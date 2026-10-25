from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import User
from core.client_ip import ClientIPError, normalize_ip, resolve_client_ip, scope_ip
from moderation.ip_management import BlacklistInput, delete_entry, save_entry
from moderation.ip_middleware import activity_for_http
from moderation.ip_rules import (
    ACTIVITIES,
    IPAccessDenied,
    enforce_ip,
    restrictions_for_ip,
    staff_exempt,
)
from moderation.models import Activity, IPAccessEntry, Sanction

ROOT = "/api/moderation/workspace/administration/ip-access/"
IP = "198.51.100.27"
OTHER = "203.0.113.9"
pytestmark = pytest.mark.django_db


@pytest.fixture
def administrator():
    return User.objects.create_superuser(username="ip_administrator", email="ip-admin@example.test")


@pytest.fixture
def admin_client(client, administrator):
    client.force_authenticate(administrator)
    return client


def rule(activity="singleplayer", address=IP, **kwargs):
    return IPAccessEntry.objects.create(
        list_kind="blacklist",
        address=address,
        reason="Sensitive internal investigation",
        **{"block_" + activity: True},
        **kwargs,
    )


def black_payload(address=IP, **kwargs):
    return {
        "address": address,
        "reason": "Internal review",
        "activities": ["singleplayer"],
        "duration": "indefinite",
        **kwargs,
    }


def grant_staff(user, role):
    if role == "administrator":
        user.is_staff = user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
    else:
        permission = Permission.objects.get(codename="access_workspace")
        if role == "group_moderator":
            group = Group.objects.create(name="IP test moderators")
            group.permissions.add(permission)
            user.groups.add(group)
        else:
            user.user_permissions.add(permission)


@pytest.mark.parametrize("role", ["administrator", "moderator", "group_moderator"])
@pytest.mark.parametrize("activity", list(ACTIVITIES))
def test_staff_exempt_from_each_http_restriction(client, user, role, activity):
    grant_staff(user, role)
    client.force_login(user)
    rule(activity)
    method, path = HTTP_PATHS[activity]
    data = (
        {"username": user.username, "password": "a-strong-unique-pass-734"}
        if activity == "login"
        else {}
    )
    response = getattr(client, method)(path, data, format="json", REMOTE_ADDR=IP)
    assert response.json().get("code") not in {"ip_restricted", "client_ip_unavailable"}
    if activity == "login":
        assert response.status_code == 200 and client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.parametrize("role", ["administrator", "moderator", "group_moderator"])
def test_staff_can_sign_in_from_blocked_ip_but_wrong_password_cannot(client, user, role):
    grant_staff(user, role)
    rule("login")
    payload = {"username": user.username, "password": "wrong password"}
    assert (
        client.post("/api/auth/login/", payload, format="json", REMOTE_ADDR=IP).status_code == 400
    )
    assert "_auth_user_id" not in client.session
    payload["password"] = "a-strong-unique-pass-734"
    assert (
        client.post("/api/auth/login/", payload, format="json", REMOTE_ADDR=IP).status_code == 200
    )


def test_admin_site_login_from_blocked_ip(client, administrator):
    administrator.set_password("a-strong-unique-pass-734")
    administrator.save(update_fields=["password"])
    rule("login")
    response = client.post(
        "/admin/login/",
        {
            "username": administrator.username,
            "password": "a-strong-unique-pass-734",
            "next": "/admin/",
        },
        REMOTE_ADDR=IP,
    )
    assert response.status_code == 302 and client.session["_auth_user_id"] == str(administrator.pk)


def test_staff_exemption_uses_current_roles_and_preserves_account_rules(
    client, user, administrator
):
    assert not staff_exempt(user)
    grant_staff(user, "moderator")
    assert staff_exempt(user)
    rule("submissions", block_login=True)
    client.force_login(user)
    # A network exemption does not grant administrator access or bypass CSRF.
    assert client.get(ROOT + "blacklist/", REMOTE_ADDR=IP).status_code == 403
    csrf = APIClient(enforce_csrf_checks=True)
    csrf.force_login(user)
    assert csrf.post("/api/library/contributions/", {}, REMOTE_ADDR=IP).status_code == 403
    Sanction.objects.create(
        user=user,
        issued_by=administrator,
        kind="probation",
        category="other",
        reason="Submission restriction",
    )
    assert (
        client.post("/api/library/contributions/", {}, format="json", REMOTE_ADDR=IP).status_code
        == 403
    )
    user.user_permissions.clear()
    assert not staff_exempt(user)
    response = client.post("/api/library/contributions/", {}, format="json", REMOTE_ADDR=IP)
    assert response.status_code == 403 and response.json()["code"] == "ip_restricted"


