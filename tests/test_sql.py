"""Tests for identifier quoting in hand-built statements.

Every statement this package assembles as a string interpolates table and column
names. Unquoted, they break on reserved words, on mixed case under PostgreSQL,
and on MySQL, which quotes with backticks rather than double quotes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from pytest_mrt.core.schema import SchemaSnapshot
from pytest_mrt.core.seeder import SmartSeeder
from pytest_mrt.core.sql import quote_identifier


@pytest.fixture()
def engine():
    e = create_engine("sqlite://")
    yield e
    e.dispose()


def test_reserved_word_is_quoted(engine):
    assert quote_identifier(engine, "order") == '"order"'


def test_mixed_case_is_quoted(engine):
    assert quote_identifier(engine, "UserProfile") == '"UserProfile"'


def test_plain_name_is_left_alone(engine):
    assert quote_identifier(engine, "users") == "users"


def test_mysql_uses_backticks():
    """MySQL quotes with backticks — a double-quoted identifier is a string there."""
    from sqlalchemy.dialects import mysql

    class _MySQLEngine:
        dialect = mysql.dialect()

    assert quote_identifier(_MySQLEngine, "order") == "`order`"


def test_seeder_handles_reserved_word_table(engine):
    """A table named `order` must seed and verify like any other."""
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE "order" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                "select" TEXT NOT NULL
            )
        """)
        )

    snap = SchemaSnapshot.capture(engine)
    seeder = SmartSeeder(engine)
    seeder.seed_table(snap.tables["order"])

    with engine.connect() as conn:
        rows = conn.execute(text('SELECT * FROM "order"')).fetchall()
    assert len(rows) == 3
    assert seeder.verify() == []
