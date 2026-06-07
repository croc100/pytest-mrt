"""Tests for SmartSeeder, _generate_value, _normalize_for_compare, _topological_order."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from pytest_mrt.core.schema import ColumnInfo, TableInfo
from pytest_mrt.core.seeder import (
    SeededRow,
    SmartSeeder,
    _generate_value,
    _normalize_for_compare,
    _topological_order,
    _unique_seed,
)


@pytest.fixture()
def engine():
    e = create_engine("sqlite://")
    yield e
    e.dispose()


def _col(name: str, type_str: str, nullable: bool = False, pk: bool = False) -> ColumnInfo:
    return ColumnInfo(name=name, type_str=type_str, nullable=nullable, primary_key=pk)


# ── _unique_seed ──────────────────────────────────────────────────────


def test_unique_seed_is_positive():
    assert _unique_seed("col", 0) > 0


def test_unique_seed_is_stable():
    assert _unique_seed("email", 2) == _unique_seed("email", 2)


def test_unique_seed_differs_by_col():
    assert _unique_seed("name", 0) != _unique_seed("email", 0)


# ── _generate_value type coverage ────────────────────────────────────


def test_generate_bigint():
    col = _col("val", "BIGINT")
    v = _generate_value(col, 0)
    assert isinstance(v, int)


def test_generate_bigserial():
    col = _col("val", "BIGSERIAL")
    v = _generate_value(col, 0)
    assert isinstance(v, int)


def test_generate_smallint():
    col = _col("val", "SMALLINT")
    v = _generate_value(col, 0)
    assert isinstance(v, int)


def test_generate_mediumint():
    col = _col("val", "MEDIUMINT")
    v = _generate_value(col, 0)
    assert isinstance(v, int)


def test_generate_float():
    col = _col("val", "FLOAT")
    v = _generate_value(col, 0)
    assert isinstance(v, float)


def test_generate_double():
    col = _col("val", "DOUBLE")
    v = _generate_value(col, 0)
    assert isinstance(v, float)


def test_generate_numeric():
    col = _col("val", "NUMERIC")
    v = _generate_value(col, 0)
    assert isinstance(v, float)


def test_generate_decimal():
    col = _col("val", "DECIMAL")
    v = _generate_value(col, 0)
    assert isinstance(v, float)


def test_generate_bool():
    col = _col("val", "BOOLEAN")
    v0 = _generate_value(col, 0)
    v1 = _generate_value(col, 1)
    assert isinstance(v0, bool)
    assert v0 != v1


def test_generate_uuid():
    col = _col("val", "UUID")
    v = _generate_value(col, 0)
    assert isinstance(v, str)
    assert len(v) == 36


def test_generate_json():
    col = _col("val", "JSON")
    v = _generate_value(col, 0)
    assert "mrt" in v


def test_generate_jsonb():
    col = _col("val", "JSONB")
    v = _generate_value(col, 0)
    assert "mrt" in v


def test_generate_bytea():
    col = _col("val", "BYTEA")
    v = _generate_value(col, 0)
    assert isinstance(v, bytes)


def test_generate_blob():
    col = _col("val", "BLOB")
    v = _generate_value(col, 0)
    assert isinstance(v, bytes)


def test_generate_timestamp():
    col = _col("val", "TIMESTAMP")
    v = _generate_value(col, 0)
    assert isinstance(v, datetime)


def test_generate_datetime():
    col = _col("val", "DATETIME")
    v = _generate_value(col, 0)
    assert isinstance(v, datetime)


def test_generate_date():
    col = _col("val", "DATE")
    v = _generate_value(col, 0)
    assert isinstance(v, date)


def test_generate_time():
    col = _col("val", "TIME")
    v = _generate_value(col, 0)
    assert isinstance(v, time)


def test_generate_varchar_with_limit():
    col = _col("val", "VARCHAR(10)")
    v = _generate_value(col, 0)
    assert isinstance(v, str)
    assert len(v) <= 10


def test_generate_text():
    col = _col("val", "TEXT")
    v = _generate_value(col, 0)
    assert isinstance(v, str)


def test_generate_char():
    col = _col("val", "CHAR(5)")
    v = _generate_value(col, 0)
    assert isinstance(v, str)
    assert len(v) <= 5


def test_generate_clob():
    col = _col("val", "CLOB")
    v = _generate_value(col, 0)
    assert isinstance(v, str)


def test_generate_enum_with_values():
    col = _col("val", "ENUM")
    v = _generate_value(col, 0, enum_values=["a", "b", "c"])
    assert v in ["a", "b", "c"]


def test_generate_enum_without_values_returns_none():
    col = _col("val", "ENUM")
    v = _generate_value(col, 0, enum_values=None)
    assert v is None


def test_generate_unknown_type_returns_string():
    col = _col("val", "CUSTOMTYPE")
    v = _generate_value(col, 0)
    assert isinstance(v, str)


# ── _normalize_for_compare ────────────────────────────────────────────


def test_normalize_datetime_strips_tz():
    from datetime import timezone

    dt = datetime(2024, 1, 1, 12, 0, 0, 999, tzinfo=timezone.utc)
    norm = _normalize_for_compare(dt)
    assert norm.tzinfo is None
    assert norm.microsecond == 0


def test_normalize_decimal():
    d = Decimal("3.14")
    assert _normalize_for_compare(d) == float(d)


def test_normalize_memoryview():
    mv = memoryview(b"hello")
    assert _normalize_for_compare(mv) == b"hello"


def test_normalize_datetime_string():
    s = "2024-01-15T10:30:00"
    norm = _normalize_for_compare(s)
    assert isinstance(norm, datetime)


def test_normalize_non_datetime_string():
    s = "hello world"
    assert _normalize_for_compare(s) == s


def test_normalize_passthrough():
    assert _normalize_for_compare(42) == 42
    assert _normalize_for_compare(None) is None


# ── _topological_order ────────────────────────────────────────────────


def test_topological_order_no_fk():
    tables = {
        "a": TableInfo("a"),
        "b": TableInfo("b"),
    }
    order = _topological_order(tables)
    assert set(order) == {"a", "b"}


def test_topological_order_with_fk():
    tables = {
        "posts": TableInfo("posts", fk_tables=["users"]),
        "users": TableInfo("users"),
    }
    order = _topological_order(tables)
    assert order.index("users") < order.index("posts")


def test_topological_order_self_reference():
    tables = {
        "nodes": TableInfo("nodes", fk_tables=["nodes"]),
    }
    order = _topological_order(tables)
    assert "nodes" in order


def test_topological_order_mutual_fk_no_infinite_loop():
    """Circular FK between two tables must not loop infinitely."""
    tables = {
        "a": TableInfo("a", fk_tables=["b"]),
        "b": TableInfo("b", fk_tables=["a"]),
    }
    order = _topological_order(tables)
    assert set(order) == {"a", "b"}
    assert len(order) == 2


# ── SmartSeeder ───────────────────────────────────────────────────────


def test_seeder_seed_table_basic(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        )

    from pytest_mrt.core.schema import SchemaSnapshot

    snap = SchemaSnapshot.capture(engine)
    seeder = SmartSeeder(engine)
    seeder.seed_table(snap.tables["users"])

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM users")).fetchall()
    assert len(rows) == 3


def test_seeder_verify_passes_after_seed(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL
            )
        """)
        )

    from pytest_mrt.core.schema import SchemaSnapshot

    snap = SchemaSnapshot.capture(engine)
    seeder = SmartSeeder(engine)
    seeder.seed_table(snap.tables["items"])
    failures = seeder.verify()
    assert failures == []