@pytest.mark.parametrize("role", ["staff_only", "superuser_only", "inactive_moderator"])
def test_partial_or_inactive_roles_are_not_staff_exempt(user, role):
    if role == "inactive_moderator":
        grant_staff(user, "moderator")
        user.is_active = False
    else:
        user.is_staff = role == "staff_only"
        user.is_superuser = role == "superuser_only"
    user.save()
    assert not staff_exempt(user)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("192.0.2.1", "192.0.2.1"),
        (" 192.0.2.1 ", "192.0.2.1"),
        ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        ("::ffff:192.0.2.1", "192.0.2.1"),
        ("::FFFF:C000:201", "192.0.2.1"),
        ("::1", "::1"),
    ],
)
def test_address_normalization(raw, expected):
    assert normalize_ip(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "hostname.test",
        "192.0.2.1/32",
        "::/0",
        "192.0.2.1:80",
        "fe80::1%eth0",
        "001.2.3.4",
        "",
        None,
        "2130706433",
    ],
)
def test_invalid_addresses(raw):
    with pytest.raises(ClientIPError):
        normalize_ip(raw)


def test_proxy_chain_and_spoof_protection(settings):
    settings.IP_TRUSTED_PROXIES = ["10.0.0.1/32", "10.0.0.2/32", "2001:db8:ffff::/64"]
    assert resolve_client_ip(IP, OTHER) == IP
    assert resolve_client_ip(IP, "malformed") == IP
    assert resolve_client_ip("10.0.0.1", f"{OTHER}, {IP}, 10.0.0.2") == IP
    assert resolve_client_ip("2001:db8:ffff::1", "2001:db8:1::1") == "2001:db8:1::1"
    assert (
        scope_ip(
            {
                "client": ("10.0.0.1", 12),
                "headers": [(b"x-forwarded-for", IP.encode()), (b"x-forwarded-for", b"10.0.0.2")],
            }
        )
        == IP
    )
    for forwarded in (None, "", "bad", IP + ", bad", "10.0.0.2", ",".join([IP] * 21), "x" * 2049):
        with pytest.raises(ClientIPError):
            resolve_client_ip("10.0.0.1", forwarded)
    with pytest.raises(ClientIPError):
        scope_ip({"client": None})
    for proxies in (["0.0.0.0/0"], ["::/0"], ["wrong"]):
        settings.IP_TRUSTED_PROXIES = proxies
        with pytest.raises(ImproperlyConfigured):
            resolve_client_ip(IP)


@pytest.mark.parametrize("kind", ["blacklist", "whitelist"])
@pytest.mark.parametrize("role", ["anonymous", "player", "moderator", "staff_only"])
def test_management_permissions(client, user, kind, role):
    if role != "anonymous":
        if role == "moderator":
            user.user_permissions.add(Permission.objects.get(codename="access_workspace"))
        if role == "staff_only":
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        client.force_authenticate(user)
    entry = (
        rule()
        if kind == "blacklist"
        else IPAccessEntry.objects.create(list_kind=kind, address=IP, reason="Private reason")
    )
    url = ROOT + kind + "/"
    for response in (
        client.get(url),
        client.post(url, black_payload(), format="json"),
        client.get(url + str(entry.pk) + "/"),
        client.post(url + str(entry.pk) + "/", {}, format="json"),
        client.delete(url + str(entry.pk) + "/"),
    ):
        assert response.status_code == 403
        assert (
            IP not in response.content.decode()
            and "Private reason" not in response.content.decode()
        )
    assert IPAccessEntry.objects.filter(pk=entry.pk).exists()


