"""Rules for newly assigned usernames; existing identities are left intact."""

import unicodedata

from django.core.exceptions import ValidationError


def validate_username_rules(value):
    value = unicodedata.normalize("NFKC", value)
    if any(character.isspace() for character in value):
        raise ValidationError("Usernames cannot contain spaces or other whitespace.")
    if value.endswith(("-", "_")):
        raise ValidationError("Usernames cannot end with a hyphen (-) or underscore (_).")
