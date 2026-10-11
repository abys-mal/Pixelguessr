from django.db import migrations

CATEGORIES = [
    ("Nature", "nature"),
    ("Animals", "animals"),
    ("Food & drink", "food-drink"),
    ("Objects", "objects"),
    ("Places", "places"),
    ("Art & culture", "art-culture"),
]


def seed_categories(apps, schema_editor):
    category = apps.get_model("library", "Category")
    for name, slug in CATEGORIES:
        category.objects.using(schema_editor.connection.alias).get_or_create(
            slug=slug, defaults={"name": name}
        )


class Migration(migrations.Migration):
    dependencies = [("library", "0001_initial")]
    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