def test_administrator_crud_audit_search_and_pagination(admin_client, administrator):
    created = admin_client.post(ROOT + "blacklist/", black_payload("2001:0DB8::1"), format="json")
    assert created.status_code == 201, created.content
    entry_id = created.json()["id"]
    assert created.json()["address"] == "2001:db8::1"
    edited = admin_client.post(
        ROOT + "blacklist/" + entry_id + "/",
        black_payload("2001:db8::2", activities=["singleplayer", "community"]),
        format="json",
    )
    assert edited.status_code == 200 and edited.json()["activities"] == [
        "singleplayer",
        "community",
    ]
    for i in range(25):
        rule(address=f"192.0.2.{i + 1}")
    result = admin_client.get(ROOT + "blacklist/?page=99").json()
    assert result["page"] == result["total_pages"] == 2 and result["count"] == 26
    assert admin_client.get(ROOT + "blacklist/?q=2001:0db8:0:0::2").json()["count"] == 1
    assert admin_client.get(ROOT + "blacklist/?q=Internal%20review").json()["count"] == 1
    deleted = admin_client.delete(ROOT + "blacklist/" + entry_id + "/")
    assert deleted.status_code == 204 and not IPAccessEntry.objects.filter(pk=entry_id).exists()
    changes = Activity.objects.filter(target_type="ip_access", target_id=entry_id).order_by(
        "created_at"
    )
    assert list(changes.values_list("action", flat=True)) == [
        "ip_entry_created",
        "ip_entry_edited",
        "ip_entry_deleted",
    ]
    assert all(row.actor_id == administrator.pk and row.user_id is None for row in changes)
    assert changes[1].changes["before"]["address"] == "2001:db8::1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"address": "bad"},
        {"reason": "   "},
        {"activities": []},
        {"activities": ["singleplayer", "singleplayer"]},
        {"activities": ["unknown"]},
        {"duration": "temporary"},
        {"duration": "temporary", "expires_at": "invalid"},
        {"duration": "temporary", "expires_at": "2000-01-01T00:00:00Z"},
        {"duration": "indefinite", "expires_at": "2090-01-01T00:00:00Z"},
    ],
)
def test_blacklist_validation(admin_client, overrides):
    response = admin_client.post(ROOT + "blacklist/", black_payload(**overrides), format="json")
    assert response.status_code == 400
    assert not IPAccessEntry.objects.exists()


def test_whitelist_validation_duplicates_and_precedence(admin_client):
    rule(address=IP)
    payload = {"address": "::ffff:" + IP, "reason": "Verified network exception"}
    response = admin_client.post(ROOT + "whitelist/", payload, format="json")
    assert response.status_code == 201 and response.json()["address"] == IP
    assert restrictions_for_ip(IP) == set()
    duplicate = admin_client.post(
        ROOT + "whitelist/", {"address": IP, "reason": "Do not overwrite"}, format="json"
    )
    assert duplicate.status_code == 400 and "already" in str(duplicate.json())
    assert IPAccessEntry.objects.get(list_kind="whitelist").reason == payload["reason"]
    with pytest.raises(IntegrityError), transaction.atomic():
        IPAccessEntry.objects.create(list_kind="whitelist", address="::ffff:" + IP, reason="Race")
    assert (
        admin_client.post(
            ROOT + "whitelist/", {**payload, "activities": ["login"]}, format="json"
        ).status_code
        == 400
    )
    assert admin_client.delete(ROOT + "whitelist/" + response.json()["id"] + "/").status_code == 204
    assert restrictions_for_ip(IP) == {"singleplayer"}


@pytest.mark.parametrize("activity", list(ACTIVITIES))
def test_restrictions_are_independent(activity):
    rule(activity)
    assert restrictions_for_ip(IP) == {activity}
    for candidate in ACTIVITIES:
        if candidate == activity:
            with pytest.raises(IPAccessDenied):
                enforce_ip(IP, candidate)
        else:
            enforce_ip(IP, candidate)


def test_exact_expiration_indefinite_edit_and_delete(administrator):
    now = timezone.now()
    entry = rule(expires_at=now + timedelta(seconds=5))
    with patch("moderation.ip_rules.timezone.now", return_value=now + timedelta(seconds=5)):
        assert restrictions_for_ip(IP) == set()
    entry.expires_at = None
    entry.save()
    assert restrictions_for_ip(IP) == {"singleplayer"}
    data = BlacklistInput(
        data=black_payload(
            activities=["parties"],
            duration="temporary",
            expires_at=(now + timedelta(hours=1)).isoformat(),
        )
    )
    data.is_valid(raise_exception=True)
    save_entry(administrator, "blacklist", data.validated_data, pk=entry.pk)
    assert restrictions_for_ip(IP) == {"parties"}
    delete_entry(administrator, "blacklist", entry.pk)
    assert restrictions_for_ip(IP) == set()


HTTP_PATHS = {
    "registration": ("post", "/api/auth/register/"),
    "login": ("post", "/api/auth/login/"),
    "singleplayer": ("get", "/api/games/singleplayer/current/"),
    "parties": ("post", "/api/parties/"),
    "ranked": ("post", "/api/ranked/queue/"),
    "submissions": ("post", "/api/library/contributions/"),
    "community": ("post", "/api/moderation/reports/"),
}


