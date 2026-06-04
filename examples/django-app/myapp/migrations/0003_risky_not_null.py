from django.db import migrations, models


class Migration(migrations.Migration):
    """
    RISKY: AddField with null=False and no default.
    mrt check will flag this as an error.

    Fix: either set null=True, or provide a default:
        field=models.IntegerField(null=False, default=0)
    """

    dependencies = [("myapp", "0002_add_profile")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="login_count",
            field=models.IntegerField(),  # null=False, no default → will break on non-empty tables
        ),
    ]
