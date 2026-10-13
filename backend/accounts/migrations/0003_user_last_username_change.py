from django.db import migrations, models
from django.db.models import F
from django.utils import timezone


def backfill_assignment(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.using(schema_editor.connection.alias).filter(
        last_username_change__isnull=True
    ).update(last_username_change=F("date_joined"))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_ranked_losses_user_ranked_matches_and_more")]
    operations = [
        migrations.AddField(
            model_name="user",
            name="last_username_change",
            field=models.DateTimeField(null=True, editable=False),
        ),
        migrations.RunPython(backfill_assignment, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="last_username_change",
            field=models.DateTimeField(default=timezone.now, editable=False),
        ),
    ]
