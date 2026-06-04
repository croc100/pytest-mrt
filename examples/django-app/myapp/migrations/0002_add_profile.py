from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("myapp", "0001_create_users")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="bio",
            field=models.TextField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="user",
            name="avatar_url",
            field=models.URLField(null=True),
        ),
    ]
