"""Tests for the automatic downgrade() fix generator."""

from __future__ import annotations

import textwrap
from pathlib import Path

from pytest_mrt.core.fixer import apply_fix, generate_fix


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "migration.py"
    p.write_text(textwrap.dedent(content).lstrip())
    return str(p)


def test_no_fix_needed_when_downgrade_exists(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        def upgrade():
            op.create_table('users')
        def downgrade():
            op.drop_table('users')
    """,
    )
    assert generate_fix(path) is None


def test_fix_missing_downgrade(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        def upgrade():
            op.create_table('users')
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert fix.issue == "Missing downgrade()"
    assert 'drop_table("users")' in fix.suggested_downgrade


def test_fix_noop_downgrade(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        def upgrade():
            op.create_table('events')
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert fix.issue == "No-op downgrade()"
    assert 'drop_table("events")' in fix.suggested_downgrade


def test_fix_add_column(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.add_column('users', sa.Column('bio', sa.Text))
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert 'drop_column("users", "bio")' in fix.suggested_downgrade


def test_fix_create_index(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        from alembic import op
        def upgrade():
            op.create_index('ix_users_email', 'users', ['email'])
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert 'drop_index("ix_users_email"' in fix.suggested_downgrade


def test_fix_rename_table(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        from alembic import op
        def upgrade():
            op.rename_table('old_users', 'users')
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert 'rename_table("users", "old_users")' in fix.suggested_downgrade


def test_fix_confidence_high(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.create_table('logs', sa.Column('id', sa.Integer, primary_key=True))
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix.confidence == "high"


def test_fix_confidence_low_when_no_ops(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        from alembic import op
        def upgrade():
            op.execute('SOME CUSTOM SQL')
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert fix.confidence == "low"


def test_apply_fix_writes_file(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.create_table('items')
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    apply_fix(path, fix)
    content = Path(path).read_text()
    assert "def downgrade" in content
    assert 'drop_table("items")' in content


def test_apply_fix_replaces_noop(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.create_table('items')
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    apply_fix(path, fix)
    content = Path(path).read_text()
    assert 'drop_table("items")' in content


def test_fix_warning_on_destructive_reverse(tmp_path):
    path = _write(
        tmp_path,
        """
        revision = 'abc'
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.add_column('users', sa.Column('phone', sa.String(20)))
        def downgrade():
            pass
    """,
    )
    fix = generate_fix(path)
    assert fix is not None
    assert fix.warning is not None
    assert "drop" in fix.warning.lower()
