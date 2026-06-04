"""Tests for Django migration static analyzer."""
import textwrap
from pathlib import Path
import pytest
from pytest_mrt.adapters.django_detector import analyze_django_migrations, is_django_migration


def django_migration(tmp_path: Path, filename: str, content: str) -> None:
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / filename).write_text(textwrap.dedent(content).lstrip())


def test_is_django_migration_detected(tmp_path):
    p = tmp_path / "0001_initial.py"
    p.write_text("from django.db import migrations\nclass Migration(migrations.Migration): pass")
    assert is_django_migration(p)


def test_is_not_django_migration(tmp_path):
    p = tmp_path / "001_alembic.py"
    p.write_text("from alembic import op\ndef upgrade(): pass\ndef downgrade(): pass")
    assert not is_django_migration(p)


def test_remove_field_detected(tmp_path):
    django_migration(tmp_path, "0002_remove.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RemoveField(
                    model_name='user',
                    name='phone',
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "RemoveField" for w in warnings)
    errors = [w for w in warnings if w.severity == "error"]
    assert len(errors) >= 1


def test_delete_model_detected(tmp_path):
    django_migration(tmp_path, "0002_delete.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.DeleteModel(name='OldTable'),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "DeleteModel" for w in warnings)


def test_run_sql_without_reverse_detected(tmp_path):
    django_migration(tmp_path, "0002_sql.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RunSQL("UPDATE users SET status = 'active'"),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "RunSQL without reverse_sql" for w in warnings)


def test_run_sql_with_reverse_is_fine(tmp_path):
    django_migration(tmp_path, "0002_sql.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RunSQL(
                    "UPDATE users SET status = 'active'",
                    reverse_sql="UPDATE users SET status = NULL",
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "RunSQL without reverse_sql" for w in warnings)


def test_run_python_without_reverse_detected(tmp_path):
    django_migration(tmp_path, "0002_python.py", """
        from django.db import migrations

        def forward(apps, schema_editor):
            User = apps.get_model('myapp', 'User')
            User.objects.update(name=User.objects.values('name'))

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RunPython(forward),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "RunPython without reverse_code" for w in warnings)


def test_run_python_with_reverse_is_fine(tmp_path):
    django_migration(tmp_path, "0002_python.py", """
        from django.db import migrations

        def forward(apps, schema_editor): pass
        def backward(apps, schema_editor): pass

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RunPython(forward, backward),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "RunPython without reverse_code" for w in warnings)


def test_safe_add_field_no_warnings(tmp_path):
    django_migration(tmp_path, "0002_add.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddField(
                    model_name='user',
                    name='bio',
                    field=models.TextField(null=True, blank=True),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    risky = [w for w in warnings if w.severity == "error"]
    assert len(risky) == 0
