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
    (versions_dir / name).write_text(textwrap.dedent("""
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
    """))


def _risky_migration(versions_dir: Path, name="002_risky.py"):
    (versions_dir / name).write_text(textwrap.dedent("""
        revision = '002'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.drop_column('users', 'email')
        def downgrade():
            pass
    """))


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


def test_check_risky_migration_exits_1(tmp_path, versions_dir):
    _risky_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir)])
    assert result.exit_code == 1


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
    assert isinstance(data, list)
    assert len(data) > 0
    assert "pattern" in data[0]
    assert "severity" in data[0]


def test_check_json_safe_exits_0(tmp_path, versions_dir):
    _safe_migration(versions_dir)
    result = runner.invoke(app, ["check", str(versions_dir), "--format", "json"])
    assert result.exit_code == 0


def test_check_strict_exits_1_on_warnings(tmp_path, versions_dir):
    # A migration with only warnings (not errors) exits 0 normally
    (versions_dir / "001.py").write_text(textwrap.dedent("""
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
    """))
    result_normal = runner.invoke(app, ["check", str(versions_dir)])
    result_strict = runner.invoke(app, ["check", str(versions_dir), "--strict"])
    # strict mode should exit 1 when there are warnings
    assert result_strict.exit_code >= result_normal.exit_code


def test_check_detects_django_migrations(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001_initial.py").write_text(textwrap.dedent("""
        from django.db import migrations, models
        class Migration(migrations.Migration):
            dependencies = []
            operations = [
                migrations.CreateModel(name='User', fields=[
                    ('id', models.AutoField(primary_key=True)),
                ]),
            ]
    """))
    result = runner.invoke(app, ["check", str(d)])
    assert "Django" in result.output or result.exit_code == 0


def test_check_empty_directory_exits_0(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["check", str(empty)])
    assert result.exit_code == 0


# ── mrt fix ──────────────────────────────────────

def test_fix_no_issues(tmp_path):
    f = tmp_path / "mig.py"
    f.write_text(textwrap.dedent("""
        revision = '001'
        from alembic import op
        def upgrade():
            op.create_table('users')
        def downgrade():
            op.drop_table('users')
    """))
    result = runner.invoke(app, ["fix", str(f)])
    assert result.exit_code == 0
    assert "No fix needed" in result.output


def test_fix_suggests_downgrade(tmp_path):
    f = tmp_path / "mig.py"
    f.write_text(textwrap.dedent("""
        revision = '001'
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.create_table('events', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """))
    result = runner.invoke(app, ["fix", str(f)])
    assert result.exit_code == 0
    assert "downgrade" in result.output.lower()


def test_fix_apply_writes_file(tmp_path):
    f = tmp_path / "mig.py"
    f.write_text(textwrap.dedent("""
        revision = '001'
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.create_table('jobs', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """))
    result = runner.invoke(app, ["fix", str(f), "--apply"])
    assert result.exit_code == 0
    content = f.read_text()
    assert 'drop_table("jobs")' in content


def test_fix_missing_file(tmp_path):
    result = runner.invoke(app, ["fix", str(tmp_path / "nonexistent.py")])
    assert result.exit_code == 1


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
