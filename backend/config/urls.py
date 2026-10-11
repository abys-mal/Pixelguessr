from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", include("core.urls")),
    path("api/auth/", include("accounts.urls")),
    path("api/library/", include("library.urls")),
    path("api/moderation/", include("moderation.urls")),
    path("api/modes/", include("games.urls")),
]
