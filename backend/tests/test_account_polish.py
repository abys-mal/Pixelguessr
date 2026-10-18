from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.contrib.sessions.models import Session
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from accounts.consumer import read_status
from accounts.models import User
from games.reveal import COVER_COLOR, render_reveal
from library.models import ImageSubmission
from moderation.models import Activity, Report, Sanction

pytestmark = pytest.mark.django_db
ROOT = "/api/moderation/workspace/"
PASSWORD = "a-strong-unique-pass-734"


@pytest.fixture
def polish_admin():
    return User.objects.create_superuser(username="polish_admin", email="admin@polish.test")


def sanction(user, admin, kind, **fields):
    return Sanction.objects.create(
        user=user, issued_by=admin, kind=kind, category="fair_play", **fields
    )


@pytest.mark.parametrize("reason", ["Public closure reason", ""])
def test_closed_login_details_require_verified_credentials(client, user, polish_admin, reason):
    closure = sanction(
        user, polish_admin, "closed", reason=reason, internal_note="PRIVATE staff note"
    )
    response = client.post("/api/auth/login/", {"username": user.username, "password": PASSWORD})
    assert response.status_code == 400
    assert response.json() == {
        "code": "account_closed",
        "detail": "Your account has been closed.",
        "closure": {
            "reason": reason or "No reason provided.",
            "issued_at": closure.starts_at.isoformat(),
        },
    }
    assert "no-store" in response["Cache-Control"]
    assert "_auth_user_id" not in client.session
    assert client.get("/api/auth/me/").json() == {"user": None, "restrictions": None}
    failures = [
        client.post("/api/auth/login/", {"username": name, "password": "incorrect"}).json()
        for name in [user.username, "nonexistent"]
    ]
    assert failures[0] == failures[1] == {"non_field_errors": ["Invalid username or password."]}
    profile = client.get(f"/api/auth/profiles/{user.username}/")
    assert "closure" not in profile.json() and "reason" not in profile.json()


