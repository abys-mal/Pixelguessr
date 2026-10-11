from django.urls import path

from .consumers import UnavailableMatchConsumer

websocket_urlpatterns = [path("ws/matches/<uuid:match_id>/", UnavailableMatchConsumer.as_asgi())]
