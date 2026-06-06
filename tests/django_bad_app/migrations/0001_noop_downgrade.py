"""
Migration with a no-op downgrade — used to verify that DjangoRollbackVerifier
detects schema drift when the rollback path does nothing.

Forward:  creates a table via raw SQL
Backward: RunSQL.noop — the table is never dropped, leaving schema drift.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE TABLE django_bad_app_leaked "
                "(id INTEGER PRIMARY KEY, val TEXT NOT NULL DEFAULT '')"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
