import uuid

from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.models import User
from games.models import Match, Round
from games.reveal import render_reveal
from library.models import ImageSubmission, ImportBatch, ImportItem

from .administration import (
    announcement_payload,
    audit,
    edit_image,
    manage_player,
    require_administrator,
    review_image,
    save_announcement,
)
from .administration_health import health
from .administration_imports import upload_item
from .administration_serializers import (
    AnnouncementInput,
    BatchInput,
    ImageAction,
    ImageEdit,
    PlayerAction,
)
from .models import Activity
from .permissions import AdministratorAccess
from .services import account_restrictions
from .workspace import ordinary_players
from .workspace_serializers import player_summary
from .workspace_views import WorkspaceView


def validated(kind, data):
    value = kind(data=data)
    value.is_valid(raise_exception=True)
    return value.validated_data


def page(request, rows, render):
    pagination = PageNumberPagination()
    pagination.page_size = 24
    selected = pagination.paginate_queryset(rows, request)
    return pagination.get_paginated_response([render(row) for row in selected])


def activity(row):
    return {
        "id": str(row.pk),
        "actor": row.actor.username,
        "actor_id": str(row.actor_id),
        "action": row.action,
        "target_type": row.target_type or "player",
        "target_id": row.target_id or str(row.user_id or ""),
        "created_at": row.created_at,
        "changes": row.changes,
        "reason": row.reason,
    }


def image_payload(image):
    return {
        "id": str(image.pk),
        "canonical_answer": image.canonical_answer,
        "accepted_synonyms": image.accepted_synonyms,
        "category": image.category_id,
        "category_name": image.category.name,
        "source": image.source,
        "attribution": image.attribution,
        "license": image.license,
        "source_url": image.source_url,
        "status": "retired" if image.retired_at else image.status,
        "review_reason": image.review_reason,
        "import_metadata": image.local_import_metadata,
        "preview_url": f"/api/moderation/workspace/administration/images/{image.pk}/preview/",
        "created_at": image.created_at,
    }


class AdministratorView(WorkspaceView):
    permission_classes = [AdministratorAccess]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        require_administrator(request.user)


class Overview(AdministratorView):
    def get(self, request):
        now = timezone.now()
        return Response(
            {
                "players": User.objects.count(),
                "active_games": Match.objects.filter(status="active")
                .exclude(mode="singleplayer", singleplayer_expires_at__lte=now)
                .count(),
                "playable_images": ImageSubmission.objects.filter(
                    status="approved", retired_at__isnull=True
                )
                .exclude(image_file="")
                .count(),
                "pending_images": ImageSubmission.objects.filter(status="pending").count(),
                "incomplete_imports": ImportItem.objects.filter(
                    Q(status="failed") | Q(image__status="pending")
                ).count(),
                "recent_activity": [
                    activity(row)
                    for row in Activity.objects.select_related("actor").order_by("-created_at")[:8]
                ],
                "health": health(),
                "import_tracking_note": "Browser batches are tracked here; historical CSV manifests remain private and are not scanned.",
            }
        )


class Staff(AdministratorView):
    def get(self, request):
        from django.contrib.auth.models import Permission

        permission = Permission.objects.get(
            content_type__app_label="moderation", codename="access_workspace"
        )
        rows = (
            User.objects.filter(
                Q(is_staff=True, is_superuser=True)
                | Q(user_permissions=permission)
                | Q(groups__permissions=permission)
            )
            .distinct()
            .order_by("username")
        )
        role = request.query_params.get("role", "all")
        if role == "administrators":
            rows = rows.filter(is_staff=True, is_superuser=True)
        elif role == "moderators":
            rows = rows.exclude(is_staff=True, is_superuser=True)

        def render(user):
            restrictions = account_restrictions(user)
            status = (
                "Inactive"
                if not user.is_active
                else "Closed"
                if restrictions["blocked"]
                else "Suspended"
                if restrictions["suspension"]
                else "Probation"
                if restrictions["probation"]
                else "Active"
            )
            recent = Activity.objects.filter(actor=user).order_by("-created_at").first()
            assigned = (
                Activity.objects.filter(
                    user=user, action="moderator_access_changed", changes__enabled=True
                )
                .order_by("-created_at")
                .first()
            )
            return {
                **player_summary(user),
                "role": "Administrator" if user.is_staff and user.is_superuser else "Moderator",
                "account_status": status,
                "assigned_at": assigned.created_at if assigned else None,
                "recent_activity": recent.action if recent else None,
            }

        return page(request, rows, render)


class PlayerSearch(AdministratorView):
    def get(self, request):
        q = request.query_params.get("q", "").strip()[:150]
        return page(
            request,
            ordinary_players().filter(username__icontains=q).order_by("username")
            if q
            else ordinary_players().none(),
            player_summary,
        )


class PlayerControl(AdministratorView):
    def post(self, request, pk):
        data = validated(PlayerAction, request.data)
        operation = data.pop("operation")
        return Response(player_summary(manage_player(request.user, pk, operation, data)))


class Announcement(WorkspaceView):
    def get(self, request):
        return Response({"announcement": announcement_payload(request.user)})

    def post(self, request):
        require_administrator(request.user)
        return Response(
            {
                "announcement": save_announcement(
                    request.user, validated(AnnouncementInput, request.data)
                )
            }
        )


