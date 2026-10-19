from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from accounts.name_filter import NAME_ERROR, validate_player_name
from moderation.models import Activity


@pytest.mark.parametrize(
    "name",
    [
        "fuck",
        "SHIT",
        "Sh1t",
        "n1gger",
        "Porn",
        "ｆｕｃｋ",
        "f.u.c.k",
        "f_u_c_k",
        "f-u-c-k",
        "fuck42",
        "FuckPlayer",
        "f\u200buck",
    ],
)
def test_obvious_names_are_rejected(name):
    with pytest.raises(ValidationError, match="This name isn't allowed"):
        validate_player_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "fuckshit",
        "shitfuck",
        "fuckshitfuck",
        "fuckfuck",
        "sh1tfvck",
        "fvck5h1t",
        "f.u.c.k.s.h.i.t",
        "fuck_shit",
        "fuck.shit",
        "f.u.c.k.shit",
        "playerfuckshit",
        "fuckshitplayer",
        "assass",
    ],
)
def test_joined_prohibited_terms_are_rejected(name):
    with pytest.raises(ValidationError, match="This name isn't allowed"):
        validate_player_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "Scunthorpe",
        "ScunthorpeFan",
        "Dickinson",
        "Classic",
        "Penistone",
        "Cocktail",
        "assassin",
        "AssassinationFan",
        "Massachusetts",
        "analyst",
        "therapist",
        "Shiitake",
        "sextant",
        "cumulative",
        "Cumberland",
        "gay",
        "Lesbian",
        "Queer",
        "Black",
        "Brown",
        "blue_fox",
        "Godfrey",
        "Zoë",
        "",
        "玩家",
    ],
)
def test_ordinary_names_and_neutral_identity_terms_are_accepted(name):
    validate_player_name(name)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("x" * 4, id="four-xs"),
        pytest.param("x" * 5, id="five-xs"),
        pytest.param("x" * 40, id="display-name-limit"),
        pytest.param("x" * 149, id="149-xs"),
        pytest.param("x" * 150, id="username-limit"),
        pytest.param("X" * 150, id="uppercase-xs"),
        pytest.param("ｘ" * 150, id="normalized-xs"),
        pytest.param("a" * 150, id="repeated-a"),
        pytest.param("z" * 150, id="repeated-z"),
        pytest.param("1" * 150, id="repeated-digit"),
    ],
)
def test_harmless_repeated_character_names_are_accepted(name):
    validate_player_name(name)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("xx", id="standalone-xx"),
        pytest.param("xxx", id="standalone-xxx"),
        pytest.param("kkk" * 50, id="substantive-repeated-term"),
        pytest.param("fuck" + "x" * 146, id="x-suffix"),
        pytest.param("x" * 146 + "fuck", id="x-prefix"),
        pytest.param("xxfuckxxx", id="x-surrounded"),
        pytest.param("x" * 142 + "fuckshit", id="joined-with-x-prefix"),
        pytest.param("fuckshit" + "x" * 142, id="joined-with-x-suffix"),
        pytest.param("xxfvck5h1txxx", id="obfuscated-joined-with-padding"),
        pytest.param("x" * 100 + ".f.u.c.k", id="spelled-word-with-padding"),
    ],
)
def test_x_run_exception_does_not_hide_prohibited_names(name):
    with pytest.raises(ValidationError, match="This name isn't allowed"):
        validate_player_name(name)


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["username", "display_name"])
@pytest.mark.parametrize("name", ["Sh1t", "fuckshit", "shitfuck", "fuckfuck", "sh1tfvck"])
def test_registration_filters_both_names(client, field, name):
    data = {
        "username": "new_player",
        "display_name": "New player",
        "email": "new@example.test",
        "password": "forest-strong-password-971!",
        "password_confirm": "forest-strong-password-971!",
        field: name,
    }
    response = client.post("/api/auth/register/", data, format="json")
    assert response.status_code == 400
    assert NAME_ERROR in response.json()[field]
    assert not User.objects.filter(email=data["email"]).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["AssassinationFan", "Scunthorpe", "Dickinson", "Cocktail"])
def test_ordinary_names_work_in_registration_and_both_settings_paths(client, name):
    password = "forest-strong-password-971!"
    response = client.post(
        "/api/auth/register/",
        {
            "username": name,
            "display_name": name,
            "email": "new@example.test",
            "password": password,
            "password_confirm": password,
        },
        format="json",
    )
    assert response.status_code == 201
    user = User.objects.get(username=name)
    client.force_authenticate(user)
    assert (
        client.patch("/api/auth/me/", {"display_name": name + " Fan"}, format="json").status_code
        == 200
    )
    User.objects.filter(pk=user.pk).update(last_username_change=timezone.now() - timedelta(days=91))
    response = client.post(
        "/api/auth/change-username/",
        {"new_username": name + "Fan", "current_password": password},
        format="json",
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.username == name + "Fan" and user.display_name == name + " Fan"


@pytest.mark.django_db
@pytest.mark.parametrize("moderator", [False, True])
@pytest.mark.parametrize("name", ["fuck", "fuckshit", "shitfuck", "fuckfuck", "sh1tfvck"])
def test_self_service_has_no_role_or_client_flag_bypass(client, user, moderator, name):
    if moderator:
        user.user_permissions.add(Permission.objects.get(codename="access_workspace"))
    client.force_authenticate(user)
    response = client.patch(
        "/api/auth/me/", {"display_name": name, "staff_override": True}, format="json"
    )
    assert response.status_code == 400
    assert NAME_ERROR in response.json()["display_name"]
    assigned_at = timezone.now() - timedelta(days=91)
    User.objects.filter(pk=user.pk).update(last_username_change=assigned_at)
    response = client.post(
        "/api/auth/change-username/",
        {"new_username": name, "current_password": "a-strong-unique-pass-734"},
        format="json",
    )
    assert response.status_code == 400
    assert NAME_ERROR in response.json()["new_username"]
    user.refresh_from_db()
    assert user.username == "pixelplayer" and user.display_name == ""
    assert user.last_username_change == assigned_at


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["Sh1t", "fuckshit"])
def test_authorized_operation_can_rename_but_players_cannot(client, user, staff, name):
    endpoint = f"/api/moderation/workspace/players/{user.pk}/names/"
    values = {"username": name, "display_name": name}
    client.force_authenticate(user)
    assert client.post(endpoint, values, format="json").status_code == 403
    staff.user_permissions.add(Permission.objects.get(codename="access_workspace"))
    client.force_authenticate(staff)
    assigned_at = user.last_username_change
    assert client.post(endpoint, values, format="json").status_code == 200
    user.refresh_from_db()
    assert user.username == values["username"] and user.display_name == values["display_name"]
    assert user.last_username_change == assigned_at
    assert Activity.objects.filter(action="player_names_changed", actor=staff, user=user).exists()
    assert client.post(endpoint, {"username": "bad name"}, format="json").status_code == 400


@pytest.mark.django_db
def test_existing_names_are_read_without_revalidation(client, user):
    User.objects.filter(pk=user.pk).update(display_name="fuck")
    user.refresh_from_db()
    client.force_authenticate(user)
    response = client.get("/api/auth/me/")
    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "fuck"
