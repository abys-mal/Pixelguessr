from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

from .models import Appeal, Report, Sanction
from .permissions import WorkspaceAccess
from .workspace import (
    change_access,
    change_names,
    issue,
    ordinary_players,
    resolve_report,
    reverse,
    review_appeal,
)
from .workspace_serializers import (
    SanctionInput,
    StaffActivity,
    StaffAppeal,
    StaffReport,
    StaffSanction,
    player_summary,
)


def visible_players(request):
    return User.objects.all() if request.user.is_superuser else ordinary_players()


def paginate(request, queryset, serializer):
    page = PageNumberPagination()
    page.page_size = 24
    rows = page.paginate_queryset(queryset, request)
    return page.get_paginated_response(serializer(rows, many=True).data)


@method_decorator(never_cache, name="dispatch")
class WorkspaceView(APIView):
    permission_classes = [WorkspaceAccess]


class Overview(WorkspaceView):
    def get(self, request):
        players = visible_players(request)
        return Response(
            {
                "pending_reports": Report.objects.filter(
                    subject__in=players, resolved_at__isnull=True
                ).count(),
                "pending_appeals": Appeal.objects.filter(
                    user__in=players, status="pending"
                ).count(),
                "administrator": request.user.is_superuser,
            }
        )


class Players(WorkspaceView):
    def get(self, request):
        rows = (
            visible_players(request)
            .filter(username__icontains=request.query_params.get("q", "")[:150])
            .order_by(Lower("username"), "pk")
        )
        page = PageNumberPagination()
        page.page_size = 24
        players = page.paginate_queryset(rows, request)
        return page.get_paginated_response([player_summary(user) for user in players])


class Player(WorkspaceView):
    def get(self, request, pk):
        user = get_object_or_404(visible_players(request), pk=pk)
        return Response(
            {
                "player": player_summary(user),
                "sanctions": StaffSanction(
                    user.sanctions.select_related("issued_by", "revoked_by").order_by(
                        "-starts_at", "id"
                    ),
                    many=True,
                ).data,
                "reports": StaffReport(
                    user.reports_received.select_related("reporter", "subject").order_by(
                        "-created_at"
                    ),
                    many=True,
                ).data,
                "appeals": StaffAppeal(
                    user.appeals.select_related(
                        "user", "sanction__issued_by", "sanction__revoked_by"
                    ),
                    many=True,
                ).data,
                "activity": StaffActivity(
                    user.moderation_activity.select_related("actor"), many=True
                ).data,
            }
        )


class IssueSanction(WorkspaceView):
    def post(self, request, pk):
        serializer = SanctionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            StaffSanction(issue(request.user, pk, serializer.validated_data)).data, status=201
        )


class PlayerNames(WorkspaceView):
    def post(self, request, pk):
        return Response(player_summary(change_names(request.user, pk, request.data)))


class ReverseSanction(WorkspaceView):
    def post(self, request, pk):
        return Response(StaffSanction(reverse(request.user, pk)).data)


class ReplaceSanction(WorkspaceView):
    def post(self, request, pk):
        original = get_object_or_404(Sanction, pk=pk)
        serializer = SanctionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            StaffSanction(
                issue(request.user, original.user_id, serializer.validated_data, replacing=pk)
            ).data,
            status=201,
        )


class Reports(WorkspaceView):
    def get(self, request):
        rows = (
            Report.objects.filter(subject__in=visible_players(request))
            .select_related("subject", "reporter")
            .order_by("-created_at", "id")
        )
        if request.query_params.get("status", "pending") == "pending":
            rows = rows.filter(resolved_at__isnull=True)
        return paginate(request, rows, StaffReport)


class ReportDecision(WorkspaceView):
    def post(self, request, pk):
        decision = serializers.ChoiceField(choices=["resolved", "dismissed"]).run_validation(
            request.data.get("decision")
        )
        return Response(StaffReport(resolve_report(request.user, pk, decision)).data)


class Appeals(WorkspaceView):
    def get(self, request):
        rows = Appeal.objects.filter(user__in=visible_players(request)).select_related(
            "user", "sanction__issued_by", "sanction__revoked_by"
        )
        if request.query_params.get("status", "pending") == "pending":
            rows = rows.filter(status="pending")
        return paginate(request, rows, StaffAppeal)


class AppealDecision(WorkspaceView):
    def post(self, request, pk):
        decision = serializers.ChoiceField(choices=["uphold", "reverse"]).run_validation(
            request.data.get("decision")
        )
        return Response(StaffAppeal(review_appeal(request.user, pk, decision)).data)


class ModeratorAccess(WorkspaceView):
    def post(self, request, pk):
        enabled = serializers.BooleanField().run_validation(request.data.get("enabled"))
        change_access(request.user, pk, enabled)
        return Response({"enabled": enabled})
