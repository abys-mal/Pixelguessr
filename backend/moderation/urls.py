from django.urls import path

from . import portal
from . import workspace_views as workspace
from .views import AcknowledgeView, MySanctionsView, ReportView

urlpatterns = [
    path("notice-login/", portal.NoticeLogin.as_view()),
    path("notices/", portal.MyNotices.as_view()),
    path("sanctions/<uuid:pk>/appeal/", portal.SubmitAppeal.as_view()),
    path("workspace/", workspace.Overview.as_view()),
    path("workspace/players/", workspace.Players.as_view()),
    path("workspace/players/<uuid:pk>/", workspace.Player.as_view()),
    path("workspace/players/<uuid:pk>/sanctions/", workspace.IssueSanction.as_view()),
    path("workspace/players/<uuid:pk>/access/", workspace.ModeratorAccess.as_view()),
    path("workspace/sanctions/<uuid:pk>/reverse/", workspace.ReverseSanction.as_view()),
    path("workspace/sanctions/<uuid:pk>/replace/", workspace.ReplaceSanction.as_view()),
    path("workspace/reports/", workspace.Reports.as_view()),
    path("workspace/reports/<uuid:pk>/resolve/", workspace.ReportDecision.as_view()),
    path("workspace/appeals/", workspace.Appeals.as_view()),
    path("workspace/appeals/<uuid:pk>/resolve/", workspace.AppealDecision.as_view()),
    path("reports/", ReportView.as_view()),
    path("sanctions/", MySanctionsView.as_view()),
    path("sanctions/<uuid:pk>/acknowledge/", AcknowledgeView.as_view()),
]
