from django.urls import path

from .ranked_views import (
    CancelQueueView,
    HistoryView,
    LeaderboardView,
    QueueView,
    RankedGuessView,
    RankedImageView,
    RankedLeaveView,
    RankedMatchView,
)

urlpatterns = [
    path("queue/", QueueView.as_view()),
    path("queue/cancel/", CancelQueueView.as_view()),
    path("leaderboard/", LeaderboardView.as_view()),
    path("history/<str:username>/", HistoryView.as_view()),
    path("matches/<uuid:match_id>/", RankedMatchView.as_view()),
    path("matches/<uuid:match_id>/guesses/", RankedGuessView.as_view()),
    path("matches/<uuid:match_id>/leave/", RankedLeaveView.as_view()),
    path("matches/<uuid:match_id>/rounds/<uuid:round_id>/image/", RankedImageView.as_view()),
]
