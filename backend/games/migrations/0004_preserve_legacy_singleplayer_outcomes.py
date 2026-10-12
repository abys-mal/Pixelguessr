from django.db import migrations


def preserve_outcomes(apps, schema_editor):
    game_round = apps.get_model("games", "Round")
    database = schema_editor.connection.alias
    # No invented scores or extra rounds. Keep legacy timestamps, states and images.
    game_round.objects.using(database).filter(
        match__mode="singleplayer",
        match__singleplayer_round_limit=1,
        match__status="complete",
        winner__isnull=False,
    ).update(outcome="solved")
    game_round.objects.using(database).filter(
        match__mode="singleplayer",
        match__singleplayer_round_limit=1,
        match__status="abandoned",
        ended_at__isnull=False,
    ).update(outcome="expired")


class Migration(migrations.Migration):
    dependencies = [("games", "0003_match_singleplayer_expires_at_and_more")]
    operations = [migrations.RunPython(preserve_outcomes, migrations.RunPython.noop)]