def test_seeder_verify_detects_dropped_table(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg TEXT NOT NULL
            )
        """)
        )

    from pytest_mrt.core.schema import SchemaSnapshot

    snap = SchemaSnapshot.capture(engine)
    seeder = SmartSeeder(engine)
    seeder.seed_table(snap.tables["logs"])

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE logs"))

    failures = seeder.verify()
    assert any("logs" in f for f in failures)


def test_seeder_verify_detects_missing_row(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        )
        conn.execute(text("INSERT INTO events VALUES (1, 'first')"))

    seeder = SmartSeeder(engine)
    seeder._rows.append(SeededRow("events", "id", 1, {"id": 1, "name": "first"}))

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM events WHERE id = 1"))

    failures = seeder.verify()
    assert any("lost" in f for f in failures)


def test_seeder_verify_detects_changed_value(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                val TEXT NOT NULL
            )
        """)
        )
        conn.execute(text("INSERT INTO settings VALUES (1, 'original')"))

    seeder = SmartSeeder(engine)
    seeder._rows.append(SeededRow("settings", "id", 1, {"id": 1, "val": "original"}))

    with engine.begin() as conn:
        conn.execute(text("UPDATE settings SET val = 'changed' WHERE id = 1"))

    failures = seeder.verify()
    assert any("val" in f and "changed" in f for f in failures)


