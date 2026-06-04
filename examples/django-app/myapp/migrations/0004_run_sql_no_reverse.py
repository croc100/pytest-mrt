from django.db import migrations


class Migration(migrations.Migration):
    """
    RISKY: RunSQL without reverse_sql.
    mrt check will flag this as an error.

    Fix: add reverse_sql to undo the change:
        migrations.RunSQL(
            sql="UPDATE myapp_user SET login_count = 0 WHERE login_count IS NULL",
            reverse_sql="UPDATE myapp_user SET login_count = NULL",
        )
    """

    dependencies = [("myapp", "0003_risky_not_null")]

    operations = [
        migrations.RunSQL(
            sql="UPDATE myapp_user SET login_count = 0 WHERE login_count IS NULL",
            # no reverse_sql — rollback cannot undo this data migration
        ),
    ]
