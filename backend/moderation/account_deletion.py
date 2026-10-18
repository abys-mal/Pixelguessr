"""Sensitive account erasure preserves anonymized shared history and licensed approved images."""

import re
import uuid

from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError

from accounts.lifecycle import invalidate_sessions
from accounts.models import User
from games.models import Guess, Match, Participant, Party, PartyMember, Round
from games.ranked import gate
from library.file_cleanup import drain_file_deletions
from library.models import ImageSubmission, ImportBatch, ImportItem, PendingFileDeletion

from .administration import audit, require_administrator
from .enforcement import enforce_locked, schedule
from .models import Activity, Appeal, Report, Sanction, StaffAnnouncement
from .permissions import is_protected
from .services import active_sanctions


def deletion_eligible(actor, user):
    return bool(
        actor.pk != user.pk
        and not is_protected(user)
        and active_sanctions(user).filter(kind="closed").exists()
    )


def redact(value, identities):
    if isinstance(value, dict):
        return {key: redact(item, identities) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, identities) for item in value]
    if isinstance(value, str):
        for identity in identities:
            if identity:
                value = re.sub(
                    r"(?<!\w)" + re.escape(identity) + r"(?!\w)",
                    "Deleted account",
                    value,
                    flags=re.IGNORECASE,
                )
    return value


