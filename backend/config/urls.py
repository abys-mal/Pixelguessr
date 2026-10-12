from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", include("core.urls")),
    path("api/auth/", include("accounts.urls")),
    path("api/library/", include("library.urls")),
    path("api/moderation/", include("moderation.urls")),
    path("api/ranked/", include("games.ranked_urls")),
    path("api/parties/", include("games.party_urls")),
    path("api/modes/", include("games.urls")),
    path("api/games/singleplayer/", include("games.singleplayer_urls")),
]
