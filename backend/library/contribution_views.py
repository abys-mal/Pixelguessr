from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import AccountAccess, CanSubmitImages
from config.pagination import ResilientPageNumberPagination as PageNumberPagination
from moderation.permissions import is_administrator

from .contributions import contribution_data, create_contribution, history_item, history_rows
from .models import ImageSubmission, RemovedContribution
from .serializers import ContributionInput


@method_decorator(never_cache, name="dispatch")
class Contributions(APIView):
    permission_classes = [IsAuthenticated, AccountAccess]

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.request.method == "POST":
            permissions.append(CanSubmitImages())
        return permissions

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "submission"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get(self, request):
        images = ImageSubmission.objects.filter(player_contribution=True, submitted_by=request.user)
        receipts = RemovedContribution.objects.filter(submitted_by=request.user)
        stats = {
            "total": images.count() + receipts.count(),
            "pending": images.filter(status="pending").count(),
            "approved": images.filter(status="approved").count(),
        }
        status = serializers.ChoiceField(
            choices=["all", "pending", "approved", "rejected", "removed"]
        ).run_validation(request.query_params.get("status", "all"))
        if status == "removed":
            images = images.none()
        elif status != "all":
            images = images.filter(status=status)
            receipts = receipts.none()
        pagination = PageNumberPagination()
        pagination.page_size = 24
        rows = pagination.paginate_queryset(history_rows(images, receipts), request)
        response = pagination.get_paginated_response(
            [history_item(row["id"], request.user) for row in rows]
        )
        response.data["stats"] = stats
        return response

    def post(self, request):
        serializer = ContributionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = create_contribution(request.user, serializer.validated_data)
        return Response(contribution_data(image), status=201)


@method_decorator(never_cache, name="dispatch")
class ContributionDetail(APIView):
    permission_classes = [IsAuthenticated, AccountAccess]

    def get(self, request, pk):
        return Response(history_item(pk, request.user))


@method_decorator(never_cache, name="dispatch")
class ContributionPreview(APIView):
    permission_classes = [IsAuthenticated, AccountAccess]

    def get(self, request, pk):
        images = ImageSubmission.objects.filter(player_contribution=True)
        if not is_administrator(request.user):
            images = images.filter(submitted_by=request.user)
        image = get_object_or_404(images, pk=pk)
        if not image.image_file:
            from rest_framework.exceptions import NotFound

            raise NotFound("No retained private image is available.")
        try:
            file = image.image_file.open("rb")
        except (OSError, ValueError):
            from rest_framework.exceptions import NotFound

            raise NotFound("No retained private image is available.") from None
        return FileResponse(file, content_type="image/webp", filename=f"{image.pk}.webp")
