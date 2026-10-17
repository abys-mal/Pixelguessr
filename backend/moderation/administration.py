"""Administrator commands share the moderation audit and existing writer ordering."""

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User, VerifiedTitle
from games.models import Match, RankedQueue
from games.ranked_rules import rule
from library.models import ImageSubmission
from library.review import review_images

from .enforcement import schedule
from .models import Activity, StaffAnnouncement
from .permissions import is_administrator
from .services import account_restrictions, active_sanctions
from .workspace import change_access, lock_player, reverse


def require_administrator(actor):
    actor = User.objects.get(pk=actor.pk)
    if not is_administrator(actor) or account_restrictions(actor)["blocked"]:
        raise PermissionDenied("Administrator access is required.")
    return actor


def audit(actor, action, target, before, after, reason="", user=None):
    return Activity.objects.create(
        actor=actor,
        user=user,
        action=action,
        target_type=target[0],
        target_id=str(target[1]),
        reason=reason,
        changes={"before": before, "after": after},
    )


@transaction.atomic
def manage_player(actor, pk, operation, data):
    target = lock_player(pk)
    actor = require_administrator(actor)
    reason = data.get("reason", "").strip()
    if operation == "rating":
        value = data["rating"]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not rule("rating_floor") <= value <= 2_147_483_647
        ):
            raise ValidationError({"rating": "Rating is outside the supported integer bounds."})
        if Match.objects.filter(mode="ranked", status="active", participants__user=target).exists():
            raise ValidationError(
                {"detail": "Wait until the player's active duel ends before overriding Elo."}
            )
        before = {"rating": target.rating}
        if target.rating == value:
            return target
        target.rating = value
        target.save(update_fields=["rating"])
        RankedQueue.objects.filter(user=target, queued_at__isnull=False).update(
            rating_snapshot=value
        )
        after = {"rating": value}
    elif operation == "reopen":
        closures = list(active_sanctions(target).filter(kind="closed"))
        if not closures:
            raise ValidationError({"detail": "This account has no active closure."})
        before = {"closures": [str(item.pk) for item in closures]}
        for closure in closures:
            reverse(actor, closure.pk)
        after = {"closures": [], "message": "Your account has been reopened."}
    elif operation == "title":
        value = data["title"]
        if value not in {"", "pro", "master", "legend"}:
            raise ValidationError({"title": "Choose PRO, MASTER, LEGEND or remove the title."})
        current = VerifiedTitle.objects.filter(user=target).first()
        previous = current.title if current and not current.revoked_at else ""
        if value == previous:
            return target
        before = {"title": previous}
        if value:
            VerifiedTitle.objects.update_or_create(
                user=target,
                defaults={
                    "title": value,
                    "verified_by": actor,
                    "verified_at": timezone.now(),
                    "revoked_at": None,
                },
            )
        elif current:
            current.revoked_at = timezone.now()
            current.save(update_fields=["revoked_at"])
        after = {"title": value}
    elif operation == "moderator":
        enabled = data["enabled"]
        from .permissions import is_protected

        if actor.pk == target.pk or target.is_staff or target.is_superuser:
            raise ValidationError(
                {"detail": "Administrator and legacy staff roles are command-line-only."}
            )
        before = {"moderator": is_protected(target)}
        if before["moderator"] == enabled:
            return target
        change_access(actor, target.pk, enabled)
        after = {"moderator": enabled}
    else:
        raise ValidationError({"detail": "Unknown player operation."})
    audit(actor, "admin_" + operation, ("player", target.pk), before, after, reason, target)
    schedule(target.pk)
    return target


def announcement_payload(actor):
    row = StaffAnnouncement.objects.select_related("editor").filter(pk=1).first()
    visible = row and row.published and (not row.expires_at or row.expires_at > timezone.now())
    if not row or (not is_administrator(actor) and not visible):
        return None
    return {
        "title": row.title,
        "body": row.body,
        "published": row.published,
        "expires_at": row.expires_at,
        "updated_at": row.updated_at,
        "editor": row.editor.username if row.editor else None,
        "version": row.version,
    }


@transaction.atomic
def save_announcement(actor, data):
    from games.ranked import gate

    gate()
    actor = require_administrator(actor)
    row, _ = StaffAnnouncement.objects.get_or_create(pk=1)
    if row.version != data.pop("version"):
        raise ValidationError({"detail": "The announcement changed. Reload before saving."})
    before = {
        key: str(getattr(row, key)) if key == "expires_at" else getattr(row, key) for key in data
    }
    for key, value in data.items():
        setattr(row, key, value)
    row.editor = actor
    row.version += 1
    row.save()
    audit(
        actor,
        "announcement_changed",
        ("announcement", 1),
        before,
        {key: str(value) if key == "expires_at" else value for key, value in data.items()},
    )
    return announcement_payload(actor)


def image_values(image):
    return {
        "canonical_answer": image.canonical_answer,
        "accepted_synonyms": image.accepted_synonyms,
        "category": image.category_id,
        "status": image.status,
        "retired": bool(image.retired_at),
        "review_reason": image.review_reason,
        "label_verified": image.local_import_metadata.get("label_verified", False),
    }


