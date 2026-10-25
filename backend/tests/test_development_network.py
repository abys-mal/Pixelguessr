import runpy
from pathlib import Path
from unittest.mock import patch

import pytest
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.testing import WebsocketCommunicator
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient

from config.development import development_network
from core.client_ip import resolve_client_ip, scope_ip
from games.routing import websocket_urlpatterns
from moderation.models import IPAccessEntry

LAN = "192.168.1.50"
CLIENT = "192.168.1.60"
PROXY = "127.0.0.2"


def network(**changes):
    return development_network(
        **{
            "debug": True,
            "hosts": ["localhost", "127.0.0.1"],
            "origins": ["http://localhost:5173"],
            "proxies": [],
            "lan_ip": LAN,
            **changes,
        }
    )


def configure(settings):
    settings.ALLOWED_HOSTS, settings.CSRF_TRUSTED_ORIGINS, settings.IP_TRUSTED_PROXIES = network()


def test_lan_settings_extend_exact_hosts_origins_and_proxy():
    hosts, origins, proxies = network(frontend_port=5190)
    assert hosts == ["localhost", "127.0.0.1", LAN]
    assert origins == [
        "http://localhost:5173",
        "http://localhost:5190",
        "http://127.0.0.1:5190",
        f"http://{LAN}:5190",
    ]
    assert proxies == [PROXY + "/32"]
    assert network(lan_ip="")[2] == proxies  # Localhost proxying also preserves client identity.


def test_settings_read_lan_environment_without_overwriting_explicit_lists(monkeypatch):
    for key, value in {
        "DEBUG": "True",
        "USE_SQLITE": "True",
        "LOCAL_SERVICES": "True",
        "DEV_LAN_IP": LAN,
        "DEV_FRONTEND_PORT": "5190",
        "ALLOWED_HOSTS": "custom.test",
        "CSRF_TRUSTED_ORIGINS": "http://custom.test:5190",
        "IP_TRUSTED_PROXIES": "10.0.0.1/32",
    }.items():
        monkeypatch.setenv(key, value)
    values = runpy.run_path(str(Path(__file__).parents[1] / "config/settings.py"))
    assert values["ALLOWED_HOSTS"] == ["custom.test", "localhost", "127.0.0.1", LAN]
    assert f"http://{LAN}:5190" in values["CSRF_TRUSTED_ORIGINS"]
    assert "http://custom.test:5190" in values["CSRF_TRUSTED_ORIGINS"]
    assert values["IP_TRUSTED_PROXIES"] == ["10.0.0.1/32", PROXY + "/32"]


@pytest.mark.parametrize("lan_ip", ["*", "0.0.0.0", "127.0.0.1", "8.8.8.8", LAN + "/24"])
def test_invalid_lan_host_rejected(lan_ip):
    with pytest.raises(ImproperlyConfigured):
        network(lan_ip=lan_ip)


def test_no_development_trust_or_hosts_in_production():
    assert network(debug=False, lan_ip="") == (
        ["localhost", "127.0.0.1"],
        ["http://localhost:5173"],
        [],
    )
    with pytest.raises(ImproperlyConfigured, match="DEBUG"):
        network(debug=False)


def test_localhost_custom_port_and_invalid_port():
    assert "http://127.0.0.1:5190" in network(lan_ip="", frontend_port=5190)[1]
    with pytest.raises(ImproperlyConfigured, match="PORT"):
        network(frontend_port=0)


def test_lan_proxy_identity_is_exact_and_direct_spoofing_ignored(settings):
    configure(settings)
    assert resolve_client_ip(PROXY, CLIENT) == CLIENT
    assert resolve_client_ip(PROXY, "127.0.0.1") == "127.0.0.1"
    assert resolve_client_ip(PROXY, "::1") == "::1"
    assert resolve_client_ip(CLIENT, "1.2.3.4") == CLIENT
    assert (
        scope_ip({"client": (PROXY, 1234), "headers": [(b"x-forwarded-for", CLIENT.encode())]})
        == CLIENT
    )


@pytest.mark.django_db
def test_lan_authentication_cookies_and_csrf(settings, user):
    configure(settings)
    client = APIClient(enforce_csrf_checks=True)
    headers = {
        "HTTP_HOST": LAN + ":5173",
        "HTTP_ORIGIN": f"http://{LAN}:5173",
        "REMOTE_ADDR": PROXY,
        "HTTP_X_FORWARDED_FOR": CLIENT,
    }
    token = client.get("/api/auth/csrf/", **headers).json()["csrfToken"]
    credentials = {"username": user.username, "password": "a-strong-unique-pass-734"}
    assert client.post("/api/auth/login/", credentials, format="json", **headers).status_code == 403
    assert (
        client.post(
            "/api/auth/login/", credentials, format="json", HTTP_X_CSRFTOKEN=token, **headers
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me/", **headers).json()["user"]["id"] == str(user.pk)
    token = client.get("/api/auth/csrf/", **headers).json()["csrfToken"]
    assert (
        client.post(
            "/api/auth/logout/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            **{**headers, "HTTP_ORIGIN": "http://untrusted.example:5173"},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/health/live/", **{**headers, "HTTP_HOST": "evil.example"}).status_code
        == 400
    )


@pytest.mark.django_db
def test_lan_blacklist_uses_actual_client_and_keeps_login_policy(settings, user):
    configure(settings)
    IPAccessEntry.objects.create(
        list_kind="blacklist", address=CLIENT, reason="Synthetic LAN test", block_singleplayer=True
    )
    client = APIClient()
    headers = {"HTTP_HOST": LAN + ":5173", "REMOTE_ADDR": PROXY, "HTTP_X_FORWARDED_FOR": CLIENT}
    assert (
        client.get("/api/games/singleplayer/current/", **headers).json()["code"] == "ip_restricted"
    )
    client.force_login(user)
    assert client.get("/api/auth/me/", **headers).json()["user"]["id"] == str(user.pk)
    IPAccessEntry.objects.update(block_login=True)
    assert client.get("/api/auth/me/", **headers).json()["user"] is None


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin, allowed", [(f"http://{LAN}:5173", True), ("http://evil.example", False)]
)
async def test_lan_websocket_origin_routing_and_ip_enforcement(settings, origin, allowed):
    configure(settings)
    from channels.db import database_sync_to_async

    app = AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)))
    with patch("games.party_consumer.socket_state", return_value={"status": "test"}) as read:
        socket = WebsocketCommunicator(
            app,
            "/ws/parties/ABCDEF/",
            headers=[
                (b"host", f"{LAN}:5173".encode()),
                (b"origin", origin.encode()),
                (b"x-forwarded-for", CLIENT.encode()),
            ],
        )
        socket.scope["client"] = (PROXY, 1234)
        connected, _ = await socket.connect()
        assert connected is allowed
        if connected:
            assert (await socket.receive_json_from())["type"] == "state"
            await database_sync_to_async(IPAccessEntry.objects.create)(
                list_kind="blacklist",
                address=CLIENT,
                reason="Synthetic LAN test",
                block_parties=True,
            )
            await socket.send_json_to({"type": "heartbeat"})
            assert (await socket.receive_json_from())["code"] == "ip_restricted"
            assert (await socket.receive_output())["code"] == 4403
        else:
            assert not read.called
        await socket.disconnect()
