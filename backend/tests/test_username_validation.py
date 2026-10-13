from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.admin import CustomUserChangeForm, CustomUserCreationForm
from accounts.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "complex-pixel-password-952"
WHITESPACE_ERROR = "Usernames cannot contain spaces or other whitespace."
ENDING_ERROR = "Usernames cannot end with a hyphen (-) or underscore (_)."


@pytest.fixture(params=["registration", "change"])
def assign(request, client, user):
    if request.param == "change":
        User.objects.filter(pk=user.pk).update(
            last_username_change=timezone.now() - timedelta(days=91)
        )
        client.force_authenticate(user)

    def run(username):
        if request.param == "registration":
            return client.post(
                "/api/auth/register/",
                {
                    "username": username,
                    "email": "new@example.test",
                    "password": PASSWORD,
                    "password_confirm": PASSWORD,
                },
                format="json",
            )
        return client.post(
            "/api/auth/change-username/",
            {
                "new_username": username,
                "current_password": "a-strong-unique-pass-734",
            },
            format="json",
        )

    return run, "username" if request.param == "registration" else "new_username"


@pytest.mark.parametrize(
    "username",
    [
        "PlayerOne",
        "player_one",
        "player-one",
        "Player123",
        "_player",
        "-player",
        "player.name+tag@123",
        "x" * 150,
    ],
)
def test_valid_usernames_in_both_flows(assign, username):
    run, field = assign
    response = run(username)
    assert response.status_code in [200, 201], response.data
    assert User.objects.filter(username=username).exists()


@pytest.mark.parametrize(
    "username, message",
    [
        ("player one", WHITESPACE_ERROR),
        (" player", WHITESPACE_ERROR),
        ("player ", WHITESPACE_ERROR),
        ("player\tone", WHITESPACE_ERROR),
        ("\tplayer", WHITESPACE_ERROR),
        ("player\t", WHITESPACE_ERROR),
        ("player\none", WHITESPACE_ERROR),
        ("\nplayer", WHITESPACE_ERROR),
        ("player\n", WHITESPACE_ERROR),
        ("player\r\none", WHITESPACE_ERROR),
        ("player\vone", WHITESPACE_ERROR),
        ("player\fone", WHITESPACE_ERROR),
        ("player\u00a0one", WHITESPACE_ERROR),
        ("player\u2003one", WHITESPACE_ERROR),
        ("player\u2028one", WHITESPACE_ERROR),
        ("player_one_", ENDING_ERROR),
        ("player-one-", ENDING_ERROR),
        ("player＿", ENDING_ERROR),
        ("player－", ENDING_ERROR),
    ],
)
def test_rejected_usernames_have_identical_field_errors_and_preserve_data(
    assign, username, message
):
    before = list(User.objects.order_by("pk").values())
    run, field = assign
    response = run(username)
    assert response.status_code == 400
    assert response.json()[field] == [message]
    assert list(User.objects.order_by("pk").values()) == before


@pytest.mark.parametrize("username", ["x" * 151, "player/name", "player!name", ""])
def test_existing_length_and_character_restrictions_remain(assign, username):
    run, field = assign
    response = run(username)
    assert response.status_code == 400 and field in response.json()


def test_case_insensitive_duplicates_in_both_flows(assign):
    User.objects.create_user(username="PlayerOne", email="taken@example.test")
    run, field = assign
    response = run("playerone")
    assert response.status_code == 400
    assert response.json()[field] == ["This username is unavailable."]


def test_case_insensitive_uniqueness_is_enforced_by_database():
    User.objects.create_user(username="PlayerOne", email="first@example.test")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(username="playerone", email="second@example.test")
    assert User.objects.count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_case_insensitive_registrations():
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for SQLite writer concurrency")
    barrier = Barrier(2)

    def run(index):
        close_old_connections()
        try:
            client = APIClient()
            barrier.wait(timeout=10)
            return client.post(
                "/api/auth/register/",
                {
                    "username": ["PlayerOne", "playerone"][index],
                    "email": f"race{index}@example.test",
                    "password": PASSWORD,
                    "password_confirm": PASSWORD,
                },
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(run, range(2)))
    assert sorted(results) == [201, 400]
    assert User.objects.filter(username__iexact="playerone").count() == 1


@pytest.mark.parametrize("username", ["legacy_", "legacy-"])
def test_legacy_usernames_remain_usable(client, username):
    legacy = User.objects.create_user(
        username=username, email="legacy@example.test", password=PASSWORD
    )
    assigned = legacy.last_username_change
    assert (
        client.post(
            "/api/auth/login/", {"username": username, "password": PASSWORD}, format="json"
        ).status_code
        == 200
    )
    assert (
        client.patch("/api/auth/me/", {"display_name": "Legacy player"}, format="json").status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/change-email/",
            {"new_email": "updated@example.test", "current_password": PASSWORD},
            format="json",
        ).status_code
        == 200
    )
    legacy.refresh_from_db()
    assert legacy.username == username and legacy.last_username_change == assigned


@pytest.mark.parametrize("username", ["player_", "player-", " player", "player\n"])
def test_admin_creation_rejects_new_invalid_usernames(username):
    form = CustomUserCreationForm(
        {
            "username": username,
            "email": "admin@example.test",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
    )
    assert not form.is_valid() and "username" in form.errors
    assert User.objects.count() == 0


class MinimalUserChangeForm(CustomUserChangeForm):
    class Meta(CustomUserChangeForm.Meta):
        fields = ("username", "email", "display_name")


def test_admin_preserves_legacy_username_for_unrelated_edits():
    legacy = User.objects.create_user(username="legacy_", email="legacy@example.test")
    form = MinimalUserChangeForm(
        {"username": "legacy_", "email": legacy.email, "display_name": "Updated"}, instance=legacy
    )
    assert form.is_valid(), form.errors
    form.save()
    legacy.refresh_from_db()
    assert legacy.username == "legacy_" and legacy.display_name == "Updated"
    changed = MinimalUserChangeForm(
        {"username": "changed_", "email": legacy.email}, instance=legacy
    )
    assert not changed.is_valid() and "username" in changed.errors
