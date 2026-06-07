from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Contact",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=128)),
                ("phone", models.CharField(blank=True, max_length=32, null=True)),
            ],
            options={"app_label": "django_fixer_app"},
        ),
    ]