@pytest.mark.parametrize("activity", list(ACTIVITIES))
def test_http_guest_only_restrictions_and_login_session_invalidation(client, user, activity):
    client.force_login(user)
    rule(activity)
    method, path = HTTP_PATHS[activity]
    data = (
        {"username": user.username, "password": "a-strong-unique-pass-734"}
        if activity == "login"
        else {}
    )
    response = getattr(client, method)(path, data, format="json", REMOTE_ADDR=IP)
    if activity != "login":
        assert response.json().get("code") != "ip_restricted"
        assert client.session["_auth_user_id"] == str(user.pk)
        client.logout()
        response = getattr(client, method)(path, data, format="json", REMOTE_ADDR=IP)
    else:
        assert "_auth_user_id" not in client.session
    assert response.status_code == 403 and response.json()["code"] == "ip_restricted"
    assert "Sensitive" not in response.content.decode() and IP not in response.content.decode()
    if activity != "singleplayer":
        other = client.get("/api/games/singleplayer/current/", REMOTE_ADDR=IP)
        assert other.json().get("code") != "ip_restricted"


@pytest.mark.parametrize(
    "path",
    [
        "/api/games/singleplayer/rounds/00000000-0000-0000-0000-000000000001/guesses/",
        "/api/games/singleplayer/rounds/00000000-0000-0000-0000-000000000001/image/",
        "/api/parties/ABCDEF/",
        "/api/parties/ABCDEF/join/",
        "/api/parties/ABCDEF/start/",
        "/api/parties/ABCDEF/guesses/",
        "/api/parties/ABCDEF/kick/",
        "/api/parties/ABCDEF/lobby/",
        "/api/parties/ABCDEF/next/",
        "/api/parties/ABCDEF/rounds/00000000-0000-0000-0000-000000000001/image/",
        "/api/ranked/queue/",
        "/api/ranked/matches/00000000-0000-0000-0000-000000000001/",
        "/api/ranked/matches/00000000-0000-0000-0000-000000000001/guesses/",
        "/api/ranked/matches/00000000-0000-0000-0000-000000000001/rounds/00000000-0000-0000-0000-000000000001/image/",
    ],
)
def test_game_route_coverage(client, path):
    activity, cleanup = activity_for_http(path, "POST")
    assert activity and not cleanup
    rule(activity)
    response = client.post(path, {}, format="json", REMOTE_ADDR=IP)
    if activity == "ranked":
        assert response.status_code == 403 and response.json().get("code") != "ip_restricted"
        return
    assert response.status_code == 403 and response.json()["code"] == "ip_restricted"


def test_session_check_signs_out_and_proxy_fail_closed(client, user, settings):
    client.force_login(user)
    rule("login", block_singleplayer=True)
    assert client.get("/api/auth/me/", REMOTE_ADDR=IP).status_code == 200
    assert "_auth_user_id" not in client.session
    assert client.get("/api/moderation/notices/", REMOTE_ADDR=IP).status_code == 403
    for path in ("/api/ranked/queue/cancel/", "/api/parties/ABCDEF/leave/"):
        response = client.post(path, {}, format="json", REMOTE_ADDR=IP)
        assert response.json().get("code") != "ip_restricted"
    response = client.get(
        "/api/games/singleplayer/current/", REMOTE_ADDR=IP, HTTP_X_FORWARDED_FOR=OTHER
    )
    assert response.json()["code"] == "ip_restricted"
    settings.IP_TRUSTED_PROXIES = ["10.0.0.1"]
    response = client.get(
        "/api/games/singleplayer/current/",
        REMOTE_ADDR="10.0.0.1",
        HTTP_X_FORWARDED_FOR=f"{OTHER}, {IP}",
    )
    assert response.json()["code"] == "ip_restricted"
    response = client.get("/api/games/singleplayer/current/", REMOTE_ADDR="10.0.0.1")
    assert response.json()["code"] == "client_ip_unavailable"
    response = client.get("/api/games/singleplayer/current/", REMOTE_ADDR="")
    assert response.json()["code"] == "client_ip_unavailable"


