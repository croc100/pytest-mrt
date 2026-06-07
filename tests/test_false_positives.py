"""
False-positive test suite.

Every test here asserts that a SAFE migration produces zero error-severity warnings.
This suite is the contract that pytest-mrt won't flag migrations that are actually correct.

When a new pattern is added to detector.py, add a corresponding safe case here.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pytest_mrt.core.detector import analyze_migrations


@pytest.fixture()
def versions_dir(tmp_path: Path) -> Path:
    v = tmp_path / "versions"
    v.mkdir()
    return v


def _write(versions_dir: Path, name: str, content: str) -> None:
    (versions_dir / name).write_text(textwrap.dedent(content).lstrip())


def _no_errors(versions_dir: Path) -> None:
    """Assert that analyzing versions_dir produces no error-severity warnings."""
    warnings = analyze_migrations(str(versions_dir))
    errors = [w for w in warnings if w.severity == "error"]
    assert errors == [], f"Expected zero errors but got {len(errors)}:\n" + "\n".join(
        f"  [{w.pattern}] {w.message}" for w in errors
    )


# ── Schema changes ────────────────────────────────────────────────────


def test_safe_create_and_drop_table(versions_dir):
    """CREATE TABLE in upgrade + DROP TABLE in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
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
    """,
    )
    _no_errors(versions_dir)


def test_safe_add_and_drop_nullable_column(versions_dir):
    """ADD COLUMN nullable + DROP COLUMN in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.add_column('users', sa.Column('bio', sa.Text, nullable=True))

        def downgrade():
            op.drop_column('users', 'bio')
    """,
    )
    _no_errors(versions_dir)


def test_safe_add_not_null_column_with_server_default(versions_dir):
    """ADD NOT NULL column with server_default = safe (data won't break)."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.add_column('users', sa.Column('status',
                sa.String(16), nullable=False, server_default='active'))

        def downgrade():
            op.drop_column('users', 'status')
    """,
    )
    _no_errors(versions_dir)


def test_safe_rename_table_with_reverse(versions_dir):
    """RENAME TABLE with correct reverse = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.rename_table('old_name', 'new_name')

        def downgrade():
            op.rename_table('new_name', 'old_name')
    """,
    )
    _no_errors(versions_dir)


def test_safe_rename_column_with_reverse(versions_dir):
    """RENAME COLUMN with correct reverse = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.alter_column('users', 'old_col', new_column_name='new_col')

        def downgrade():
            op.alter_column('users', 'new_col', new_column_name='old_col')
    """,
    )
    _no_errors(versions_dir)


def test_safe_create_and_drop_index(versions_dir):
    """CREATE INDEX + DROP INDEX in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.create_index('ix_users_email', 'users', ['email'])

        def downgrade():
            op.drop_index('ix_users_email', table_name='users')
    """,
    )
    _no_errors(versions_dir)


def test_safe_create_and_drop_unique_constraint(versions_dir):
    """CREATE UNIQUE CONSTRAINT on empty table + DROP in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.create_unique_constraint('uq_users_email', 'users', ['email'])

        def downgrade():
            op.drop_constraint('uq_users_email', 'users', type_='unique')
    """,
    )
    _no_errors(versions_dir)


def test_safe_create_and_drop_foreign_key(versions_dir):
    """CREATE FOREIGN KEY + DROP in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.create_foreign_key('fk_posts_user', 'posts', 'users', ['user_id'], ['id'])

        def downgrade():
            op.drop_constraint('fk_posts_user', 'posts', type_='foreignkey')
    """,
    )
    _no_errors(versions_dir)


def test_safe_drop_foreign_key_with_restore(versions_dir):
    """DROP FK in upgrade + CREATE FK in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.drop_constraint('fk_posts_user', 'posts', type_='foreignkey')

        def downgrade():
            op.create_foreign_key('fk_posts_user', 'posts', 'users', ['user_id'], ['id'])
    """,
    )
    _no_errors(versions_dir)


# ── Data migrations ───────────────────────────────────────────────────


def test_safe_data_migration_with_reverse(versions_dir):
    """op.execute() data migration with a proper reverse = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.execute("UPDATE users SET status = 'active' WHERE status IS NULL")

        def downgrade():
            op.execute("UPDATE users SET status = NULL WHERE status = 'active'")
    """,
    )
    _no_errors(versions_dir)


def test_safe_run_sql_with_reverse(versions_dir):
    """Plain execute SQL with matching downgrade execute = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.execute("INSERT INTO settings (key, value) VALUES ('maintenance', 'false')")

        def downgrade():
            op.execute("DELETE FROM settings WHERE key = 'maintenance'")
    """,
    )
    _no_errors(versions_dir)


# ── Batch operations (SQLite) ─────────────────────────────────────────


def test_safe_batch_alter_add_column(versions_dir):
    """batch_alter_table ADD COLUMN (no drop) = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            with op.batch_alter_table('users') as batch_op:
                batch_op.add_column(sa.Column('nickname', sa.String(64), nullable=True))

        def downgrade():
            with op.batch_alter_table('users') as batch_op:
                batch_op.drop_column('nickname')
    """,
    )
    _no_errors(versions_dir)


# ── Index patterns ────────────────────────────────────────────────────


def test_safe_concurrently_index(versions_dir):
    """CONCURRENTLY index via op.execute() with matching drop = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_email ON users (email)')

        def downgrade():
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_email')
    """,
    )
    _no_errors(versions_dir)


# ── Trigger patterns ──────────────────────────────────────────────────


def test_safe_create_trigger_with_drop(versions_dir):
    """CREATE TRIGGER in upgrade + DROP TRIGGER in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.execute('''
                CREATE TRIGGER update_timestamp
                BEFORE UPDATE ON users
                FOR EACH ROW EXECUTE FUNCTION update_updated_at()
            ''')

        def downgrade():
            op.execute('DROP TRIGGER IF EXISTS update_timestamp ON users')
    """,
    )
    _no_errors(versions_dir)


def test_safe_create_type_with_drop(versions_dir):
    """CREATE TYPE in upgrade + DROP TYPE in downgrade = safe."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.execute("CREATE TYPE user_role AS ENUM ('admin', 'member', 'viewer')")
            op.add_column('users',
                __import__('sqlalchemy').Column('role', __import__('sqlalchemy').Enum(
                    'admin', 'member', 'viewer', name='user_role'), nullable=True))

        def downgrade():
            op.drop_column('users', 'role')
            op.execute('DROP TYPE IF EXISTS user_role')
    """,
    )
    _no_errors(versions_dir)


# ── No-op noop-safe migrations ────────────────────────────────────────


def test_safe_empty_migration_both_pass(versions_dir):
    """Both upgrade() and downgrade() are pass — no-op migration = no error (noop check
    only fires when upgrade changes schema but downgrade does nothing)."""
    _write(
        versions_dir,
        "001.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        def upgrade():
            pass

        def downgrade():
            pass
    """,
    )
    # A fully no-op migration (upgrade=pass) does NOT trigger the noop_downgrade check
    warnings = analyze_migrations(str(versions_dir))
    noop_errors = [w for w in warnings if w.pattern == "noop downgrade" and w.severity == "error"]
    assert noop_errors == [], f"Unexpected noop error on truly empty migration: {noop_errors}"
