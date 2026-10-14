from django.db import migrations


def backfill(apps, schema_editor):
    Sanction = apps.get_model("moderation", "Sanction")
    Activity = apps.get_model("moderation", "Activity")
    database = schema_editor.connection.alias
    for sanction in Sanction.objects.using(database).iterator():
        Activity.objects.using(database).get_or_create(
            sanction_id=sanction.pk,
            action="sanction_issued",
            defaults={
                "user_id": sanction.user_id,
                "actor_id": sanction.issued_by_id,
                "created_at": sanction.starts_at,
                "changes": {"kind": sanction.kind, "reason": sanction.reason, "historical": True},
            },
        )
        if sanction.revoked_at:
            Activity.objects.using(database).get_or_create(
                sanction_id=sanction.pk,
                action="sanction_reversed",
                defaults={
                    "user_id": sanction.user_id,
                    "actor_id": sanction.revoked_by_id,
                    "created_at": sanction.revoked_at,
                    "changes": {"kind": sanction.kind, "historical": True},
                },
            )


class Migration(migrations.Migration):
    dependencies = [("moderation", "0002_alter_sanction_options_report_resolution_and_more")]
    operations = [migrations.RunPython(backfill, reverse_code=migrations.RunPython.noop)]
