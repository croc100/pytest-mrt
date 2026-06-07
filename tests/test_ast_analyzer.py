"""Tests for MigrationAST helper methods in ast_analyzer.py."""

from __future__ import annotations

import ast
import textwrap

from pytest_mrt.core.ast_analyzer import MigrationAST


def _ast(source: str) -> MigrationAST:
    return MigrationAST(textwrap.dedent(source).lstrip(), "001", "001.py")


# ── module_var ────────────────────────────────────────────────────────


def test_module_var_string():
    m = _ast("""
        revision = '001'
        def upgrade(): pass
        def downgrade(): pass
    """)
    assert m.module_var("revision") == "001"


def test_module_var_tuple():
    """down_revision = ('a', 'b') returns comma-joined string."""
    m = _ast("""
        revision = '003'
        down_revision = ('001', '002')
        def upgrade(): pass
        def downgrade(): pass
    """)
    result = m.module_var("down_revision")
    assert result == "001,002"


def test_module_var_missing_returns_none():
    m = _ast("""
        def upgrade(): pass
        def downgrade(): pass
    """)
    assert m.module_var("revision") is None


# ── parse error ───────────────────────────────────────────────────────


def test_parse_error_sets_flag():
    m = MigrationAST("def upgrade(: pass\n", "001", "001.py")
    assert m._parse_error is not None


# ── is_noop ───────────────────────────────────────────────────────────


def test_is_noop_with_pass():
    m = _ast("""
        revision = '001'
        def upgrade(): pass
        def downgrade(): pass
    """)
    assert m.is_noop(m.downgrade_fn) is True


def test_is_noop_with_real_call():
    m = _ast("""
        revision = '001'
        from alembic import op
        def upgrade():
            op.create_table('x')
        def downgrade():
            op.drop_table('x')
    """)
    assert m.is_noop(m.downgrade_fn) is False


def test_is_noop_with_none():
    m = _ast("""
        revision = '001'
        def upgrade(): pass
    """)
    assert m.is_noop(None) is True


# ── str_arg ───────────────────────────────────────────────────────────


def test_str_arg_returns_string():
    tree = ast.parse("op.drop_table('users')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.str_arg(call, 0) == "users"


def test_str_arg_out_of_range_returns_none():
    tree = ast.parse("op.drop_table('users')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.str_arg(call, 5) is None


def test_str_arg_non_constant_returns_none():
    tree = ast.parse("op.drop_table(my_var)")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.str_arg(call, 0) is None


# ── has_kwarg ─────────────────────────────────────────────────────────


def test_has_kwarg_true():
    tree = ast.parse("op.alter_column('t', 'c', nullable=False)")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.has_kwarg(call, "nullable") is True


def test_has_kwarg_false():
    tree = ast.parse("op.alter_column('t', 'c')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.has_kwarg(call, "nullable") is False


# ── kwarg_str ─────────────────────────────────────────────────────────


def test_kwarg_str_returns_value():
    tree = ast.parse("op.create_index('ix', 'users', schema='public')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.kwarg_str(call, "schema") == "public"


def test_kwarg_str_missing_returns_none():
    tree = ast.parse("op.create_index('ix', 'users')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.kwarg_str(call, "schema") is None


# ── kwarg_bool ────────────────────────────────────────────────────────


def test_kwarg_bool_true():
    tree = ast.parse("op.alter_column('t', 'c', nullable=True)")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.kwarg_bool(call, "nullable") is True


def test_kwarg_bool_false():
    tree = ast.parse("op.alter_column('t', 'c', nullable=False)")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.kwarg_bool(call, "nullable") is False


def test_kwarg_bool_non_bool_returns_none():
    tree = ast.parse("op.alter_column('t', 'c', server_default='now()')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.kwarg_bool(call, "server_default") is None


def test_kwarg_bool_missing_returns_none():
    tree = ast.parse("op.alter_column('t', 'c')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.kwarg_bool(call, "nullable") is None


# ── sql_content ───────────────────────────────────────────────────────


def test_sql_content_plain_string():
    tree = ast.parse("op.execute('SELECT 1')")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.sql_content(call) == "SELECT 1"


def test_sql_content_sa_text():
    tree = ast.parse("op.execute(sa.text('SELECT 1'))")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    outer = calls[0]  # op.execute(...)
    assert MigrationAST.sql_content(outer) == "SELECT 1"


def test_sql_content_no_args():
    tree = ast.parse("op.execute()")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert MigrationAST.sql_content(call) == ""


# ── find_column_calls ─────────────────────────────────────────────────


def test_find_column_calls_sa_column():
    tree = ast.parse("op.create_table('t', sa.Column('id', sa.Integer, primary_key=True))")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    outer = calls[0]
    cols = MigrationAST.find_column_calls(outer)
    assert len(cols) >= 1


def test_find_column_calls_bare_column():
    tree = ast.parse("op.create_table('t', Column('id', Integer, primary_key=True))")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    outer = calls[0]
    cols = MigrationAST.find_column_calls(outer)
    assert len(cols) >= 1


# ── upgrade_methods / downgrade_methods ───────────────────────────────


def test_upgrade_methods_returns_set():
    m = _ast("""
        revision = '001'
        from alembic import op
        def upgrade():
            op.create_table('t')
            op.add_column('t', None)
        def downgrade():
            op.drop_table('t')
    """)
    assert "create_table" in m.upgrade_methods()
    assert "add_column" in m.upgrade_methods()
    assert "drop_table" in m.downgrade_methods()


# ── nested function not counted ───────────────────────────────────────


def test_nested_function_calls_not_attributed_to_upgrade(tmp_path):
    """Calls inside a nested def inside upgrade() should not appear in upgrade_calls."""
    m = _ast("""
        revision = '001'
        from alembic import op
        def upgrade():
            def helper():
                op.drop_table('secret')
            helper()
        def downgrade():
            pass
    """)
    methods = m.upgrade_methods()
    assert "drop_table" not in methods
