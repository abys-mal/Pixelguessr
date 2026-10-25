"""Audited administrator writers; no game/account sanctions are changed here."""

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from core.client_ip import ClientIPError, is_trusted_proxy, normalize_ip

from .administration import audit, require_administrator
from .administration_serializers import StrictInput
from .ip_rules import ACTIVITIES
from .models import IPAccessEntry


class IPInput(StrictInput):
    address = serializers.CharField(max_length=64)
    reason = serializers.CharField(max_length=2000)

    def validate_address(self, value):
        try:
            return normalize_ip(value)
        except ClientIPError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class BlacklistInput(IPInput):
    activities = serializers.ListField(
        child=serializers.ChoiceField(choices=ACTIVITIES),
        allow_empty=False,
        max_length=len(ACTIVITIES),
    )
    duration = serializers.ChoiceField(choices=["temporary", "indefinite"])
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_activities(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Select each activity only once.")
        return value

    def validate(self, data):
        expires = data.get("expires_at")
        if data["duration"] == "temporary":
            if expires is None or expires <= timezone.now():
                raise serializers.ValidationError(
                    {"expires_at": "Choose an expiration in the future."}
                )
        elif expires is not None:
            raise serializers.ValidationError(
                {"expires_at": "Indefinite restrictions have no expiration."}
            )
        data.pop("duration")
        data["expires_at"] = expires
        return data


def entry_values(entry):
    return {
        "address": entry.address,
        "list_kind": entry.list_kind,
        "reason": entry.reason,
        "activities": entry.activities,
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
    }


def entry_payload(entry):
    return {
        "id": str(entry.pk),
        **entry_values(entry),
        "status": "expired"
        if entry.expires_at and entry.expires_at <= timezone.now()
        else "active",
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "created_by": entry.created_by.username if entry.created_by else "Deleted administrator",
        "updated_by": entry.updated_by.username if entry.updated_by else "Deleted administrator",
    }


def save_entry(actor, list_kind, data, *, pk=None):
    try:
        with transaction.atomic():
            # Reserve the SQLite writer before mutable reads; PostgreSQL also locks matching rows.
            target = {"pk": pk} if pk else {"address": data["address"]}
            IPAccessEntry.objects.filter(list_kind=list_kind, **target).update(reason=F("reason"))
            actor = require_administrator(actor)
            entry = (
                get_object_or_404(IPAccessEntry, pk=pk, list_kind=list_kind)
                if pk
                else IPAccessEntry(list_kind=list_kind, created_by=actor)
            )
            before = entry_values(entry) if pk else {}
            if list_kind == "blacklist" and is_trusted_proxy(data["address"]):
                raise ValidationError(
                    {
                        "address": "This address belongs to configured trusted proxy infrastructure; target the end-client IP instead."
                    }
                )
            if (
                IPAccessEntry.objects.filter(list_kind=list_kind, address=data["address"])
                .exclude(pk=entry.pk)
                .exists()
            ):
                raise ValidationError({"address": "This IP is already in this list."})
            entry.address = data["address"]
            entry.reason = data["reason"]
            entry.expires_at = data.get("expires_at")
            if entry.expires_at is not None and entry.expires_at <= timezone.now():
                raise ValidationError({"expires_at": "Choose an expiration in the future."})
            for activity in ACTIVITIES:
                setattr(entry, "block_" + activity, activity in data.get("activities", []))
            entry.block_ranked = False  # Legacy storage only; ranked always requires sign-in.
            entry.updated_by = actor
            try:
                entry.full_clean(validate_unique=False, validate_constraints=False)
            except ModelValidationError as exc:
                raise ValidationError(exc.message_dict) from exc
            entry.save()
            audit(
                actor,
                "ip_entry_edited" if pk else "ip_entry_created",
                ("ip_access", entry.pk),
                before,
                entry_values(entry),
                entry.reason,
            )
            return entry
    except IntegrityError as exc:
        if (
            IPAccessEntry.objects.filter(list_kind=list_kind, address=data["address"])
            .exclude(pk=pk)
            .exists()
        ):
            raise ValidationError({"address": "This IP is already in this list."}) from exc
        raise ValidationError(
            "The entry could not be saved. Review its configuration and retry."
        ) from exc


@transaction.atomic
def delete_entry(actor, list_kind, pk):
    IPAccessEntry.objects.filter(list_kind=list_kind, pk=pk).update(reason=F("reason"))
    actor = require_administrator(actor)
    entry = get_object_or_404(IPAccessEntry, pk=pk, list_kind=list_kind)
    audit(actor, "ip_entry_deleted", ("ip_access", entry.pk), entry_values(entry), {}, entry.reason)
    entry.delete()
