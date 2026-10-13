import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.services import change_account
from games.models import Match, Participant
from moderation.models import Sanction

pytestmark = pytest.mark.django_db
PASSWORD = "a-strong-unique-pass-734"
NEW_PASSWORD = "a-new-unique-forest-password-951!"
BASE = "/api/auth/"


def change(client, operation, **data):
    return client.post(
        BASE + f"change-{operation}/", {"current_password": PASSWORD, **data}, format="json"
    )


@pytest.fixture
def signed(client, user):
    client.force_authenticate(user)
    return client


@pytest.fixture
def clock(monkeypatch):
    value = {"now": timezone.now()}
    monkeypatch.setattr(timezone, "now", lambda: value["now"])
    return value


@pytest.fixture
def eligible(user, clock):
    User.objects.filter(pk=user.pk).update(last_username_change=clock["now"] - timedelta(days=90))
    user.refresh_from_db()
    return user


def test_new_account_assignment_and_settings(signed, user):
    assert user.last_username_change == user.date_joined
    body = signed.get(BASE + "settings/").json()
    assert set(body) == {
        "username",
        "email",
        "username_change_available",
        "username_change_available_at",
    }
    assert body["username"] == user.username and body["email"] == user.email
    assert body["username_change_available"] is False
    response = change(signed, "username", new_username="renamed")
    assert response.status_code == 400
    assert "username_change_available_at" in response.json()
    user.refresh_from_db()
    assert user.username == "pixelplayer"


@pytest.mark.parametrize("days,accepted", [(89, False), (90, True)])
def test_username_exact_cooldown_boundary(signed, user, clock, days, accepted):
    assigned = clock["now"]
    User.objects.filter(pk=user.pk).update(last_username_change=assigned)
    clock["now"] += timedelta(days=days)
    response = change(signed, "username", new_username="fresh_player")
    assert response.status_code == (200 if accepted else 400)
    user.refresh_from_db()
    assert user.last_username_change == (clock["now"] if accepted else assigned)
    if accepted:
        assert change(signed, "username", new_username="second_name").status_code == 400
        clock["now"] += timedelta(days=90)
        assert change(signed, "username", new_username="second_name").status_code == 200


@pytest.mark.parametrize(
    "value", ["pixelplayer", "PIXELPLAYER", "ｐixelplayer", "bad name", "invalid/name", ""]
)
def test_username_invalid_or_same(signed, eligible, value):
    assert change(signed, "username", new_username=value).status_code == 400
    eligible.refresh_from_db()
    assert eligible.username == "pixelplayer"


