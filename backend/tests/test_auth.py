import pytest
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db


def registration():
    return {
        "username": "newplayer",
        "email": "new@example.com",
        "password": "complex-pixel-password-952",
        "password_confirm": "complex-pixel-password-952",
    }


def secure_client():
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    return client, token


def test_anonymous_auth_requires_csrf():
    client = APIClient(enforce_csrf_checks=True)
    assert client.post("/api/auth/register/", registration(), format="json").status_code == 403
    assert (
        client.post(
            "/api/auth/login/", {"username": "x", "password": "x"}, format="json"
        ).status_code
        == 403
    )


def test_registration_session_and_csrf_rotation():
    client, token = secure_client()
    response = client.post(
        "/api/auth/register/", registration(), format="json", HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 201
    assert "password" not in response.json()["user"]
    assert "password_confirm" not in response.json()["user"]
    created = User.objects.get(username="newplayer")
    assert created.last_username_change == created.date_joined
    assert client.get("/api/auth/me/").json()["user"]["username"] == "newplayer"
    # The pre-login token becomes invalid after Django rotates CSRF secrets.
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 403
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert client.get("/api/auth/me/").json()["user"] is None


def test_login_and_authenticated_edit_csrf(user):
    client, token = secure_client()
    assert (
        client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "a-strong-unique-pass-734"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        ).status_code
        == 200
    )
    assert (
        client.patch("/api/auth/me/", {"display_name": "New name"}, format="json").status_code
        == 403
    )
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert (
        client.patch(
            "/api/auth/me/",
            {"display_name": "New name", "is_staff": True, "rating": 9999},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        ).status_code
        == 200
    )
    user.refresh_from_db()
    assert user.display_name == "New name"
    assert not user.is_staff
    assert user.rating == 1000


def test_case_insensitive_registration_uniqueness(client, user):
    for data in [
        {**registration(), "username": user.username.upper()},
        {**registration(), "email": user.email.upper()},
    ]:
        assert client.post("/api/auth/register/", data, format="json").status_code == 400


def test_weak_password_rejected(client):
    assert (
        client.post(
            "/api/auth/register/",
            {**registration(), "password": "password", "password_confirm": "password"},
            format="json",
        ).status_code
        == 400
    )
    assert User.objects.count() == 0


def test_public_profile_no_email(client, user):
    body = client.get(f"/api/auth/profiles/{user.username}/").json()
    assert "email" not in body and "password" not in body
    assert body["rating"] == 1000
    assert body["ranked_tier"] is None


def test_auth_throttle(client):
    responses = [
        client.post("/api/auth/login/", {"username": "missing", "password": "bad"}, format="json")
        for _ in range(11)
    ]
    assert responses[-1].status_code == 429


@pytest.mark.parametrize("confirmation", [None, "mismatched-password"])
def test_registration_requires_password_confirmation(client, confirmation):
    data = registration()
    if confirmation is None:
        data.pop("password_confirm")
    else:
        data["password_confirm"] = confirmation
    response = client.post("/api/auth/register/", data, format="json")
    assert response.status_code == 400
    assert "password_confirm" in response.json()
    assert User.objects.count() == 0
