from django.urls import path

from . import administration_views as views
from .ip_views import IPDetail, IPList

urlpatterns = [
    path("ip-access/<str:list_kind>/", IPList.as_view()),
    path("ip-access/<str:list_kind>/<uuid:pk>/", IPDetail.as_view()),
    path("", views.Overview.as_view()),
    path("staff/", views.Staff.as_view()),
    path("players/", views.PlayerSearch.as_view()),
    path("players/<uuid:pk>/delete/", views.PermanentAccountDeletion.as_view()),
    path("players/<uuid:pk>/", views.PlayerControl.as_view()),
    path("announcement/", views.Announcement.as_view()),
    path("audit/", views.AuditLog.as_view()),
    path("health/", views.Health.as_view()),
    path("player-submissions/", views.PlayerSubmissions.as_view()),
    path("player-submissions/<uuid:pk>/review/", views.PlayerSubmissionReview.as_view()),
    path("images/", views.Images.as_view()),
    path("images/review/", views.ImageReview.as_view()),
    path("images/<uuid:pk>/delete/", views.PermanentImageDeletion.as_view()),
    path("images/<uuid:pk>/", views.ImageDetail.as_view()),
    path("images/<uuid:pk>/preview/", views.ImagePreview.as_view()),
    path("imports/", views.Batches.as_view()),
    path("imports/<uuid:pk>/", views.BatchDetail.as_view()),
]