@transaction.atomic
@sensitive_variables()
def delete_account(actor, user_id, data):
    gate()
    User.objects.filter(pk__in=[actor.pk, user_id]).update(
        last_username_change=F("last_username_change")
    )
    actor = require_administrator(actor)
    user = User.objects.filter(pk=user_id).first()
    if not user or not deletion_eligible(actor, user):
        raise ValidationError(
            "Only a closed, unprotected account other than your own can be permanently deleted."
        )
    if not actor.check_password(data.get("current_password", "")):
        raise ValidationError({"current_password": "Current password is incorrect."})
    reason = data.get("reason", "")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise ValidationError({"reason": "A deletion reason is required."})
    if data.get("confirmation") != user.username:
        raise ValidationError({"confirmation": "Type the exact target username."})
    # All checks are repeated on fresh rows under the existing writer gate.
    identities = [user.email, user.username, user.display_name, str(user.pk), user.pk.hex]
    images = ImageSubmission.objects.filter(submitted_by=user)
    image_ids = list(images.values_list("pk", flat=True))
    removed_ids = list(images.exclude(status="approved").values_list("pk", flat=True))
    if Round.objects.filter(image_id__in=removed_ids, match__status="active").exists():
        raise ValidationError(
            "An unapproved submission is in an active game. Retry after the game ends."
        )
    enforce_locked(user.pk)
    session_count = invalidate_sessions(user.pk)
    # Delete only exclusively owned singleplayer matches; shared games remain intact.
    solo_ids = list(
        Match.objects.annotate(people=Count("participants"))
        .filter(mode="singleplayer", participants__user=user, people=1)
        .exclude(parties__isnull=False)
        .values_list("pk", flat=True)
    )
    Round.objects.filter(match_id__in=solo_ids).update(winner=None, is_decisive=False)
    Match.objects.filter(pk__in=solo_ids).update(ranked_winner=None)
    # These queues are account-specific and may otherwise protect an owned match.
    from games.models import RankedConnection, RankedQueue

    RankedQueue.objects.filter(user=user).delete()
    RankedConnection.objects.filter(user=user).delete()
    Match.objects.filter(pk__in=solo_ids).delete()
    Guess.objects.filter(participant__user=user).delete()
    shared = Participant.objects.filter(user=user).count()
    Participant.objects.filter(user=user).update(
        user=None,
        identity_deleted=True,
        rating_before=None,
        rating_after=None,
        rating_delta=None,
        rated_matches_before=None,
        ranked_last_seen=None,
        ranked_disconnected_at=None,
    )
    parties = list(PartyMember.objects.filter(user=user).values_list("party_id", flat=True))
    for member in PartyMember.objects.filter(user=user):
        member.user = None
        member.identity_deleted = True
        member.display_name = "Deleted player"
        member.name_key = "deleted-" + uuid.uuid4().hex
        member.left_at = member.left_at or timezone.now()
        member.save(
            update_fields=["user", "identity_deleted", "display_name", "name_key", "left_at"]
        )
    for party in Party.objects.filter(pk__in=parties):
        party.message = redact(party.message, identities)
        party.save(update_fields=["message"])
    # Strip account-owned free text and filenames, retaining licensing and integrity provenance.
    approved_count = images.filter(status="approved").count()
    for image in images.filter(status="approved"):
        image.local_import_metadata = {
            key: value
            for key, value in image.local_import_metadata.items()
            if key
            not in {
                "original_filename",
                "description",
                "review_notes",
                "submitter",
                "submitter_email",
                "submitter_username",
            }
        }
        image.submitted_by = None
        image.review_reason = redact(image.review_reason, identities)
        image.player_review_explanation = ""
        image.save(
            update_fields=[
                "submitted_by",
                "local_import_metadata",
                "review_reason",
                "player_review_explanation",
            ]
        )
        ImportItem.objects.filter(image=image).update(filename="Anonymized submission")
    files = list(
        ImageSubmission.objects.filter(pk__in=removed_ids)
        .exclude(image_file="")
        .values_list("image_file", flat=True)
    )
    Round.objects.filter(image_id__in=removed_ids).update(image=None, image_storage_name="")
    ImportItem.objects.filter(image_id__in=removed_ids).update(
        image=None, filename="Deleted submission", error=""
    )
    ImageSubmission.objects.filter(pk__in=removed_ids).delete()
    # Preserve other subjects' records while removing this account's actor identity.
    events = Activity.objects.filter(
        Q(user=user)
        | Q(actor=user)
        | Q(target_type="player", target_id=str(user.pk))
        | Q(sanction__user=user)
        | Q(appeal__user=user)
        | Q(report__subject=user)
    )
    events.filter(
        Q(user=user)
        | Q(target_type="player", target_id=str(user.pk))
        | Q(sanction__user=user)
        | Q(appeal__user=user)
        | Q(report__subject=user)
    ).delete()
    for event in Activity.objects.filter(
        Q(actor=user) | Q(target_type="image", target_id__in=[str(pk) for pk in image_ids])
    ):
        if event.actor_id == user.pk:
            event.actor = None
        event.reason = redact(event.reason, identities)
        event.changes = redact(event.changes, identities)
        event.save(update_fields=["actor", "reason", "changes"])
    for report in Report.objects.filter(reporter=user).exclude(subject=user):
        report.details = redact(report.details, identities)
        report.reporter = None
        report.save(update_fields=["details", "reporter"])
    Appeal.objects.filter(Q(user=user) | Q(sanction__user=user)).delete()
    Sanction.objects.filter(user=user).update(replaces=None)
    Sanction.objects.filter(user=user).delete()
    Report.objects.filter(subject=user).delete()
    ImportItem.objects.filter(batch__created_by=user).update(
        filename="Anonymized submission", error=""
    )
    ImportBatch.objects.filter(created_by=user).update(name="Anonymized batch")
    for announcement in StaffAnnouncement.objects.filter(editor=user):
        announcement.title = redact(announcement.title, identities)
        announcement.body = redact(announcement.body, identities)
        announcement.save(update_fields=["title", "body"])
    content_type = ContentType.objects.get_for_model(User)
    LogEntry.objects.filter(
        Q(user=user) | Q(content_type=content_type, object_id=str(user.pk))
    ).delete()
    # Deleting credentials now leaves nullable professional/metadata references anonymous.
    ImageSubmission.objects.filter(reviewed_by=user).update(reviewer_deleted=True)
    Sanction.objects.filter(revoked_by=user).update(revoker_deleted=True)
    user.delete()
    job_ids = []
    for name in set(files):
        job, _ = PendingFileDeletion.objects.get_or_create(name=name)
        if job.completed_at:
            job.completed_at = None
            job.save(update_fields=["completed_at"])
        job_ids.append(job.pk)
    reference = uuid.uuid4()
    outcome = {
        "approved_images_preserved": approved_count,
        "unapproved_images_deleted": len(removed_ids),
        "shared_participants_anonymized": shared,
        "solo_games_deleted": len(solo_ids),
        "sessions_deleted": session_count,
        "files_scheduled": len(job_ids),
    }
    audit(
        actor,
        "account_permanently_deleted",
        ("deletion", reference),
        {},
        outcome,
        redact(reason, identities),
    )
    schedule(user_id)
    transaction.on_commit(lambda: drain_file_deletions(job_ids), robust=True)
    return {"reference": str(reference), "outcome": outcome}