@transaction.atomic
def edit_image(actor, pk, data):
    ImageSubmission.objects.filter(pk=pk).update(status=F("status"))
    actor = require_administrator(actor)
    image = get_object_or_404(ImageSubmission, pk=pk)
    before = image_values(image)
    for key, value in data.items():
        setattr(image, key, value)
    if image.local_import_digest:
        image.local_import_metadata = {**image.local_import_metadata, "label_verified": True}
    try:
        image.full_clean()
    except ModelValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        ) from exc
    image.save()
    after = image_values(image)
    if before != after:
        audit(actor, "image_edited", ("image", image.pk), before, after)
    return image


@transaction.atomic
def review_image(actor, pk, operation, reason=""):
    from games.ranked import gate

    gate()
    ImageSubmission.objects.filter(pk=pk).update(status=F("status"))
    actor = require_administrator(actor)
    image = get_object_or_404(ImageSubmission, pk=pk)
    before = image_values(image)
    if operation in {"approve", "reject"}:
        if operation == "reject" and not is_administrator(actor) and not reason.strip():
            raise ValidationError({"reason": "A rejection reason is required."})
        expected = "approved" if operation == "approve" else "rejected"
        if image.status == expected:
            return "skipped", image
        if operation == "approve":
            if not image.image_file:
                raise ValidationError({"detail": "Upload a private hosted image before approval."})
            from PIL import Image

            with (
                image.image_file.storage.open(image.image_file.name, "rb") as file,
                Image.open(file) as decoded,
            ):
                decoded.load()
            if image.local_import_digest:
                from library.local_import import verify_stored

                verify_stored(image)
        try:
            review_images(ImageSubmission.objects.filter(pk=pk), actor, expected)
        except ModelValidationError as exc:
            raise ValidationError(exc.messages) from exc
        image.refresh_from_db()
        image.review_reason = reason.strip()
        image.save(update_fields=["review_reason"])
    elif operation in {"retire", "restore"}:
        if image.status != "approved":
            raise ValidationError({"detail": "Only approved images can be retired or restored."})
        if bool(image.retired_at) == (operation == "retire"):
            return "skipped", image
        if (
            operation == "retire"
            and Match.objects.filter(status="active").exists()
            and not ImageSubmission.objects.filter(status="approved", retired_at__isnull=True)
            .exclude(image_file="")
            .exclude(pk=image.pk)
            .exists()
        ):
            raise ValidationError(
                {"detail": "Keep at least one playable image while games are active."}
            )
        image.retired_at = timezone.now() if operation == "retire" else None
        image.retired_by = actor if image.retired_at else None
        image.save(update_fields=["retired_at", "retired_by"])
    else:
        raise ValidationError({"detail": "Unknown image action."})
    audit(actor, "image_" + operation, ("image", image.pk), before, image_values(image), reason)
    return "success", image


@transaction.atomic
def delete_library_image(actor, pk, confirmation):
    from django.core.cache import cache
    from django.db.models import Q

    from games.models import Round
    from games.ranked import gate
    from library.file_cleanup import drain_file_deletions
    from library.models import ImportItem, PendingFileDeletion

    gate()
    actor = require_administrator(actor)
    ImageSubmission.objects.filter(pk=pk).update(status=F("status"))
    image = get_object_or_404(ImageSubmission.objects.select_related("category"), pk=pk)
    if confirmation is not True:
        raise ValidationError({"confirm": "Explicit deletion confirmation is required."})
    if image.status != "rejected" and not image.retired_at:
        raise ValidationError("Only rejected or retired images can be permanently deleted.")
    name = image.image_file.name
    references = Q(image=image)
    if name:
        references |= Q(image_storage_name=name)
    rounds = Round.objects.filter(references)
    if rounds.filter(
        match__status="active", reveal_started_at__isnull=False, ended_at__isnull=True
    ).exists():
        raise ValidationError(
            "This image is still being revealed in an active game. Retry after the round ends."
        )
    # Keep outcomes and required credit, without retaining image bytes or storage references.
    Round.objects.filter(image=image).update(
        image=None,
        image_storage_name="",
        image_metadata_snapshot={
            "license": image.license,
            "attribution": image.attribution,
            "category": image.category.name,
        },
    )
    if name:
        Round.objects.filter(image_storage_name=name, image__isnull=True).update(
            image_storage_name=""
        )
    ImportItem.objects.filter(image=image).delete()
    image.delete()
    audit(actor, "image_permanently_deleted", ("image", pk), {}, {"deleted": True})
    if name:
        job, _ = PendingFileDeletion.objects.get_or_create(name=name)
        if job.completed_at:
            job.completed_at = None
            job.save(update_fields=["completed_at"])

        def cleanup():
            cache.delete("game-source:v1:" + name)
            drain_file_deletions([job.pk])

        transaction.on_commit(cleanup, robust=True)
    return {"deleted": True, "id": str(pk)}
