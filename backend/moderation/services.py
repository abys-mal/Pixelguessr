from django.db.models import Q
from django.utils import timezone

from .models import Sanction


def active_sanctions(user):
    now = timezone.now()
    return user.sanctions.filter(starts_at__lte=now, revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )


def account_restrictions(user):
    sanctions = list(active_sanctions(user))
    kinds = {s.kind for s in sanctions}
    return {
        "blocked": not user.is_active
        or bool(kinds & {Sanction.Kind.SUSPENSION, Sanction.Kind.CLOSED}),
        "probation": Sanction.Kind.PROBATION in kinds,
        "unacknowledged_warnings": [
            str(s.id)
            for s in sanctions
            if s.kind == Sanction.Kind.WARNING and not s.acknowledged_at
        ],
    }
