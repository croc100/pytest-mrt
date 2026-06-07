import textwrap
from pathlib import Path

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
    """Fires when upgrade has op.execute but downgrade does not."""
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("UPDATE users SET status = 'active'")
        def downgrade():
            op.add_column('users', sa.Column('status', sa.String))
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


# ── bug fixes ─────────────────────────────────────────────────────────

def test_raw_execute_no_false_positive_when_downgrade_also_has_execute(tmp_path):
    """If both upgrade and downgrade have op.execute, it's likely intentional."""
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("UPDATE users SET status = 'active'")
        def downgrade():
            op.execute("UPDATE users SET status = NULL")
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Raw SQL (op.execute)" not in patterns


def test_raw_execute_fires_when_downgrade_has_no_execute(tmp_path):
    """op.execute in upgrade with no corresponding execute in downgrade should warn."""
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("UPDATE users SET status = 'active'")
        def downgrade():
            op.drop_column('users', 'status')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Raw SQL (op.execute)" in patterns


# ── batch_alter_table ──────────────────────────────────────────────────

def test_batch_alter_drop_column(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            with op.batch_alter_table('users') as batch_op:
                batch_op.drop_column('phone')
        def downgrade():
            with op.batch_alter_table('users') as batch_op:
                batch_op.add_column(sa.Column('phone', sa.String(20)))
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP COLUMN in batch_alter_table" in patterns


def test_batch_alter_safe_operation_is_fine(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            with op.batch_alter_table('users') as batch_op:
                batch_op.add_column(sa.Column('bio', sa.Text, nullable=True))
        def downgrade():
            with op.batch_alter_table('users') as batch_op:
                batch_op.drop_column('bio')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP COLUMN in batch_alter_table" not in patterns


# ── multiple heads ─────────────────────────────────────────────────────

def test_multiple_heads_detected(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        def upgrade(): pass
        def downgrade(): pass
    """)
    migration(tmp_path, "002a.py", """
        revision = '002a'
        down_revision = '001'
        def upgrade(): pass
        def downgrade(): pass
    """)
    migration(tmp_path, "002b.py", """
        revision = '002b'
        down_revision = '001'
        def upgrade(): pass
        def downgrade(): pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Multiple heads" in patterns


def test_linear_history_no_multiple_heads(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        def upgrade(): pass
        def downgrade(): pass
    """)
    migration(tmp_path, "002.py", """
        revision = '002'
        down_revision = '001'
        def upgrade(): pass
        def downgrade(): pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Multiple heads" not in patterns


# ── new patterns ──────────────────────────────────────────────────────

def test_rename_table_without_reverse(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.rename_table('users', 'accounts')
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "rename_table without reverse" in patterns


def test_rename_table_with_reverse_is_fine(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.rename_table('users', 'accounts')
        def downgrade():
            op.rename_table('accounts', 'users')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "rename_table without reverse" not in patterns


def test_enum_value_added(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("ALTER TYPE user_status ADD VALUE 'suspended'")
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "ENUM value added" in patterns


def test_multi_step_destructive(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.add_column('users', sa.Column('full_name', sa.String))
            op.execute("UPDATE users SET full_name = first_name || ' ' || last_name")
            op.drop_column('users', 'first_name')
            op.drop_column('users', 'last_name')
        def downgrade():
            op.add_column('users', sa.Column('first_name', sa.String))
            op.add_column('users', sa.Column('last_name', sa.String))
            op.drop_column('users', 'full_name')
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "Multi-step destructive migration" in patterns


def test_drop_view_without_reverse(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("DROP VIEW active_users")
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP VIEW without reverse" in patterns


def test_drop_index_without_reverse(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.drop_index('ix_users_email', table_name='users')
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP INDEX without reverse" in patterns


def test_drop_index_with_reverse_is_fine(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.drop_index('ix_users_email', table_name='users')
        def downgrade():
            op.create_index('ix_users_email', 'users', ['email'])
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "DROP INDEX without reverse" not in patterns


def test_sequence_modification_warning(tmp_path):
    migration(tmp_path, "001.py", """
        revision = '001'
        def upgrade():
            op.execute("ALTER SEQUENCE users_id_seq RESTART WITH 1000")
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "SEQUENCE modification" in patterns


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


# ── Pattern 28: DROP FOREIGN KEY without restore ──────────────────────

def test_drop_fk_without_restore_detected(tmp_path):
    """op.drop_constraint(type_='foreignkey') without create_foreign_key in downgrade."""
    (tmp_path / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.drop_constraint('fk_posts_user', 'posts', type_='foreignkey')
        def downgrade():
            pass
    """))
    warnings = analyze_migrations(str(tmp_path))
    assert any(w.pattern == "DROP FOREIGN KEY without restore" for w in warnings)


def test_drop_fk_with_restore_is_safe(tmp_path):
    (tmp_path / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.drop_constraint('fk_posts_user', 'posts', type_='foreignkey')
        def downgrade():
            op.create_foreign_key('fk_posts_user', 'posts', 'users', ['user_id'], ['id'])
    """))
    warnings = analyze_migrations(str(tmp_path))
    assert not any(w.pattern == "DROP FOREIGN KEY without restore" for w in warnings)


# ── Pattern 29: CREATE TRIGGER without DROP TRIGGER ───────────────────

def test_create_trigger_without_drop_detected(tmp_path):
    (tmp_path / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute('CREATE TRIGGER update_ts BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION fn()')
        def downgrade():
            pass
    """))
    warnings = analyze_migrations(str(tmp_path))
    assert any(w.pattern == "CREATE TRIGGER without DROP TRIGGER" for w in warnings)


def test_create_trigger_with_drop_is_safe(tmp_path):
    (tmp_path / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute('CREATE TRIGGER update_ts BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION fn()')
        def downgrade():
            op.execute('DROP TRIGGER IF EXISTS update_ts ON users')
    """))
    warnings = analyze_migrations(str(tmp_path))
    assert not any(w.pattern == "CREATE TRIGGER without DROP TRIGGER" for w in warnings)


# ── Pattern 30: CREATE TYPE without DROP TYPE ─────────────────────────

def test_create_type_without_drop_detected(tmp_path):
    (tmp_path / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute("CREATE TYPE user_role AS ENUM ('admin', 'member')")
        def downgrade():
            pass
    """))
    warnings = analyze_migrations(str(tmp_path))
    assert any(w.pattern == "CREATE TYPE without DROP TYPE" for w in warnings)


def test_create_type_with_drop_is_safe(tmp_path):
    (tmp_path / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute("CREATE TYPE user_role AS ENUM ('admin', 'member')")
        def downgrade():
            op.execute('DROP TYPE IF EXISTS user_role')
    """))
    warnings = analyze_migrations(str(tmp_path))
    assert not any(w.pattern == "CREATE TYPE without DROP TYPE" for w in warnings)


# ── 추가 패턴 커버리지 ──────────────────────────────────────────────────

def test_not_null_nullable_restore_warning(tmp_path):
    """alter_column nullable=False in upgrade without nullable=True in downgrade."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.alter_column('users', 'email', nullable=False)
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "NOT NULL without reverting nullable" in patterns


def test_not_null_nullable_restore_safe_when_restored(tmp_path):
    """alter_column nullable=False with nullable=True in downgrade is safe."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.alter_column('users', 'email', nullable=False)
        def downgrade():
            op.alter_column('users', 'email', nullable=True)
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "NOT NULL without reverting nullable" not in patterns


def test_bulk_insert_no_reverse_warning(tmp_path):
    """op.bulk_insert() without DELETE in downgrade triggers warning."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.bulk_insert(sa.table('roles'), [{'id': 1, 'name': 'admin'}])
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "bulk_insert without reverse" in patterns


def test_bulk_insert_with_delete_is_safe(tmp_path):
    """op.bulk_insert() with op.execute('DELETE ...') in downgrade is safe."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        import sqlalchemy as sa
        def upgrade():
            op.bulk_insert(sa.table('roles'), [{'id': 1, 'name': 'admin'}])
        def downgrade():
            op.execute("DELETE FROM roles WHERE id = 1")
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "bulk_insert without reverse" not in patterns


def test_not_null_raw_sql_warning(tmp_path):
    """Raw SQL SET NOT NULL without DROP NOT NULL in downgrade triggers warning."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute('ALTER TABLE users ALTER COLUMN email SET NOT NULL')
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "NOT NULL via raw SQL without reverse" in patterns


def test_context_execute_warning(tmp_path):
    """context.execute() in upgrade without reverse triggers warning."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        def upgrade():
            context.execute('UPDATE users SET active = 1')
        def downgrade():
            pass
    """)
    patterns = [w.pattern for w in analyze_migrations(str(tmp_path))]
    assert "context.execute without reverse" in patterns


def test_syntax_error_migration_reported(tmp_path):
    """A migration file with a syntax error is reported as an error."""
    (tmp_path / "001.py").write_text("def upgrade(: pass\n")  # invalid syntax
    warnings = analyze_migrations(str(tmp_path))
    assert any(w.pattern == "Syntax error" for w in warnings)
    assert any(w.severity == "error" for w in warnings)


def test_mrt_ignore_suppresses_warning(tmp_path):
    """# mrt: ignore on the same line suppresses that warning."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.drop_column('users', 'email')  # mrt: ignore
        def downgrade():
            op.add_column('users', 'email')
    """)
    warnings = analyze_migrations(str(tmp_path))
    assert not any(w.pattern == "DROP COLUMN in upgrade" for w in warnings)


def test_mrt_ignore_only_suppresses_annotated_line(tmp_path):
    """# mrt: ignore on one line does not suppress warnings on other lines."""
    migration(tmp_path, "001.py", """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.drop_column('users', 'email')  # mrt: ignore
            op.drop_column('users', 'phone')
        def downgrade():
            op.add_column('users', 'email')
            op.add_column('users', 'phone')
    """)
    warnings = analyze_migrations(str(tmp_path))
    drop_warnings = [w for w in warnings if w.pattern == "DROP COLUMN in upgrade"]
    assert len(drop_warnings) == 1
    assert "phone" in drop_warnings[0].message
