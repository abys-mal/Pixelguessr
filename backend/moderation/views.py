from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import ReportSerializer, SanctionSerializer
from .services import active_sanctions
from .workspace import acknowledge_warning, submit_appeal, submit_report
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
                # Reopening events stay in the staff audit, not player standing.
                "updates": [],
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
        serializer.instance = submit_report(self.request.user, **serializer.validated_data)


class MySanctionsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SanctionSerializer

    def get_queryset(self):
        return active_sanctions(self.request.user).order_by("-starts_at")


class AcknowledgeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        return Response(SanctionSerializer(acknowledge_warning(request.user, pk)).data)