def test_whitelist_preserves_auth_csrf_sanctions_and_throttles(
    client, user, administrator, settings
):
    rule("login")
    IPAccessEntry.objects.create(list_kind="whitelist", address=IP, reason="Exception")
    assert client.get(ROOT + "blacklist/", REMOTE_ADDR=IP).status_code == 403
    csrf = APIClient(enforce_csrf_checks=True)
    assert csrf.post("/api/auth/login/", {}, REMOTE_ADDR=IP).status_code == 403
    client.force_login(user)
    Sanction.objects.create(
        user=user, issued_by=administrator, kind="closed", category="other", reason="Closed account"
    )
    assert client.get("/api/games/singleplayer/current/", REMOTE_ADDR=IP).status_code == 403
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "auth": "1/minute",
        },
    }
    from rest_framework.throttling import ScopedRateThrottle

    with patch.object(
        ScopedRateThrottle, "THROTTLE_RATES", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    ):
        anonymous = APIClient()
        assert anonymous.post("/api/auth/register/", {}, REMOTE_ADDR=IP).status_code == 400
        assert anonymous.post("/api/auth/register/", {}, REMOTE_ADDR=IP).status_code == 429


def test_login_only_restriction_does_not_block_registration_or_create_a_session(client):
    rule("login")
    response = client.post(
        "/api/auth/register/",
        {
            "username": "new_ip_player",
            "email": "new-ip-player@example.test",
            "password": "correct-unique-signup-pass-734!",
            "password_confirm": "correct-unique-signup-pass-734!",
        },
        format="json",
        REMOTE_ADDR=IP,
    )
    assert response.status_code == 201, response.content
    assert response.json()["login_required"] is True
    assert User.objects.filter(username="new_ip_player").exists()
    assert "_auth_user_id" not in client.session
    assert client.get("/api/auth/me/", REMOTE_ADDR=IP).json()["user"] is None


def test_own_ip_blacklist_and_whitelist_changes_need_no_exception(client, administrator):
    client.force_login(administrator)
    response = client.post(
        ROOT + "blacklist/", black_payload("127.0.0.1", activities=["login"]), format="json"
    )
    assert (
        response.status_code == 201
        and not IPAccessEntry.objects.filter(list_kind="whitelist").exists()
    )
    assert client.get(ROOT + "blacklist/").status_code == 200
    white = client.post(
        ROOT + "whitelist/", {"address": "127.0.0.1", "reason": "Operator access"}, format="json"
    ).json()
    url = ROOT + "whitelist/" + white["id"] + "/"
    assert client.post(url, {"address": OTHER, "reason": "Move"}, format="json").status_code == 200
    assert (
        client.post(url, {"address": "127.0.0.1", "reason": "Restore"}, format="json").status_code
        == 200
    )
    assert client.delete(url).status_code == 204
    assert client.get(ROOT + "blacklist/").status_code == 200
    assert restrictions_for_ip("127.0.0.1") == {"login"}