class AuditLog(AdministratorView):
    def get(self, request):
        rows = Activity.objects.select_related("actor").order_by("-created_at", "id")
        q = request.query_params.get("q", "")[:150]
        if q:
            rows = rows.filter(
                Q(actor__username__icontains=q)
                | Q(target_id__icontains=q)
                | Q(user__username__icontains=q)
                | Q(reason__icontains=q)
                | Q(action__icontains=q)
            )
        for key in ("action", "target_type"):
            if request.query_params.get(key):
                rows = rows.filter(**{key: request.query_params[key][:64]})
        return page(request, rows, activity)


class Health(AdministratorView):
    def get(self, request):
        return Response({"checks": health()})


class Images(AdministratorView):
    def get(self, request):
        rows = ImageSubmission.objects.select_related("category").order_by("-created_at", "id")
        q = request.query_params.get("q", "").strip()[:150]
        if q:
            condition = (
                Q(canonical_answer__icontains=q)
                | Q(category__name__icontains=q)
                | Q(category__slug__icontains=q)
            )
            try:
                condition |= Q(pk=uuid.UUID(q))
            except ValueError:
                pass
            rows = rows.filter(condition)
        status = request.query_params.get("status", "")
        if status == "retired":
            rows = rows.filter(retired_at__isnull=False)
        elif status in {"approved", "pending", "rejected"}:
            rows = rows.filter(status=status, retired_at__isnull=True)
        return page(request, rows, image_payload)


class ImageDetail(AdministratorView):
    def get(self, request, pk):
        return Response(
            image_payload(
                get_object_or_404(ImageSubmission.objects.select_related("category"), pk=pk)
            )
        )

    def post(self, request, pk):
        return Response(
            image_payload(edit_image(request.user, pk, validated(ImageEdit, request.data)))
        )


class ImageReview(AdministratorView):
    def post(self, request):
        data = validated(ImageAction, request.data)
        if data["operation"] == "reject" and not data["reason"].strip():
            raise ValidationError({"reason": "A rejection reason is required."})
        results = []
        for pk in dict.fromkeys(data["ids"]):
            try:
                state, _ = review_image(request.user, pk, data["operation"], data["reason"])
                results.append({"id": str(pk), "status": state})
            except Exception as exc:
                from django.http import Http404
                from rest_framework.exceptions import APIException

                message = (
                    str(exc.detail)
                    if isinstance(exc, APIException)
                    else "Image not found."
                    if isinstance(exc, Http404)
                    else "Image action failed. Check private storage and retry."
                )
                results.append({"id": str(pk), "status": "failed", "error": message})
        return Response({"results": results})


class ImagePreview(AdministratorView):
    def get(self, request, pk):
        image = get_object_or_404(ImageSubmission, pk=pk)
        if not image.image_file:
            raise ValidationError("No private hosted image is available.")
        if request.query_params.get("reveal") is not None:
            count = serializers.IntegerField(min_value=0, max_value=400).run_validation(
                request.query_params["reveal"]
            )
            # Stable row-major order makes the actual compositor easy to inspect at each step.
            game_round = Round(
                image_storage_name=image.image_file.name,
                grid_size=20,
                reveal_order=list(range(400)),
            )
            content, _ = render_reveal(game_round, timezone.now(), count=count)
            response = HttpResponse(content, content_type="image/webp")
        else:
            try:
                response = FileResponse(
                    image.image_file.storage.open(image.image_file.name, "rb"),
                    content_type="image/webp",
                )
            except OSError as exc:
                raise ValidationError("Private image storage is unavailable.") from exc
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


def batch_payload(batch):
    return {
        "id": str(batch.pk),
        "name": batch.name,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "items": batch.items.count(),
        "failed": batch.items.filter(status="failed").count(),
        "pending": batch.items.filter(image__status="pending").count(),
    }


def item_payload(item):
    return {
        "id": str(item.pk),
        "filename": item.filename,
        "status": item.status,
        "error": item.error,
        "image": image_payload(item.image) if item.image else None,
    }


class Batches(AdministratorView):
    def get(self, request):
        return page(request, ImportBatch.objects.order_by("-created_at", "id"), batch_payload)

    def post(self, request):
        actor = require_administrator(request.user)
        from django.db import transaction

        with transaction.atomic():
            row = ImportBatch.objects.create(
                created_by=actor, **validated(BatchInput, request.data)
            )
            audit(actor, "import_batch_created", ("import_batch", row.pk), {}, {"name": row.name})
        return Response(batch_payload(row), status=201)


class BatchDetail(AdministratorView):
    def get(self, request, pk):
        batch = get_object_or_404(ImportBatch, pk=pk)
        return page(
            request,
            batch.items.select_related("image__category").order_by("created_at", "id"),
            item_payload,
        )

    def post(self, request, pk):
        if set(request.data) - {"request_id", "file"}:
            raise ValidationError("Unexpected upload fields.")
        request_id = serializers.UUIDField().run_validation(request.data.get("request_id"))
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Choose an image."})
        if upload.size > 8 * 1024 * 1024:
            raise ValidationError({"file": "Maximum upload size is 8 MiB."})
        return Response(item_payload(upload_item(request.user, pk, request_id, upload)), status=201)