def test_seeder_reset_clears_rows(engine):
    seeder = SmartSeeder(engine)
    seeder._rows.append(SeededRow("t", "id", 1, {}))
    seeder.reset()
    assert seeder._rows == []


def test_seeder_seed_all(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE cats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        )

    from pytest_mrt.core.schema import SchemaSnapshot

    snap = SchemaSnapshot.capture(engine)
    seeder = SmartSeeder(engine)
    seeder.seed_all(snap.tables, count=2)

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM cats")).fetchall()
    assert len(rows) == 2


def test_seeder_table_without_pk_is_skipped(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE nopk (
                name TEXT NOT NULL
            )
        """)
        )

    seeder = SmartSeeder(engine)
    table = TableInfo(name="nopk")  # no pk_cols
    seeder.seed_table(table)
    assert seeder._rows == []


def test_seeder_skips_nullable_columns(engine):
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE notes (
                id INTEGER NOT NULL PRIMARY KEY,
                body TEXT
            )
        """)
        )

    from pytest_mrt.core.schema import SchemaSnapshot

    snap = SchemaSnapshot.capture(engine)
    seeder = SmartSeeder(engine)
    seeder.seed_table(snap.tables["notes"])

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM notes")).fetchall()
    assert len(rows) == 3
    # body is nullable, so it should be NULL in seeded rows
    assert all(row[1] is None for row in rows)


# ── SmartSeeder._is_auto_pk ───────────────────────────────────────────


def test_is_auto_pk_serial_type(engine):
    """SERIAL type string is recognised as auto-generated PK."""
    seeder = SmartSeeder(engine)
    col = ColumnInfo(name="id", type_str="SERIAL", nullable=False, primary_key=True)
    assert seeder._is_auto_pk(col) is True


def test_is_auto_pk_auto_increment_type(engine):
    """AUTO_INCREMENT (MySQL) is recognised as auto-generated PK."""
    seeder = SmartSeeder(engine)
    col = ColumnInfo(name="id", type_str="INT AUTO_INCREMENT", nullable=False, primary_key=True)
    assert seeder._is_auto_pk(col) is True


def test_is_auto_pk_nextval_default(engine):
    """Sequence-backed PK detected via nextval() in the column default."""
    seeder = SmartSeeder(engine)
    col = ColumnInfo(
        name="id",
        type_str="INTEGER",
        nullable=False,
        primary_key=True,
        default="nextval('items_id_seq'::regclass)",
    )
    assert seeder._is_auto_pk(col) is True


def test_is_auto_pk_plain_integer_is_not_auto(engine):
    """Plain INTEGER PK with no default is not auto-generated."""
    seeder = SmartSeeder(engine)
    col = ColumnInfo(name="id", type_str="INTEGER", nullable=False, primary_key=True)
    assert seeder._is_auto_pk(col) is False


def test_seed_table_skips_serial_pk_row(engine):
    """seed_table inserts nothing when the only non-nullable column is a SERIAL PK."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE only_serial (id INTEGER NOT NULL PRIMARY KEY)"))

    seeder = SmartSeeder(engine)
    # Construct TableInfo manually so type_str is SERIAL (as PG would reflect it)
    table = TableInfo(
        name="only_serial",
        columns={
            "id": ColumnInfo(name="id", type_str="SERIAL", nullable=False, primary_key=True),
        },
        pk_cols=["id"],
    )
    seeder.seed_table(table)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM only_serial")).scalar()
    assert count == 0