def test_infrastructure_and_recovery(admin_client, administrator, settings):
    settings.IP_TRUSTED_PROXIES = ["10.0.0.1"]
    assert (
        admin_client.post(ROOT + "blacklist/", black_payload("10.0.0.1"), format="json").status_code
        == 400
    )
    rule("login", IP)
    call_command(
        "ip_access_recover",
        IP,
        administrator=administrator.username,
        reason="Server-local recovery",
    )
    assert restrictions_for_ip(IP) == set()
    assert Activity.objects.filter(action="ip_entry_created", target_type="ip_access").exists()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_duplicate_creation(administrator):
    if connection.vendor == "sqlite" and connection.settings_dict["NAME"].startswith("file:memory"):
        pytest.skip("File-backed SQLite or PostgreSQL required for concurrent writers")
    barrier = Barrier(2)

    def create(_):
        close_old_connections()
        try:
            actor = User.objects.get(pk=administrator.pk)
            barrier.wait(timeout=10)
            try:
                save_entry(
                    actor,
                    "whitelist",
                    {"address": IP, "reason": "Concurrent create"},
                )
                return "created"
            except ValidationError as exc:
                assert "already" in str(exc.detail)
                return "duplicate"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(create, range(2)))
    assert sorted(results) == ["created", "duplicate"]
    assert IPAccessEntry.objects.filter(list_kind="whitelist", address=IP).count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, activity, target",
    [
        ("/ws/parties/ABCDEF/", "parties", "games.party_consumer.socket_state"),
        (
            "/ws/ranked/queue/00000000-0000-0000-0000-000000000001/",
            "ranked",
            "games.ranked_consumer.RankedConsumer.read",
        ),
        (
            "/ws/matches/00000000-0000-0000-0000-000000000001/",
            "ranked",
            "games.ranked_consumer.RankedConsumer.read",
        ),
    ],
)
async def test_websocket_connect_and_existing_socket_rechecks(path, activity, target, user):
    from config.asgi import application

    headers = [(b"origin", b"http://localhost:5173")]

    def authenticated_headers():
        client = APIClient()
        client.force_login(user)
        return [
            (b"origin", b"http://localhost:5173"),
            (b"cookie", f"sessionid={client.cookies['sessionid'].value}".encode()),
        ]

    if activity == "ranked":
        activity = "login"
        headers = await database_sync_to_async(authenticated_headers)()
    with patch(target, return_value={"status": "test"}) as read:
        socket = WebsocketCommunicator(application, path, headers=headers)
        socket.scope["client"] = (IP, 12345)
        connected, _ = await socket.connect()
        assert connected
        assert (await socket.receive_json_from())["type"] == "state"
        await database_sync_to_async(rule)(activity)
        await socket.send_json_to({"type": "heartbeat"})
        event = await socket.receive_json_from()
        assert event["type"] == "access_denied" and event["code"] == "ip_restricted"
        assert "Sensitive" not in str(event) and IP not in str(event)
        assert (await socket.receive_output())["code"] == 4403
        await socket.disconnect()
        read.reset_mock()
        if activity == "login":
            headers = await database_sync_to_async(authenticated_headers)()
        blocked = WebsocketCommunicator(application, path, headers=headers)
        blocked.scope["client"] = (IP, 12345)
        connected, code = await blocked.connect()
        assert not connected and code == 4403 and not read.called
        await blocked.disconnect()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_missing_socket_peer_and_whitelist_cannot_bypass_authentication():
    from config.asgi import application

    with patch("games.party_consumer.socket_state", return_value={}) as read:
        missing = WebsocketCommunicator(
            application, "/ws/parties/ABCDEF/", headers=[(b"origin", b"http://localhost:5173")]
        )
        missing.scope["client"] = None
        connected, code = await missing.connect()
        assert not connected and code == 4403 and not read.called
        await missing.disconnect()
    await database_sync_to_async(IPAccessEntry.objects.create)(
        list_kind="whitelist", address=IP, reason="Exception"
    )
    unauthenticated = WebsocketCommunicator(
        application,
        "/ws/ranked/queue/00000000-0000-0000-0000-000000000001/",
        headers=[(b"origin", b"http://localhost:5173")],
    )
    unauthenticated.scope["client"] = (IP, 12)
    connected, code = await unauthenticated.connect()
    assert not connected and code == 4403
    await unauthenticated.disconnect()


def test_administrator_can_manage_lists_from_a_blocked_ip(client, administrator):
    client.force_login(administrator)
    rule("login")
    response = client.get(ROOT + "blacklist/", REMOTE_ADDR=IP)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me/",
        "/api/auth/csrf/",
        "/api/auth/settings/",
        "/api/moderation/notices/",
        "/api/ranked/leaderboard/",
        "/api/parties/ABCDEF/leave/",
        "/api/games/singleplayer/current/",
    ],
)
def test_login_rule_deletes_accessing_session_even_on_support_or_public_routes(client, user, path):
    client.force_login(user)
    old_key = client.cookies["sessionid"].value
    unaffected = APIClient()
    unaffected.force_login(user)
    safe_key = unaffected.cookies["sessionid"].value
    rule("login")
    method = client.post if path.endswith("/leave/") else client.get
    response = method(path, REMOTE_ADDR=IP)
    assert response.status_code == (200 if path in {"/api/auth/me/", "/api/auth/csrf/"} else 403)
    assert not Session.objects.filter(session_key=old_key).exists()
    assert Session.objects.filter(session_key=safe_key).exists()
    assert unaffected.get("/api/auth/me/", REMOTE_ADDR=OTHER).json()["user"]["id"] == str(user.pk)
    # Moving networks or replaying the old cookie cannot revive the deleted session.
    client.cookies["sessionid"] = old_key
    assert client.get("/api/auth/me/", REMOTE_ADDR=OTHER).json()["user"] is None


def test_staff_can_replace_an_invalidated_player_session_at_login(client, user, administrator):
    administrator.set_password("verified-staff-password-734!")
    administrator.save(update_fields=["password"])
    client.force_login(user)
    old_key = client.cookies["sessionid"].value
    rule("login")
    response = client.post(
        "/api/auth/login/",
        {"username": administrator.username, "password": "verified-staff-password-734!"},
        format="json",
        REMOTE_ADDR=IP,
    )
    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(administrator.pk)
    assert not Session.objects.filter(session_key=old_key).exists()


