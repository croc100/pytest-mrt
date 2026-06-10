"""Tests for rolling-deploy compatibility checks (MRT7xx)."""

from __future__ import annotations

import pytest

from pytest_mrt.core.ast_analyzer import MigrationAST
from pytest_mrt.core.compat import analyze_compat

# ── fixtures ──────────────────────────────────────────────────────────────────

DROP_COL = """
revision = "a001"
def upgrade():
    op.drop_column("users", "email")
def downgrade():
    op.add_column("users", sa.Column("email", sa.String()))
"""

DROP_TABLE = """
revision = "a002"
def upgrade():
    op.drop_table("legacy_tokens")
def downgrade():
    op.create_table("legacy_tokens", sa.Column("id", sa.Integer()))
"""

RENAME_COL = """
revision = "a003"
def upgrade():
    op.alter_column("users", "email", new_column_name="email_address")
def downgrade():
    op.alter_column("users", "email_address", new_column_name="email")
"""

NOT_NULL_NO_DEFAULT = """
revision = "a004"
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer(), nullable=False))
def downgrade():
    op.drop_column("users", "score")
"""

NOT_NULL_WITH_SERVER_DEFAULT = """
revision = "a005"
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer(), nullable=False, server_default="0"))
def downgrade():
    op.drop_column("users", "score")
"""

SAFE_NULLABLE = """
revision = "a006"
def upgrade():
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
def downgrade():
    op.drop_column("users", "bio")
"""

TYPE_CHANGE = """
revision = "a007"
def upgrade():
    op.alter_column("users", "age", type_=sa.BigInteger())
def downgrade():
    op.alter_column("users", "age", type_=sa.Integer())
"""

SUPPRESSED = """
revision = "a008"
def upgrade():
    op.drop_column("users", "email")  # noqa: MRT701
def downgrade():
    op.add_column("users", sa.Column("email", sa.String()))
"""


def _codes(source: str, rev: str = "aXXX") -> list[str]:
    m = MigrationAST(source, rev, "test.py")
    return [w.code for w in analyze_compat(m)]


# ── MRT701 ───────────────────────────────────────────────────────────────────


def test_drop_column_flagged_mrt701():
    assert "MRT701" in _codes(DROP_COL)


def test_drop_column_suppressed():
    assert "MRT701" not in _codes(SUPPRESSED)


# ── MRT702 ───────────────────────────────────────────────────────────────────


def test_rename_column_flagged_mrt702():
    assert "MRT702" in _codes(RENAME_COL)


# ── MRT703 ───────────────────────────────────────────────────────────────────


def test_drop_table_flagged_mrt703():
    assert "MRT703" in _codes(DROP_TABLE)


# ── MRT704 ───────────────────────────────────────────────────────────────────


def test_not_null_no_default_flagged_mrt704():
    assert "MRT704" in _codes(NOT_NULL_NO_DEFAULT)


def test_not_null_with_server_default_not_flagged():
    assert "MRT704" not in _codes(NOT_NULL_WITH_SERVER_DEFAULT)


def test_nullable_column_not_flagged():
    assert not _codes(SAFE_NULLABLE)


# ── MRT705 ───────────────────────────────────────────────────────────────────


def test_type_change_flagged_mrt705():
    assert "MRT705" in _codes(TYPE_CHANGE)
