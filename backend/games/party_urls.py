from django.urls import path

from .party_views import (
    PartyActionView,
    PartyCreateView,
    PartyGuessView,
    PartyImageView,
    PartyJoinView,
    PartyKickView,
    PartyView,
)

urlpatterns = [
    path("", PartyCreateView.as_view()),
    path("<str:code>/", PartyView.as_view()),
    path("<str:code>/join/", PartyJoinView.as_view()),
    path("<str:code>/kick/", PartyKickView.as_view()),
    path("<str:code>/guesses/", PartyGuessView.as_view()),
    path("<str:code>/rounds/<uuid:pk>/image/", PartyImageView.as_view()),
    *[
        path(f"<str:code>/{action}/", PartyActionView.as_view(), {"action": action})
        for action in ("start", "leave", "lobby", "next")
    ],
]
