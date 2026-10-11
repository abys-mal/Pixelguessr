from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Sanction
from .serializers import ReportSerializer, SanctionSerializer
from .services import active_sanctions


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
        sanction = get_object_or_404(
            active_sanctions(request.user), pk=pk, kind=Sanction.Kind.WARNING
        )
        if not sanction.acknowledged_at:
            sanction.acknowledged_at = timezone.now()
            sanction.save(update_fields=["acknowledged_at"])
        return Response(SanctionSerializer(sanction).data)
