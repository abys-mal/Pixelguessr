from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import AccountAccess, CanSubmitImages
from moderation.permissions import AdministratorAccess

from .models import Category, ImageSubmission
from .serializers import (
    CategorySerializer,
    ContributionInput,
    PublicImageSerializer,
    SubmissionSerializer,
)


class CategoryList(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CategorySerializer
    queryset = Category.objects.order_by("name")
    pagination_class = None


class PublicCatalog(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = PublicImageSerializer
    queryset = ImageSubmission.objects.filter(
        status=ImageSubmission.Status.APPROVED, retired_at__isnull=True
    ).select_related("category")


class MySubmissions(generics.ListCreateAPIView):
    permission_classes = [CanSubmitImages]
    serializer_class = SubmissionSerializer

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "submission"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        return ImageSubmission.objects.filter(submitted_by=self.request.user)

    def get_serializer_class(self):
        return ContributionInput if self.request.method == "POST" else SubmissionSerializer

    def perform_create(self, serializer):
        from .contributions import create_contribution

        serializer.instance = create_contribution(self.request.user, serializer.validated_data)


class PrivatePreview(APIView):
    permission_classes = [AdministratorAccess, AccountAccess]

    def get(self, request, pk):
        image = get_object_or_404(ImageSubmission, pk=pk)
        if not image.image_file:
            from rest_framework.exceptions import NotFound

            raise NotFound("This submission uses an external reference.")
        response = FileResponse(
            image.image_file.open("rb"), content_type="image/webp", filename=f"{image.id}.webp"
        )
        response["Cache-Control"] = "private, no-store"
        return response
