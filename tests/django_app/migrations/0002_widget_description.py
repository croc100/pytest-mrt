from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("django_app", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="Widget",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
