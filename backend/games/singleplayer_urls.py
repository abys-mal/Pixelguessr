from django.urls import path

from .singleplayer_views import CurrentRoundView, GuessView, ImageView, RoundView, StartRoundView

urlpatterns = [
    path("current/", CurrentRoundView.as_view()),
    path("rounds/", StartRoundView.as_view()),
    path("rounds/<uuid:pk>/", RoundView.as_view()),
    path("rounds/<uuid:pk>/guesses/", GuessView.as_view()),
    path("rounds/<uuid:pk>/image/", ImageView.as_view()),
]
