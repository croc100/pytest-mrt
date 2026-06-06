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


def test_add_field_not_null_explicit_detected(tmp_path):
    """AddField with null=False and no default is flagged as error."""
    django_migration(tmp_path, "0002_add.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddField(
                    model_name='user',
                    name='score',
                    field=models.IntegerField(null=False),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "AddField NOT NULL without default" and w.severity == "error"
               for w in warnings)


def test_add_field_not_null_with_default_ok(tmp_path):
    """AddField with null=False but with a default is safe."""
    django_migration(tmp_path, "0002_add.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddField(
                    model_name='user',
                    name='score',
                    field=models.IntegerField(null=False, default=0),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "AddField NOT NULL without default" and w.severity == "error"
                   for w in warnings)


def test_add_field_implicit_not_null_warns(tmp_path):
    """AddField with no null kwarg on a non-nullable-by-default type warns."""
    django_migration(tmp_path, "0002_add.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddField(
                    model_name='user',
                    name='count',
                    field=models.IntegerField(),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "AddField NOT NULL without default" for w in warnings)


def test_alter_field_not_null_detected(tmp_path):
    """AlterField to null=False without default is flagged as error."""
    django_migration(tmp_path, "0002_alter.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AlterField(
                    model_name='user',
                    name='email',
                    field=models.EmailField(null=False),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "AlterField to NOT NULL without default" for w in warnings)


def test_alter_field_with_default_ok(tmp_path):
    """AlterField to null=False with a default is safe."""
    django_migration(tmp_path, "0002_alter.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AlterField(
                    model_name='user',
                    name='email',
                    field=models.EmailField(null=False, default=''),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "AlterField to NOT NULL without default" for w in warnings)


def test_rename_model_alone_no_warning(tmp_path):
    """RenameModel alone is reversible and produces no warning."""
    django_migration(tmp_path, "0002_rename.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RenameModel(old_name='OldUser', new_name='User'),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "RenameModel with data-loss operations" for w in warnings)


def test_rename_model_with_remove_field_warns(tmp_path):
    """RenameModel combined with RemoveField triggers a warning."""
    django_migration(tmp_path, "0002_rename_risky.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RenameModel(old_name='OldUser', new_name='User'),
                migrations.RemoveField(model_name='user', name='phone'),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "RenameModel with data-loss operations" for w in warnings)


def test_add_index_without_atomic_false_warns(tmp_path):
    """AddIndex without atomic=False generates a warning."""
    django_migration(tmp_path, "0002_index.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddIndex(
                    model_name='user',
                    index=models.Index(fields=['email'], name='idx_email'),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "AddIndex without atomic=False" for w in warnings)


def test_add_index_with_atomic_false_ok(tmp_path):
    """AddIndex with atomic=False does not warn about locking."""
    django_migration(tmp_path, "0002_index.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            atomic = False
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddIndex(
                    model_name='user',
                    index=models.Index(fields=['email'], name='idx_email'),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "AddIndex without atomic=False" for w in warnings)


def test_run_sql_truncate_detected(tmp_path):
    """RunSQL containing TRUNCATE is flagged as error."""
    django_migration(tmp_path, "0002_truncate.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RunSQL("TRUNCATE TABLE users"),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "RunSQL TRUNCATE" for w in warnings)


def test_run_sql_drop_table_detected(tmp_path):
    """RunSQL containing DROP TABLE is flagged as error."""
    django_migration(tmp_path, "0002_drop.py", """
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RunSQL("DROP TABLE old_table"),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "RunSQL DROP TABLE" for w in warnings)


def test_syntax_error_migration_is_flagged(tmp_path):
    """A migration file with a syntax error is recorded as a risk warning."""
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "0001_broken.py").write_text(
        "from django.db import migrations\nclass Migration(migrations.Migration:\n    pass\n"
    )
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "Syntax error" for w in warnings)


def test_empty_directory_returns_no_warnings(tmp_path):
    """analyze_django_migrations on an empty dir returns empty list."""
    warnings = analyze_django_migrations(str(tmp_path))
    assert warnings == []


def test_non_migration_file_is_ignored(tmp_path):
    """Python files that aren't Django migrations are skipped."""
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "helpers.py").write_text("def helper(): pass\n")
    warnings = analyze_django_migrations(str(tmp_path))
    assert warnings == []


def test_is_django_migration_unreadable_file(tmp_path):
    """is_django_migration returns False for unreadable paths."""
    result = is_django_migration(tmp_path / "nonexistent.py")
    assert result is False


def test_missing_atomic_false_check(tmp_path):
    """Missing atomic=False is flagged for operations that require it."""
    django_migration(tmp_path, "0002_index.py", """
        from django.db import migrations, models

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.AddIndex(
                    model_name='user',
                    index=models.Index(fields=['name'], name='idx_name'),
                ),
            ]
    """)
    warnings = analyze_django_migrations(str(tmp_path))
    assert any(w.pattern == "Missing atomic=False" for w in warnings)


def test_mrt_ignore_suppresses_django_warning(tmp_path):
    """# mrt: ignore on the same line suppresses that Django migration warning."""
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "0002_remove.py").write_text(textwrap.dedent("""
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RemoveField(  # mrt: ignore
                    model_name='user',
                    name='phone',
                ),
            ]
    """).lstrip())
    warnings = analyze_django_migrations(str(tmp_path))
    assert not any(w.pattern == "RemoveField" for w in warnings)


def test_mrt_ignore_only_suppresses_annotated_django_line(tmp_path):
    """# mrt: ignore on one operation does not suppress others."""
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "0002_multi.py").write_text(textwrap.dedent("""
        from django.db import migrations

        class Migration(migrations.Migration):
            dependencies = [('myapp', '0001_initial')]
            operations = [
                migrations.RemoveField(  # mrt: ignore
                    model_name='user',
                    name='phone',
                ),
                migrations.RemoveField(
                    model_name='user',
                    name='email',
                ),
            ]
    """).lstrip())
    warnings = analyze_django_migrations(str(tmp_path))
    remove_warnings = [w for w in warnings if w.pattern == "RemoveField"]
    assert len(remove_warnings) == 1
    assert "email" in remove_warnings[0].message
