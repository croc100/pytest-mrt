"""Tests for the mrt CLI commands."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pytest_mrt.cli import app

runner = CliRunner()


@pytest.fixture()
def versions_dir(tmp_path):
    v = tmp_path / "versions"
    v.mkdir()
    return v


def _safe_migration(versions_dir: Path, name="001_safe.py"):
    (versions_dir / name).write_text(
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.create_table('users',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
            )
        def downgrade():
            op.drop_table('users')
    """)
    )


def _risky_migration(versions_dir: Path, name="002_risky.py"):
    (versions_dir / name).write_text(
        textwrap.dedent("""
        revision = '002'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.drop_column('users', 'email')
        def downgrade():
            pass
    """)
    )


# ── mrt version ─────────────────────────────────


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "pytest-mrt" in result.output


def test_version_shows_number():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    # should contain a version number like 0.7.0
    import re

    assert re.search(r"\d+\.\d+", result.output)


# ── mrt check ────────────────────────────────────


def test_check_safe_migrations_exits_0(tmp_path, versions_dir):
    _safe_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir)])
    assert result.exit_code == 0
    assert "No rollback risks" in result.output


def test_check_risky_migration_exits_2(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir)])
    assert result.exit_code == 2


def test_check_shows_pattern_name(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir)])
    assert "No-op downgrade" in result.output or "DROP COLUMN" in result.output


def test_check_shows_line_number(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir)])
    # line number column should appear for errors with line info
    import re

    assert re.search(r"\d+", result.output)


def test_check_json_format(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir), "--format", "json"])
    import json

    data = json.loads(result.output)
    assert isinstance(data, dict)
    assert "version" in data
    assert "checked_at" in data
    assert "summary" in data
    assert "findings" in data
    assert data["summary"]["total_issues"] > 0
    assert data["summary"]["errors"] > 0
    finding = data["findings"][0]
    assert "rule" in finding
    assert "severity" in finding
    assert "fixable" in finding
    assert result.exit_code == 2  # errors → exit 2


def test_check_json_safe_exits_0(tmp_path, versions_dir):
    _safe_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir), "--format", "json"])
    assert result.exit_code == 0


def test_check_json_warnings_only_exits_1(tmp_path, versions_dir):
    """--format json with warnings but no errors must exit 1."""
    (versions_dir / "001.py").write_text(
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.create_index('ix_name', 'users', ['name'])
        def downgrade():
            op.drop_index('ix_name', table_name='users')
    """)
    )
    result = runner.invoke(app, ["check", str(versions_dir), "--format", "json"])
    assert result.exit_code == 1


def test_check_html_format_writes_file(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    out = tmp_path / "report.html"
    result = runner.invoke(app, ["check", str(versions_dir), "--format", "html", "--output", str(out)])
    assert out.exists()
    content = out.read_text()
    assert "<html" in content
    assert result.exit_code == 2  # errors → exit 2


def test_check_html_format_default_filename(tmp_path, versions_dir):
    _safe_migration(versions_dir)
    import os
    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["check", str(versions_dir), "--format", "html"])
        assert (tmp_path / "mrt-report.html").exists()
        assert result.exit_code == 0
    finally:
        os.chdir(orig)


def test_check_json_output_flag(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    import json
    out = tmp_path / "out.json"
    result = runner.invoke(app, ["check", str(versions_dir), "--format", "json", "--output", str(out)])
    assert out.exists()
    data = json.loads(out.read_text())
    assert "findings" in data
    assert result.exit_code == 2


def test_check_strict_exits_1_on_warnings(tmp_path, versions_dir):
    # A migration with only warnings (not errors) exits 0 normally
    (versions_dir / "001.py").write_text(
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.create_index('ix_users_name', 'users', ['name'])
        def downgrade():
            op.drop_index('ix_users_name', table_name='users')
    """)
    )
    result_normal = runner.invoke(app, ["check", str(versions_dir)])
    result_strict = runner.invoke(app, ["check", str(versions_dir), "--strict"])
    # warnings only: exit 1 normally, exit 2 with --strict
    assert result_normal.exit_code == 1
    assert result_strict.exit_code == 2