def test_inactive_without_closure_is_generic_and_does_not_sign_in(client, user):
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = client.post("/api/auth/login/", {"username": user.username, "password": PASSWORD})
    assert response.status_code == 400 and "closure" not in response.json()
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize("kind", [None, "warning", "probation", "suspension"])
def test_other_standings_keep_normal_login(client, user, polish_admin, kind):
    if kind:
        sanction(user, polish_admin, kind, reason="Visible notice")
    assert (
        client.post(
            "/api/auth/login/", {"username": user.username, "password": PASSWORD}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me/").json()["user"]["id"] == str(user.pk)


@pytest.mark.parametrize("socket", [False, True])
def test_closed_session_is_consumed_once(client, user, polish_admin, socket):
    client.force_login(user, backend="accounts.backends.AccountBackend")
    key = client.session.session_key
    sanction(user, polish_admin, "closed", reason="Public closure")
    if socket:
        identity, first = read_status(key)
        assert identity == user.pk
        assert read_status(key) == (None, {"user": None, "restrictions": None})
    else:
        first = client.get("/api/auth/me/").json()
    assert first["user"] is None and first["account_closed"]
    assert not Session.objects.filter(session_key=key).exists()
    assert client.get("/api/auth/me/").json() == {"user": None, "restrictions": None}


@pytest.mark.parametrize(
    "state,closed",
    [
        ("open", False),
        ("inactive", False),
        ("warning", False),
        ("probation", False),
        ("suspension", False),
        ("closed", True),
        ("reversed", False),
        ("future", False),
    ],
)
def test_player_directory_closure_uses_active_sanction(client, user, polish_admin, state, closed):
    if state == "inactive":
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif state not in ["open", "inactive"]:
        row = sanction(user, polish_admin, "closed" if state in ["reversed", "future"] else state)
        if state == "reversed":
            row.revoked_at, row.revoked_by = timezone.now(), polish_admin
            row.save()
        if state == "future":
            row.starts_at = timezone.now() + timedelta(days=1)
            row.save()
    client.force_authenticate(polish_admin)
    rows = client.get(ROOT + f"players/?q={user.username}").json()["results"]
    assert len(rows) == 1 and rows[0]["closed"] is closed


@pytest.mark.parametrize(
    "state,allowed",
    [
        ("open", True),
        ("warning", True),
        ("probation", True),
        ("suspension", False),
        ("expired", True),
        ("lifted", True),
        ("future", True),
        ("closed", False),
    ],
)
def test_report_permission_and_no_blocked_side_effects(client, user, polish_admin, state, allowed):
    if state != "open":
        row = sanction(
            user, polish_admin, "suspension" if state in ["expired", "lifted", "future"] else state
        )
        if state == "expired":
            row.starts_at = timezone.now() - timedelta(days=2)
            row.expires_at = timezone.now() - timedelta(days=1)
            row.save()
        elif state == "lifted":
            row.revoked_at, row.revoked_by = timezone.now(), polish_admin
            row.save()
        elif state == "future":
            row.starts_at = timezone.now() + timedelta(days=1)
            row.save()
    client.force_authenticate(user)
    before = Activity.objects.count()
    response = client.post(
        "/api/moderation/reports/",
        {"subject": str(polish_admin.pk), "category": "fair_play", "details": "A test report."},
        format="json",
    )
    assert response.status_code == (201 if allowed else 403)
    assert Report.objects.count() == int(allowed)
    assert Activity.objects.count() == before + int(allowed)
    if state == "suspension":
        assert (
            response.json()["detail"] == "Reporting is unavailable while your account is suspended."
        )
        assert client.get("/api/moderation/notices/").status_code == 200
        assert (
            client.post(
                f"/api/moderation/sanctions/{row.pk}/appeal/",
                {"explanation": "Please reconsider."},
                format="json",
            ).status_code
            == 201
        )


def test_preview_scattered_stable_prefix_complete_and_new_run(client, polish_admin, category):
    stream = BytesIO()
    Image.new("RGB", (40, 40), "red").save(stream, format="WEBP", lossless=True)
    image = ImageSubmission.objects.create(
        submitted_by=polish_admin,
        category=category,
        canonical_answer="red",
        image_file=ContentFile(stream.getvalue(), name="test-preview.webp"),
    )
    client.force_authenticate(polish_admin)
    url = ROOT + f"administration/images/{image.pk}/preview/"
    run = UUID(int=1)
    with patch("moderation.administration_views.render_reveal", wraps=render_reveal) as render:
        frames = [client.get(url, {"reveal": count, "run": run}) for count in [80, 160, 400]]
        orders = [call.args[0].reveal_order for call in render.call_args_list]
        assert orders[0] == orders[1] == orders[2]
        assert sorted(orders[0]) == list(range(400))
        assert {(tile // 200, tile % 20 // 10) for tile in orders[0][:80]} == {
            (0, 0),
            (0, 1),
            (1, 0),
            (1, 1),
        }
        assert orders[0] != list(range(400))
        client.get(url, {"reveal": 80, "run": uuid4()})
        assert render.call_args.args[0].reveal_order != orders[0]
    visible = []
    for response in frames:
        assert response.status_code == 200
        decoded = Image.open(BytesIO(response.content))
        visible.append(
            {
                tile
                for tile in range(400)
                if decoded.getpixel(((tile % 20) * 48 + 24, (tile // 20) * 36 + 18)) != COVER_COLOR
            }
        )
    assert len(visible[0]) == 80 and len(visible[1]) == 160
    assert visible[0] < visible[1] < visible[2] == set(range(400))
    assert client.get(url, {"reveal": 1, "run": "invalid"}).status_code == 400
    assert client.get(url, {"reveal": 401, "run": run}).status_code == 400
    client.force_authenticate(None)
    assert client.get(url, {"reveal": 400, "run": run}).status_code == 403
