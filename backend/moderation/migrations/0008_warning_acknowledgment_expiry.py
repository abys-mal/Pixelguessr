from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def acknowledgment_expiry(apps, schema_editor):
    warnings = (
        apps.get_model("moderation", "Sanction")
        .objects.using(schema_editor.connection.alias)
        .filter(kind="warning")
    )
    warnings.filter(acknowledged_at__isnull=False).update(
        expires_at=models.F("acknowledged_at") + timedelta(days=90)
    )
    # Already expired and reversed records stay historical; do not resurrect them.
    warnings.filter(acknowledged_at__isnull=True, revoked_at__isnull=True).filter(
        models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
    ).update(expires_at=None)


def issuance_expiry(apps, schema_editor):
    apps.get_model("moderation", "Sanction").objects.using(schema_editor.connection.alias).filter(
        kind="warning"
    ).update(expires_at=models.F("starts_at") + timedelta(days=90))


class Migration(migrations.Migration):
    dependencies = [("moderation", "0007_ipaccessentry")]
    operations = [
        migrations.RemoveConstraint(model_name="sanction", name="warning_must_expire"),
        migrations.RunPython(acknowledgment_expiry, issuance_expiry),
        migrations.AddConstraint(
            model_name="sanction",
            constraint=models.CheckConstraint(
                condition=~models.Q(kind="warning")
                | models.Q(acknowledged_at__isnull=True)
                | models.Q(
                    expires_at__isnull=False,
                    expires_at=models.F("acknowledged_at") + timedelta(days=90),
                ),
                name="warning_expiry_after_acknowledgment",
            ),
        ),
    ]
