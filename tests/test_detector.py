import textwrap
from pathlib import Path
import pytest
from pytest_mrt.core.detector import analyze_migrations


def migration(tmp_path: Path, name: str, content: str) -> None:
    (tmp_path / name).write_text(textwrap.dedent(content))


# ── errors ────────────────────────────────────────────────────────────

def test_missing_downgrade(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('x', sa.String))
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Missing downgrade" in patterns


def test_noop_downgrade(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('x', sa.String))
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "No-op downgrade" in patterns


def test_drop_column_in_upgrade(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.drop_column('users', 'email')
        def downgrade():
            op.add_column('users', sa.Column('email', sa.String))
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP COLUMN in upgrade" in patterns


def test_drop_column_in_downgrade_is_fine(tmp_path):
    """DROP COLUMN inside downgrade() is expected — not a warning."""
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('email', sa.String))
        def downgrade():
            op.drop_column('users', 'email')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP COLUMN in upgrade" not in patterns


def test_drop_table_in_upgrade(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.drop_table('sessions')
        def downgrade():
            op.create_table('sessions', sa.Column('id', sa.Integer))
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP TABLE in upgrade" in patterns


def test_truncate_in_upgrade(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute('TRUNCATE TABLE logs')
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "TRUNCATE" in patterns


# ── warnings ──────────────────────────────────────────────────────────

def test_not_null_without_default(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('score', sa.Integer, nullable=False))
        def downgrade():
            op.drop_column('users', 'score')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "NOT NULL without default" in patterns


def test_not_null_with_server_default_is_fine(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('score', sa.Integer, nullable=False, server_default='0'))
        def downgrade():
            op.drop_column('users', 'score')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "NOT NULL without default" not in patterns


def test_raw_execute_warning(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("UPDATE users SET status = 'active'")
        def downgrade():
            op.execute("UPDATE users SET status = NULL")
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Raw SQL (op.execute)" in patterns


def test_data_transform_without_reverse(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("UPDATE users SET name = UPPER(name)")
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Data transform without reverse" in patterns


def test_index_without_concurrently(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.create_index('ix_users_email', 'users', ['email'])
        def downgrade():
            op.drop_index('ix_users_email')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "INDEX without CONCURRENTLY" in patterns


def test_index_with_concurrently_is_fine(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.create_index('ix_users_email', 'users', ['email'], postgresql_concurrently=True)
        def downgrade():
            op.drop_index('ix_users_email')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "INDEX without CONCURRENTLY" not in patterns


def test_unique_constraint_warning(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.create_unique_constraint('uq_users_email', 'users', ['email'])
        def downgrade():
            op.drop_constraint('uq_users_email', 'users')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "UNIQUE constraint on existing data" in patterns


def test_cascade_delete_warning(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('posts', sa.Column('user_id', sa.Integer,
                sa.ForeignKey('users.id', ondelete='CASCADE')))
        def downgrade():
            op.drop_column('posts', 'user_id')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "CASCADE DELETE" in patterns


def test_column_type_change_warning(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.alter_column('users', 'age', type_=sa.String(10))
        def downgrade():
            op.alter_column('users', 'age', type_=sa.Integer)
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Column type change" in patterns


# ── clean migration — no warnings ─────────────────────────────────────

def test_clean_migration_no_warnings(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('nickname', sa.String(64), nullable=True))
        def downgrade():
            op.drop_column('users', 'nickname')
    """)
    assert analyze_migrations(str(tmp_path)) == []


def test_severity_errors_are_errors(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.drop_column('users', 'email')
        def downgrade():
            op.add_column('users', sa.Column('email', sa.String))
    """)
    warnings = analyze_migrations(str(tmp_path))
    errors = [w for w in warnings if w.severity == "error"]
    assert len(errors) >= 1