def test_check_detects_django_migrations(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001_initial.py").write_text(
        textwrap.dedent("""
        from django.db import migrations, models
        class Migration(migrations.Migration):
            dependencies = []
            operations = [
                migrations.CreateModel(name='User', fields=[
                    ('id', models.AutoField(primary_key=True)),
                ]),
            ]
    """)
    )
    result = runner.invoke(app, ["check", str(d)])
    assert "Django" in result.output or result.exit_code == 0


def test_check_empty_directory_exits_0(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["check", str(empty)])
    assert result.exit_code == 0


def test_check_nonexistent_path_exits_1(tmp_path):
    result = runner.invoke(app, ["check", str(tmp_path / "does_not_exist")])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_check_file_instead_of_dir_exits_1(tmp_path):
    f = tmp_path / "not_a_dir.py"
    f.write_text("# not a directory")
    result = runner.invoke(app, ["check", str(f)])
    assert result.exit_code == 1
    assert "not a directory" in result.output


# ── mrt check --since ────────────────────────────


def test_check_since_unknown_revision_exits_1(tmp_path, versions_dir):
    """--since with an unknown revision exits 1 with a clear warning."""
    _safe_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir), "--since", "deadbeef"])
    assert result.exit_code == 1
    assert "matched no migrations" in result.output


def test_check_since_valid_revision_shows_note(tmp_path, versions_dir):
    """--since with a valid revision prints the graph-checks-skipped note."""
    # migration 001 (down_revision=None), migration 002 (down_revision=001)
    _safe_migration(versions_dir, name="001_safe.py")
    (versions_dir / "002_after.py").write_text(
        textwrap.dedent("""
        revision = '002'
        down_revision = '001'
        from alembic import op
        def upgrade():
            op.create_table('posts', )
        def downgrade():
            op.drop_table('posts')
        """)
    )
    result = runner.invoke(app, ["check", str(versions_dir), "--since", "001"])
    assert result.exit_code == 0
    assert "graph checks" in result.output
    assert "skipped" in result.output


def test_check_since_valid_revision_shows_count(tmp_path, versions_dir):
    """--since prints how many migrations are being checked."""
    _safe_migration(versions_dir, name="001_safe.py")
    (versions_dir / "002_after.py").write_text(
        textwrap.dedent("""
        revision = '002'
        down_revision = '001'
        from alembic import op
        def upgrade():
            pass
        def downgrade():
            pass
        """)
    )
    result = runner.invoke(app, ["check", str(versions_dir), "--since", "001"])
    assert "1 migration" in result.output


# ── mrt init Django detection ────────────────────


def test_init_detects_django_via_manage_py(tmp_path, monkeypatch):
    """init switches to Django mode when manage.py exists and no alembic.ini."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "manage.py").write_text("# django manage")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "myproject.settings_test")
    result = runner.invoke(
        app,
        ["init"],
        input="\n\n",  # accept all defaults
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Django" in result.output


def test_init_django_creates_django_conftest(tmp_path, monkeypatch):
    """init writes django_settings into conftest.py for Django projects."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "manage.py").write_text("# django manage")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "myproject.settings_test")
    runner.invoke(
        app,
        ["init"],
        input="\n\n",
        catch_exceptions=False,
    )
    conftest = tmp_path / "conftest.py"
    assert conftest.exists()
    content = conftest.read_text()
    assert "django_settings" in content
    assert "alembic_ini" not in content