def test_failed_player_signin_does_not_invalidate_existing_staff_session(
    client, user, administrator
):
    client.force_login(administrator)
    key = client.cookies["sessionid"].value
    rule("login")
    response = client.post(
        "/api/auth/login/",
        {"username": user.username, "password": "a-strong-unique-pass-734"},
        format="json",
        REMOTE_ADDR=IP,
    )
    assert response.status_code == 403
    assert Session.objects.filter(session_key=key).exists()
    assert client.session["_auth_user_id"] == str(administrator.pk)


def test_legacy_ranked_only_entry_is_preserved_but_not_enforced(admin_client, client, user):
    entry = rule("ranked")
    assert restrictions_for_ip(IP) == set()
    assert admin_client.get(ROOT + "blacklist/").json()["results"][0]["activities"] == []
    assert (
        admin_client.post(
            ROOT + "blacklist/", black_payload(OTHER, activities=["ranked"]), format="json"
        ).status_code
        == 400
    )
    assert IPAccessEntry.objects.filter(pk=entry.pk, block_ranked=True).exists()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_account_socket_login_restriction_invalidates_session_and_publishes_signout(user):
    from config.asgi import application

    def setup():
        client = APIClient()
        client.force_login(user)
        return client.cookies["sessionid"].value

    key = await database_sync_to_async(setup)()
    socket = WebsocketCommunicator(
        application,
        "/ws/account/",
        headers=[(b"origin", b"http://localhost:5173"), (b"cookie", f"sessionid={key}".encode())],
    )
    socket.scope["client"] = (IP, 12345)
    assert (await socket.connect())[0]
    assert (await socket.receive_json_from())["state"]["user"]["id"] == str(user.pk)
    await database_sync_to_async(rule)("login")
    assert (await socket.receive_json_from(timeout=2))["state"] == {
        "user": None,
        "restrictions": None,
    }
    assert (await socket.receive_json_from())["type"] == "access_denied"
    assert (await socket.receive_output())["code"] == 4403
    assert not await database_sync_to_async(Session.objects.filter(session_key=key).exists)()
    await socket.disconnect()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["moderator", "administrator"])
async def test_staff_account_socket_is_exempt(user, role):
    from config.asgi import application

    def setup():
        grant_staff(user, role)
        client = APIClient()
        client.force_login(user)
        rule("login")
        return client.cookies["sessionid"].value

    key = await database_sync_to_async(setup)()
    socket = WebsocketCommunicator(
        application,
        "/ws/account/",
        headers=[(b"origin", b"http://localhost:5173"), (b"cookie", f"sessionid={key}".encode())],
    )
    socket.scope["client"] = (IP, 12345)
    assert (await socket.connect())[0]
    assert (await socket.receive_json_from())["state"]["user"]["id"] == str(user.pk)
    assert await database_sync_to_async(Session.objects.filter(session_key=key).exists)()
    await socket.disconnect()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_signed_in_party_socket_ignores_guest_rule_until_session_ends(user):
    from config.asgi import application

    def setup():
        client = APIClient()
        client.force_login(user)
        rule("parties")
        return client.cookies["sessionid"].value

    key = await database_sync_to_async(setup)()
    with patch("games.party_consumer.socket_state", return_value={"status": "test"}):
        socket = WebsocketCommunicator(
            application,
            "/ws/parties/ABCDEF/",
            headers=[
                (b"origin", b"http://localhost:5173"),
                (b"cookie", f"sessionid={key}".encode()),
            ],
        )
        socket.scope["client"] = (IP, 12345)
        assert (await socket.connect())[0]
        assert (await socket.receive_json_from())["type"] == "state"
        await database_sync_to_async(Session.objects.filter(session_key=key).delete)()
        await socket.send_json_to({"type": "heartbeat"})
        assert (await socket.receive_json_from())["type"] == "access_denied"
        assert (await socket.receive_output())["code"] == 4403
        await socket.disconnect()


def test_whitelist_edit_and_normalized_duplicate_do_not_overwrite(admin_client):
    first = admin_client.post(
        ROOT + "whitelist/", {"address": "2001:db8::1", "reason": "Original"}, format="json"
    ).json()
    second = admin_client.post(
        ROOT + "whitelist/", {"address": "2001:db8::2", "reason": "Separate"}, format="json"
    ).json()
    url = ROOT + "whitelist/" + first["id"] + "/"
    response = admin_client.post(
        url, {"address": "2001:0DB8:0:0:0:0:0:2", "reason": "Collision"}, format="json"
    )
    assert response.status_code == 400 and "already" in str(response.json())
    assert IPAccessEntry.objects.get(pk=second["id"]).reason == "Separate"
    response = admin_client.post(
        url, {"address": "2001:db8::3", "reason": "Updated exception"}, format="json"
    )
    assert response.status_code == 200 and response.json()["address"] == "2001:db8::3"
    assert response.json()["reason"] == "Updated exception"


