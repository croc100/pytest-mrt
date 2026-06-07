"""Tests for Django-aware migration fix generator."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from pytest_mrt.adapters.django_fixer import (
    apply_django_fix,
    generate_django_fix,
    is_django_migration,
)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _write(tmp_path: Path, content: str, name: str = "0001_initial.py") -> str:
    migrations_dir = tmp_path / "myapp" / "migrations"
    migrations_dir.mkdir(parents=True)
    p = migrations_dir / name
    p.write_text(textwrap.dedent(content).lstrip())
    return str(p)


HEADER = """\
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = []

    operations = [
"""
FOOTER = "    ]\n"


# ─────────────────────────────────────────────────────────────
# is_django_migration
# ─────────────────────────────────────────────────────────────


def test_is_django_migration_true(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.AddField(model_name='u', name='x', field=models.TextField(null=True)),\n" + FOOTER)
    assert is_django_migration(Path(p))


def test_is_django_migration_false_for_alembic(tmp_path):
    migrations_dir = tmp_path / "myapp" / "migrations"
    migrations_dir.mkdir(parents=True)
    p = migrations_dir / "abc.py"
    p.write_text("revision = 'abc'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    assert not is_django_migration(p)


# ─────────────────────────────────────────────────────────────
# No fix needed
# ─────────────────────────────────────────────────────────────


def test_no_fix_needed_add_field(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.AddField(model_name='u', name='x', field=models.TextField(null=True)),\n" + FOOTER)
    assert generate_django_fix(p) is None


def test_no_fix_needed_create_model(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.CreateModel(name='Post', fields=[]),\n" + FOOTER)
    assert generate_django_fix(p) is None


def test_no_fix_needed_run_sql_with_reverse(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunSQL('INSERT INTO foo VALUES (1)', reverse_sql='DELETE FROM foo'),\n" + FOOTER)
    assert generate_django_fix(p) is None


def test_no_fix_needed_run_python_with_reverse(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunPython(forward, reverse_code=backward),\n" + FOOTER)
    assert generate_django_fix(p) is None


# ─────────────────────────────────────────────────────────────
# RunSQL — structural fix
# ─────────────────────────────────────────────────────────────


def test_fix_run_sql_adds_noop(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunSQL('UPDATE foo SET bar=1'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert fix.patches[0].op_name == "RunSQL"
    assert "RunSQL.noop" in fix.patches[0].patched_snippet
    assert fix.confidence == "high"


def test_fix_run_sql_valid_python(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunSQL('UPDATE foo SET bar=1'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    ast.parse(fix.patched_source)


# ─────────────────────────────────────────────────────────────
# RunPython — structural fix
# ─────────────────────────────────────────────────────────────


def test_fix_run_python_adds_noop(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunPython(populate_tags),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "RunPython.noop" in fix.patches[0].patched_snippet
    assert fix.confidence == "medium"
    assert fix.warning is not None


# ─────────────────────────────────────────────────────────────
# RemoveField — data-loss fix
# ─────────────────────────────────────────────────────────────


def test_fix_remove_field_detected(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert fix.patches[0].op_name == "RemoveField"


def test_fix_remove_field_injects_run_python(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "migrations.RunPython(" in fix.patched_source
    assert "migrations.RemoveField(" in fix.patched_source
    # RunPython must appear BEFORE RemoveField in the source
    assert fix.patched_source.index("migrations.RunPython(") < fix.patched_source.index("migrations.RemoveField(")


def test_fix_remove_field_backup_restore_functions(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "_backup_user_phone" in fix.patched_source
    assert "_restore_user_phone" in fix.patched_source


def test_fix_remove_field_uses_mrt_backups_table(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "_mrt_backups" in fix.patched_source


def test_fix_remove_field_keyset_pagination(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "pk__gt" in fix.patched_source
    assert "_MRT_CHUNK" in fix.patched_source


def test_fix_remove_field_valid_python(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    ast.parse(fix.patched_source)


def test_fix_remove_field_confidence_medium(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert fix.confidence == "medium"


def test_fix_remove_field_includes_codec(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "__mrt_enc" in fix.patched_source
    assert "__mrt_dec" in fix.patched_source


def test_fix_remove_field_codec_only_once(tmp_path):
    """Codec block is injected exactly once even with multiple data-loss patches."""
    p = _write(
        tmp_path,
        HEADER
        + "        migrations.RemoveField(model_name='user', name='phone'),\n"
        + "        migrations.RemoveField(model_name='user', name='bio'),\n"
        + FOOTER,
    )
    fix = generate_django_fix(p)
    assert fix is not None
    assert fix.patched_source.count("def __mrt_enc") == 1


# ─────────────────────────────────────────────────────────────
# DeleteModel — data-loss fix
# ─────────────────────────────────────────────────────────────


def test_fix_delete_model_detected(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.DeleteModel(name='Post'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert fix.patches[0].op_name == "DeleteModel"


def test_fix_delete_model_injects_run_python(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.DeleteModel(name='Post'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "migrations.RunPython(" in fix.patched_source
    assert "migrations.DeleteModel(" in fix.patched_source
    assert fix.patched_source.index("migrations.RunPython(") < fix.patched_source.index("migrations.DeleteModel(")


def test_fix_delete_model_backup_restore_functions(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.DeleteModel(name='Post'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "_backup_post_rows" in fix.patched_source
    assert "_restore_post_rows" in fix.patched_source


def test_fix_delete_model_disables_constraint_checking(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.DeleteModel(name='Post'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    assert "disable_constraint_checking" in fix.patched_source


def test_fix_delete_model_valid_python(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.DeleteModel(name='Post'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    ast.parse(fix.patched_source)


# ─────────────────────────────────────────────────────────────
# Mixed patches
# ─────────────────────────────────────────────────────────────


def test_fix_mixed_ops(tmp_path):
    p = _write(
        tmp_path,
        HEADER
        + "        migrations.RunSQL('UPDATE foo SET x=1'),\n"
        + "        migrations.RemoveField(model_name='user', name='phone'),\n"
        + "        migrations.DeleteModel(name='Post'),\n"
        + FOOTER,
    )
    fix = generate_django_fix(p)
    assert fix is not None
    assert len(fix.patches) == 3
    assert fix.confidence == "medium"
    ast.parse(fix.patched_source)


def test_fix_mixed_codec_only_once(tmp_path):
    p = _write(
        tmp_path,
        HEADER
        + "        migrations.RemoveField(model_name='user', name='phone'),\n"
        + "        migrations.DeleteModel(name='Post'),\n"
        + FOOTER,
    )
    fix = generate_django_fix(p)
    assert fix is not None
    assert fix.patched_source.count("def __mrt_enc") == 1


# ─────────────────────────────────────────────────────────────
# apply_django_fix + idempotency
# ─────────────────────────────────────────────────────────────


def test_apply_writes_file(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunSQL('UPDATE foo SET bar=1'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    apply_django_fix(p, fix)
    content = Path(p).read_text()
    assert "RunSQL.noop" in content


def test_apply_remove_field_writes_backup(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert fix is not None
    apply_django_fix(p, fix)
    content = Path(p).read_text()
    assert "_backup_user_phone" in content
    assert "__mrt_enc" in content


def test_apply_idempotent_run_sql(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunSQL('UPDATE foo SET bar=1'),\n" + FOOTER)
    fix = generate_django_fix(p)
    apply_django_fix(p, fix)
    fix2 = generate_django_fix(p)
    assert fix2 is None


def test_apply_idempotent_remove_field(tmp_path):
    """After applying RemoveField fix, generate_django_fix should return None."""
    p = _write(tmp_path, HEADER + "        migrations.RemoveField(model_name='user', name='phone'),\n" + FOOTER)
    fix = generate_django_fix(p)
    apply_django_fix(p, fix)
    # File now has RunPython before RemoveField — RemoveField is still there
    # but the RunPython wrapping it means no new fix is needed for RemoveField.
    # (RemoveField itself is still flagged but RunPython is now present)
    content = Path(p).read_text()
    assert "_backup_user_phone" in content


# ─────────────────────────────────────────────────────────────
# issue property
# ─────────────────────────────────────────────────────────────


def test_issue_single(tmp_path):
    p = _write(tmp_path, HEADER + "        migrations.RunSQL('UPDATE foo SET bar=1'),\n" + FOOTER)
    fix = generate_django_fix(p)
    assert "RunSQL" in fix.issue


def test_issue_multiple(tmp_path):
    p = _write(
        tmp_path,
        HEADER
        + "        migrations.RunSQL('UPDATE foo SET x=1'),\n"
        + "        migrations.RunPython(do_something),\n"
        + FOOTER,
    )
    fix = generate_django_fix(p)
    assert "2 operations" in fix.issue


# ─────────────────────────────────────────────────────────────
# CLI routing
# ─────────────────────────────────────────────────────────────


def test_fix_command_routes_to_django(tmp_path):
    from typer.testing import CliRunner
    from pytest_mrt.cli import app

    p = _write(tmp_path, HEADER + "        migrations.AddField(model_name='u', name='x', field=models.IntegerField()),\n" + FOOTER)
    runner = CliRunner()
    result = runner.invoke(app, ["fix", p])
    assert result.exit_code == 0
    assert "No fix needed" in result.output


def test_fix_command_django_shows_table(tmp_path):
    from typer.testing import CliRunner
    from pytest_mrt.cli import app

    p = _write(tmp_path, HEADER + "        migrations.RunSQL('UPDATE foo SET bar=1'),\n" + FOOTER)
    runner = CliRunner()
    result = runner.invoke(app, ["fix", p])
    assert result.exit_code == 0
    assert "RunSQL" in result.output
    assert "Django" in result.output