@pytest.mark.parametrize(
    "operation,data",
    [
        ("username", {"new_username": "changed"}),
        ("email", {"new_email": "changed@example.test"}),
        ("password", {"new_password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD}),
    ],
)
def test_each_operation_requires_current_password(signed, eligible, operation, data):
    before = User.objects.values().get(pk=eligible.pk)
    response = change(signed, operation, current_password="wrong-password", **data)
    assert response.status_code == 400 and "Current password is incorrect." in str(response.json())
    assert User.objects.values().get(pk=eligible.pk) == before
    data["current_password"] = ""
    assert signed.post(BASE + f"change-{operation}/", data, format="json").status_code == 400


def test_username_normalization_unique_and_identity_preserved(signed, eligible, staff, clock):
    User.objects.create_user(username="taken", email="taken@example.test")
    assert change(signed, "username", new_username="TAKEN").status_code == 400
    match = Match.objects.create(
        mode="ranked", status="complete", ranked_outcome="no_contest", completed_at=clock["now"]
    )
    participant = Participant.objects.create(
        match=match, user=eligible, rating_before=1400, rating_after=1400, total_score=234
    )
    Participant.objects.create(match=match, user=staff, rating_before=1000, rating_after=1000)
    sanction = Sanction.objects.create(
        user=eligible, issued_by=staff, kind="probation", category="fair_play", reason="Test notice"
    )
    User.objects.filter(pk=eligible.pk).update(
        rating=1400, ranked_matches=5, ranked_wins=3, ranked_losses=2
    )
    original_id = eligible.pk
    # Django's canonical NFKC normalization is shared with registration.
    assert change(signed, "username", new_username="Ｆresh_Player").status_code == 200
    eligible.refresh_from_db()
    assert eligible.username == "Fresh_Player" and eligible.pk == original_id
    assert (
        eligible.rating,
        eligible.ranked_matches,
        eligible.ranked_wins,
        eligible.ranked_losses,
    ) == (1400, 5, 3, 2)
    assert Participant.objects.get(pk=participant.pk).user_id == original_id
    assert Sanction.objects.get(pk=sanction.pk).user_id == original_id
    assert signed.get(BASE + "profiles/pixelplayer/").status_code == 404
    assert signed.get(BASE + "profiles/Fresh_Player/").json()["id"] == str(original_id)
    assert signed.get("/api/ranked/history/Fresh_Player/").json()["results"][0]["id"] == str(
        match.pk
    )
    assert signed.get("/api/ranked/leaderboard/").json()["results"][0]["username"] == "Fresh_Player"


@pytest.mark.parametrize("email", ["invalid", "player@example.com", "PLAYER@EXAMPLE.COM"])
def test_email_invalid_or_unchanged(signed, user, email):
    before = User.objects.values().get(pk=user.pk)
    assert change(signed, "email", new_email=email).status_code == 400
    assert User.objects.values().get(pk=user.pk) == before


def test_email_duplicate_and_immediate_normalization(signed, user):
    User.objects.create_user(username="other", email="other@example.test")
    assert change(signed, "email", new_email="OTHER@example.test").status_code == 400
    before = User.objects.values().get(pk=user.pk)
    response = change(signed, "email", new_email="  NEW@EXAMPLE.TEST  ")
    assert (
        response.status_code == 200 and response.json()["settings"]["email"] == "new@example.test"
    )
    after = User.objects.values().get(pk=user.pk)
    assert {k: v for k, v in after.items() if k != "email"} == {
        k: v for k, v in before.items() if k != "email"
    }


@pytest.mark.parametrize(
    "data",
    [
        {
            "current_password": "wrong",
            "new_password": NEW_PASSWORD,
            "password_confirm": NEW_PASSWORD,
        },
        {"new_password": NEW_PASSWORD, "password_confirm": "different-password"},
        {"new_password": "password", "password_confirm": "password"},
        {"new_password": PASSWORD, "password_confirm": PASSWORD},
    ],
)
def test_password_rejected_without_partial_update(signed, user, data):
    before = User.objects.values().get(pk=user.pk)
    assert change(signed, "password", **data).status_code == 400
    assert User.objects.values().get(pk=user.pk) == before


def test_password_session_preserved_and_other_sessions_invalidated(user):
    current, other = APIClient(), APIClient()
    current.force_login(user)
    other.force_login(user)
    old_session = current.cookies["sessionid"].value
    before = User.objects.values().get(pk=user.pk)
    response = change(current, "password", new_password=NEW_PASSWORD, password_confirm=NEW_PASSWORD)
    assert response.status_code == 200
    assert current.cookies["sessionid"].value != old_session
    assert current.get(BASE + "me/").json()["user"]["id"] == str(user.pk)
    assert other.get(BASE + "me/").json()["user"] is None
    user.refresh_from_db()
    assert not user.check_password(PASSWORD) and user.check_password(NEW_PASSWORD)
    after = User.objects.values().get(pk=user.pk)
    assert {k: v for k, v in after.items() if k != "password"} == {
        k: v for k, v in before.items() if k != "password"
    }
    login = APIClient()
    assert (
        login.post(
            BASE + "login/", {"username": user.username, "password": PASSWORD}, format="json"
        ).status_code
        == 400
    )
    assert (
        login.post(
            BASE + "login/", {"username": user.username, "password": NEW_PASSWORD}, format="json"
        ).status_code
        == 200
    )
    # Other users' sessions are untouched; no bulk session deletion.
    friend = User.objects.create_user(
        username="friend", email="friend@example.test", password=PASSWORD
    )
    friend_client = APIClient()
    friend_client.force_login(friend)
    assert (
        change(
            current,
            "password",
            current_password=NEW_PASSWORD,
            new_password=PASSWORD,
            password_confirm=PASSWORD,
        ).status_code
        == 200
    )
    assert friend_client.get(BASE + "me/").json()["user"]["id"] == str(friend.pk)


def test_username_email_keep_session_and_login_uses_new_username(user, eligible):
    client = APIClient()
    client.force_login(user)
    key = client.cookies["sessionid"].value
    assert change(client, "username", new_username="renamed").status_code == 200
    assert change(client, "email", new_email="new@example.test").status_code == 200
    assert client.cookies["sessionid"].value == key
    assert client.get(BASE + "me/").json()["user"]["username"] == "renamed"
    login = APIClient()
    assert (
        login.post(
            BASE + "login/", {"username": "pixelplayer", "password": PASSWORD}, format="json"
        ).status_code
        == 400
    )
    assert (
        login.post(
            BASE + "login/", {"username": "renamed", "password": PASSWORD}, format="json"
        ).status_code
        == 200
    )
    assert login.get(BASE + "me/").json()["user"]["email"] == "new@example.test"


@pytest.mark.parametrize(
    "operation,data",
    [
        ("username", {"new_username": "renamed"}),
        ("email", {"new_email": "new@example.test"}),
        ("password", {"new_password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD}),
    ],
)
def test_auth_csrf_and_extra_fields(user, eligible, operation, data):
    guest = APIClient()
    assert change(guest, operation, **data).status_code == 403
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    assert change(client, operation, **data).status_code == 403
    token = client.get(BASE + "csrf/").json()["csrfToken"]
    response = client.post(
        BASE + f"change-{operation}/",
        {"current_password": PASSWORD, **data, "user_id": str(uuid.uuid4()), "is_staff": True},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 400
    response = client.post(
        BASE + f"change-{operation}/",
        {"current_password": PASSWORD, **data},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200


def test_reauthentication_throttle_is_scoped_to_authenticated_user(signed, user):
    assert [
        change(signed, "email", current_password="wrong", new_email="new@example.test").status_code
        for _ in range(11)
    ][-1] == 429
    other = User.objects.create_user(
        username="another", email="another@example.test", password=PASSWORD
    )
    second = APIClient()
    second.force_authenticate(other)
    assert change(second, "email", new_email="available@example.test").status_code == 200


@pytest.mark.parametrize("payload", [[], [{"new_email": "x"}], None])
def test_invalid_payloads_do_not_raise(signed, payload):
    assert signed.post(BASE + "change-email/", payload, format="json").status_code == 400


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_populated_migration_backfills_original_creation_date():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [("accounts", "0002_user_ranked_losses_user_ranked_matches_and_more")]
    try:
        executor.migrate(previous)
        OldUser = executor.loader.project_state(previous).apps.get_model("accounts", "User")
        joined = timezone.now() - timedelta(days=182)
        old = OldUser.objects.create(
            username="legacycooldown",
            email="legacy@example.test",
            date_joined=joined,
            rating=1555,
            ranked_matches=11,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        NewUser = executor.loader.project_state(latest).apps.get_model("accounts", "User")
        new = NewUser.objects.get(pk=old.pk)
        assert new.last_username_change == joined and new.date_joined == joined
        assert new.rating == 1555 and new.ranked_matches == 11
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("operation", ["username", "email", "password"])
def test_concurrent_account_changes_are_serialized(user, clock, operation):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for SQLite writer concurrency")
    User.objects.filter(pk=user.pk).update(last_username_change=clock["now"] - timedelta(days=90))
    barrier = Barrier(2)

    def run(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            data = {"current_password": PASSWORD}
            if operation == "username":
                data["new_username"] = f"renamed{index}"
            elif operation == "email":
                data["new_email"] = f"changed{index}@example.test"
            else:
                data.update(
                    new_password=f"new-forest-password-{index}-951!",
                    password_confirm=f"new-forest-password-{index}-951!",
                )
            try:
                change_account(user.pk, operation, data)
                return True
            except Exception as exc:
                from rest_framework.exceptions import ValidationError

                if isinstance(exc, ValidationError):
                    return False
                raise
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(run, range(2)))
    assert sum(results) == (2 if operation == "email" else 1)
    user.refresh_from_db()
    if operation == "username":
        assert user.last_username_change == clock["now"]


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("operation", ["username", "email"])
def test_concurrent_unique_claims_preserve_both_accounts(user, clock, operation):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for SQLite writer concurrency")
    other = User.objects.create_user(
        username="second", email="second@example.test", password=PASSWORD
    )
    User.objects.filter(pk__in=[user.pk, other.pk]).update(
        last_username_change=clock["now"] - timedelta(days=90)
    )
    barrier = Barrier(2)

    def run(account):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(account)
            barrier.wait(timeout=10)
            data = (
                {"new_username": "Shared_Claim" if account.pk == user.pk else "shared_claim"}
                if operation == "username"
                else {"new_email": "shared@example.test"}
            )
            return change(client, operation, **data).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(run, [user, other]))
    assert sorted(results) == [200, 400]
    user.refresh_from_db()
    other.refresh_from_db()
    field = "username" if operation == "username" else "email"
    assert getattr(user, field) != getattr(other, field)
    assert user.check_password(PASSWORD) and other.check_password(PASSWORD)
    assert user.rating == other.rating == 1000
