from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Sanction
from .serializers import ReportSerializer, SanctionSerializer
from .services import active_sanctions
from .workspace import submit_appeal
from .workspace_serializers import PlayerAppeal, PlayerNotice


@method_decorator(never_cache, name="dispatch")
class MyNotices(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "sanctions": PlayerNotice(
                    request.user.sanctions.order_by("-starts_at"), many=True
                ).data,
                "appeals": PlayerAppeal(request.user.appeals.all(), many=True).data,
                "updates": [
                    {
                        "message": "Your account has been reopened. Other active sanctions still apply.",
                        "created_at": row.created_at,
                    }
                    for row in request.user.moderation_activity.filter(
                        action="admin_reopen"
                    ).order_by("-created_at")[:10]
                ],
            }
        )


class SubmitAppeal(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        explanation = serializers.CharField(max_length=4000).run_validation(
            request.data.get("explanation")
        )
        return Response(PlayerAppeal(submit_appeal(request.user, pk, explanation)).data, status=201)


class ReportView(generics.CreateAPIView):
    serializer_class = ReportSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "report"

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)


class MySanctionsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SanctionSerializer

    def get_queryset(self):
        return active_sanctions(self.request.user).order_by("-starts_at")


class AcknowledgeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        warnings = active_sanctions(request.user).filter(pk=pk, kind=Sanction.Kind.WARNING)
        # One conditional write preserves the first acknowledgment under concurrent retries.
        warnings.filter(acknowledged_at__isnull=True).update(acknowledged_at=timezone.now())
        sanction = get_object_or_404(warnings)
        from django.db import transaction

        from .enforcement import publish_account

        transaction.on_commit(lambda: publish_account(request.user.pk), robust=True)
        return Response(SanctionSerializer(sanction).data)
