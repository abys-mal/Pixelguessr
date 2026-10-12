from django.urls import path

from .consumers import UnavailableMatchConsumer
from .party_consumer import PartyConsumer

websocket_urlpatterns = [
    path("ws/parties/<str:code>/", PartyConsumer.as_asgi()),
    path("ws/matches/<uuid:match_id>/", UnavailableMatchConsumer.as_asgi()),
]
