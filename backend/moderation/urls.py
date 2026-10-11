from django.urls import path

from .views import AcknowledgeView, MySanctionsView, ReportView

urlpatterns = [
    path("reports/", ReportView.as_view()),
    path("sanctions/", MySanctionsView.as_view()),
    path("sanctions/<uuid:pk>/acknowledge/", AcknowledgeView.as_view()),
]
