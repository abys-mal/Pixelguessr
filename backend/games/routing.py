from django.urls import path

from accounts.consumer import AccountConsumer

from .party_consumer import PartyConsumer
from .ranked_consumer import RankedConsumer

websocket_urlpatterns = [
    path("ws/account/", AccountConsumer.as_asgi()),
    path("ws/ranked/queue/<uuid:ticket>/", RankedConsumer.as_asgi()),
    path("ws/parties/<str:code>/", PartyConsumer.as_asgi()),
    path("ws/matches/<uuid:match_id>/", RankedConsumer.as_asgi()),
]