def test_init_django_creates_test_migrations(tmp_path, monkeypatch):
    """init creates test_migrations.py for Django projects."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "manage.py").write_text("# django manage")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "myproject.settings_test")
    runner.invoke(
        app,
        ["init"],
        input="\n\n",
        catch_exceptions=False,
    )
    test_file = tmp_path / "test_migrations.py"
    assert test_file.exists()
    assert "assert_all_reversible" in test_file.read_text()


def test_init_alembic_mode_when_manage_py_and_alembic_ini_both_exist(tmp_path, monkeypatch):
    """init uses Alembic mode when alembic.ini exists, even if manage.py is present."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "manage.py").write_text("# django manage")
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "myproject.settings_test")
    result = runner.invoke(
        app,
        ["init"],
        input="\nsqlite:///test.db\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    conftest = tmp_path / "conftest.py"
    if conftest.exists():
        assert "alembic_ini" in conftest.read_text()


# ── mrt fix ──────────────────────────────────────


def test_fix_no_issues(tmp_path):
    f = tmp_path / "mig.py"
    f.write_text(
        textwrap.dedent("""
        revision = '001'
        from alembic import op
        def upgrade():
            op.create_table('users')
        def downgrade():
            op.drop_table('users')
    """)
    )
    result = runner.invoke(app, ["fix", str(f)])
    assert result.exit_code == 0
    assert "No fix needed" in result.output


def test_fix_suggests_downgrade(tmp_path):
    f = tmp_path / "mig.py"
    f.write_text(
        textwrap.dedent("""
        revision = '001'
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.create_table('events', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """)
    )
    result = runner.invoke(app, ["fix", str(f)])
    assert result.exit_code == 0
    assert "downgrade" in result.output.lower()


def test_fix_apply_writes_file(tmp_path):
    f = tmp_path / "mig.py"
    f.write_text(
        textwrap.dedent("""
        revision = '001'
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.create_table('jobs', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """)
    )
    result = runner.invoke(app, ["fix", str(f), "--apply"])
    assert result.exit_code == 0
    content = f.read_text()
    assert 'drop_table("jobs")' in content


def test_fix_missing_file(tmp_path):
    result = runner.invoke(app, ["fix", str(tmp_path / "nonexistent.py")])
    assert result.exit_code == 1


def test_fix_batch_requires_apply_flag(tmp_path):
    result = runner.invoke(app, ["fix"])
    assert result.exit_code == 1
    assert "--apply" in result.output


def test_fix_batch_dry_run(tmp_path):
    mig = tmp_path / "0001_initial.py"
    mig.write_text(textwrap.dedent("""
        revision = '0001'
        from alembic import op
        def upgrade():
            op.create_table('users', op.Column('id', op.Integer, primary_key=True))
        def downgrade():
            pass
    """))
    result = runner.invoke(app, ["fix", "--apply", "--dry-run", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "dry-run" in result.output.lower() or "Dry-run" in result.output
    # File should NOT be modified in dry-run
    assert "pass" in mig.read_text()


def test_fix_batch_applies_all(tmp_path):
    for i in range(3):
        mig = tmp_path / f"000{i}_mig.py"
        mig.write_text(textwrap.dedent(f"""
            revision = '000{i}'
            from alembic import op
            def upgrade():
                op.create_table('t{i}', op.Column('id', op.Integer, primary_key=True))
            def downgrade():
                pass
        """))
    result = runner.invoke(app, ["fix", "--apply", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "fixed" in result.output


# ── mrt report ───────────────────────────────────


def test_report_generates_html(tmp_path, versions_dir):
    _safe_migration(versions_dir)
    output = str(tmp_path / "report.html")
    result = runner.invoke(app, ["report", str(versions_dir), "--output", output])
    assert result.exit_code == 0
    assert Path(output).exists()
    content = Path(output).read_text()
    assert "<!DOCTYPE html>" in content


def test_report_default_output(tmp_path, versions_dir, monkeypatch):
    _safe_migration(versions_dir)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report", str(versions_dir)])
    assert result.exit_code == 0
    assert (tmp_path / "migration_report.html").exists()


# ── mrt init ─────────────────────────────────────


def test_init_creates_conftest_and_test_file(tmp_path, monkeypatch):
    """init with no alembic.ini prompts for path, creates both files."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Next steps" in result.output


def test_init_finds_alembic_ini(tmp_path, monkeypatch):
    """init detects alembic.ini in current dir, skips path prompt."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    result = runner.invoke(
        app,
        ["init"],
        input="sqlite:///test.db\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Found" in result.output


def test_init_creates_conftest_file(tmp_path, monkeypatch):
    """init writes conftest.py when it doesn't exist."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\n",
        catch_exceptions=False,
    )
    conftest = tmp_path / "conftest.py"
    assert conftest.exists()
    content = conftest.read_text()
    assert "MRTConfig" in content
    assert "alembic.ini" in content


def test_init_creates_test_migrations_file(tmp_path, monkeypatch):
    """init writes test_migrations.py when it doesn't exist."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\n",
        catch_exceptions=False,
    )
    test_file = tmp_path / "test_migrations.py"
    assert test_file.exists()
    assert "assert_all_reversible" in test_file.read_text()


def test_init_skips_existing_conftest_when_declined(tmp_path, monkeypatch):
    """init skips conftest.py when user declines to overwrite."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "conftest.py").write_text("# existing\n")
    result = runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\nn\n",
        catch_exceptions=False,
    )
    assert (tmp_path / "conftest.py").read_text() == "# existing\n"
    assert "Skipping" in result.output


def test_init_appends_to_existing_conftest_when_accepted(tmp_path, monkeypatch):
    """init appends MRTConfig to existing conftest.py when user accepts."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "conftest.py").write_text("# existing\n")
    runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\ny\n",
        catch_exceptions=False,
    )
    content = (tmp_path / "conftest.py").read_text()
    assert "# existing" in content
    assert "MRTConfig" in content


def test_init_skips_existing_test_migrations(tmp_path, monkeypatch):
    """init skips test_migrations.py if it already exists."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test_migrations.py").write_text("# already here\n")
    runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\n",
        catch_exceptions=False,
    )
    assert (tmp_path / "test_migrations.py").read_text() == "# already here\n"


def test_init_uses_tests_dir_if_exists(tmp_path, monkeypatch):
    """init uses tests/ as test_dir when the directory exists."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    runner.invoke(
        app,
        ["init"],
        input="alembic.ini\nsqlite:///test.db\n",
        catch_exceptions=False,
    )
    assert (tmp_path / "tests" / "conftest.py").exists() or (
        tmp_path / "tests" / "test_migrations.py"
    ).exists()


# ── mrt explain ──────────────────────────────────


def test_explain_missing_anthropic(tmp_path):
    """explain exits 1 with helpful message when anthropic is not installed."""
    import sys
    import unittest.mock as mock

    f = tmp_path / "mig.py"
    f.write_text("# migration\n")

    with mock.patch.dict(sys.modules, {"anthropic": None}):
        result = runner.invoke(app, ["explain", str(f)])

    assert result.exit_code == 1
    assert "not installed" in result.output or "Missing" in result.output


def test_explain_missing_file(tmp_path):
    """explain exits 1 — either file not found or anthropic not installed."""
    result = runner.invoke(app, ["explain", str(tmp_path / "nonexistent.py")])
    assert result.exit_code == 1
    # anthropic may or may not be installed; either way, exit 1
    assert "not found" in result.output.lower() or "not installed" in result.output.lower()


# ── mrt fix edge cases ───────────────────────────


def test_fix_shows_confidence(tmp_path):
    """fix output contains confidence level."""
    f = tmp_path / "mig.py"
    f.write_text(
        textwrap.dedent("""
        revision = '001'
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.create_table('widgets', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """)
    )
    result = runner.invoke(app, ["fix", str(f)])
    assert result.exit_code == 0
    assert any(level in result.output.lower() for level in ["high", "medium", "low"])


def test_fix_shows_run_with_apply_hint(tmp_path):
    """fix without --apply tells user to run with --apply."""
    f = tmp_path / "mig.py"
    f.write_text(
        textwrap.dedent("""
        revision = '001'
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.create_table('items', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """)
    )
    result = runner.invoke(app, ["fix", str(f)])
    assert "--apply" in result.output