@pytest.mark.parametrize(
    "path",
    [
        "/api/library/submissions/",
        "/api/moderation/workspace/administration/imports/00000000-0000-0000-0000-000000000001/",
        "/admin/library/imagesubmission/add/",
    ],
)
def test_submission_alternate_routes_cannot_bypass_rule(client, user, path):
    rule("submissions")
    response = client.post(path, {}, format="json", REMOTE_ADDR=IP)
    assert response.status_code == 403 and response.json()["code"] == "ip_restricted"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("activity", ["parties", "login"])
async def test_live_socket_whitelist_removal_and_idle_recheck(activity, user):
    from config.asgi import application

    def session_cookie():
        client = APIClient()
        if activity == "login":
            client.force_login(user)
        else:
            session = client.session
            session["guest_test"] = True
            session.save()
        return client.cookies["sessionid"].value

    cookie = await database_sync_to_async(session_cookie)()
    await database_sync_to_async(rule)(activity)
    white = await database_sync_to_async(IPAccessEntry.objects.create)(
        list_kind="whitelist", address=IP, reason="Temporary operator exception"
    )
    target = (
        "games.party_consumer.socket_state"
        if activity == "parties"
        else "games.ranked_consumer.RankedConsumer.read"
    )
    path = (
        "/ws/parties/ABCDEF/"
        if activity == "parties"
        else "/ws/matches/00000000-0000-0000-0000-000000000001/"
    )
    with patch(target, return_value={"status": "test"}):
        socket = WebsocketCommunicator(
            application,
            path,
            headers=[
                (b"origin", b"http://localhost:5173"),
                (b"cookie", f"sessionid={cookie}".encode()),
            ],
        )
        socket.scope["client"] = (IP, 12345)
        assert (await socket.connect())[0]
        assert (await socket.receive_json_from())["type"] == "state"
        await database_sync_to_async(white.delete)()
        # No client action is needed: the normal tick rechecks the current database rules.
        for _ in range(10):
            event = await socket.receive_json_from(timeout=2)
            if event["type"] == "access_denied":
                break
        assert event["type"] == "access_denied" and event["code"] == "ip_restricted"
        assert (await socket.receive_output())["code"] == 4403
        await socket.disconnect()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["moderator", "administrator"])
@pytest.mark.parametrize(
    "path, activity, target",
    [
        ("/ws/parties/ABCDEF/", "parties", "games.party_consumer.socket_state"),
        (
            "/ws/ranked/queue/00000000-0000-0000-0000-000000000001/",
            "ranked",
            "games.ranked_consumer.RankedConsumer.read",
        ),
        (
            "/ws/matches/00000000-0000-0000-0000-000000000001/",
            "ranked",
            "games.ranked_consumer.RankedConsumer.read",
        ),
    ],
)
async def test_staff_socket_exemption_and_live_demotion(user, role, path, activity, target):
    from config.asgi import application

    def setup():
        grant_staff(user, role)
        client = APIClient()
        client.force_login(user)
        rule(activity, block_login=True)
        return client.cookies["sessionid"].value

    cookie = await database_sync_to_async(setup)()
    with patch(target, return_value={"status": "test"}):
        socket = WebsocketCommunicator(
            application,
            path,
            headers=[
                (b"origin", b"http://localhost:5173"),
                (b"cookie", f"sessionid={cookie}".encode()),
            ],
        )
        socket.scope["client"] = (IP, 12345)
        assert (await socket.connect())[0]
        assert (await socket.receive_json_from())["type"] == "state"
        await socket.send_json_to({"type": "heartbeat"})
        # A normal idle push is allowed too, despite both activity and login rules.
        assert (await socket.receive_json_from(timeout=2))["type"] == "state"

        def demote():
            User.objects.filter(pk=user.pk).update(is_staff=False, is_superuser=False)
            user.user_permissions.clear()

        await database_sync_to_async(demote)()
        await socket.send_json_to({"type": "heartbeat"})
        for _ in range(10):
            event = await socket.receive_json_from(timeout=2)
            if event["type"] == "access_denied":
                break
        assert event["type"] == "access_denied" and event["code"] == "ip_restricted"
        assert (await socket.receive_output())["code"] == 4403
        await socket.disconnect()
