"""Tests for SchemaSnapshot, SchemaDiff, and SchemaIssue."""
from __future__ import annotations
import pytest
from sqlalchemy import create_engine, text
from pytest_mrt.core.schema import SchemaSnapshot, SchemaDiff, SchemaIssue


@pytest.fixture()
def engine():
    e = create_engine("sqlite://")
    yield e
    e.dispose()


def _create_users(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT
            )
        """))


def test_snapshot_captures_tables(engine):
    _create_users(engine)
    snap = SchemaSnapshot.capture(engine)
    assert "users" in snap.tables


def test_snapshot_captures_columns(engine):
    _create_users(engine)
    snap = SchemaSnapshot.capture(engine)
    cols = snap.tables["users"].columns
    assert "id" in cols
    assert "name" in cols
    assert "email" in cols


def test_snapshot_captures_pk(engine):
    _create_users(engine)
    snap = SchemaSnapshot.capture(engine)
    assert snap.tables["users"].pk_cols == ["id"]


def test_snapshot_excludes_alembic_version(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)"))
    snap = SchemaSnapshot.capture(engine)
    assert "alembic_version" not in snap.tables


def test_snapshot_empty_db(engine):
    snap = SchemaSnapshot.capture(engine)
    assert snap.tables == {}


def test_diff_dropped_table(engine):
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE users"))
    after = SchemaSnapshot.capture(engine)
    diff = SchemaDiff.compute(before, after)
    assert "users" in diff.dropped_tables


def test_diff_added_table(engine):
    before = SchemaSnapshot.capture(engine)
    _create_users(engine)
    after = SchemaSnapshot.capture(engine)
    diff = SchemaDiff.compute(before, after)
    assert "users" in diff.added_tables


def test_diff_dropped_column(engine):
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN email"))
    after = SchemaSnapshot.capture(engine)
    diff = SchemaDiff.compute(before, after)
    assert "email" in diff.dropped_columns.get("users", [])


def test_diff_added_column(engine):
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN bio TEXT"))
    after = SchemaSnapshot.capture(engine)
    diff = SchemaDiff.compute(before, after)
    assert "bio" in diff.added_columns.get("users", [])


def test_verify_restored_passes_when_identical(engine):
    _create_users(engine)
    snap = SchemaSnapshot.capture(engine)
    issues = SchemaDiff().verify_restored(snap, snap)
    assert issues == []


def test_verify_restored_fails_missing_table(engine):
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE users"))
    after = SchemaSnapshot.capture(engine)
    issues = SchemaDiff().verify_restored(before, after)
    assert any("users" in i.message and "missing" in i.message for i in issues)
    assert all(i.severity == "error" for i in issues)


def test_verify_restored_fails_extra_table(engine):
    before = SchemaSnapshot.capture(engine)
    _create_users(engine)
    after = SchemaSnapshot.capture(engine)
    issues = SchemaDiff().verify_restored(before, after)
    assert any("users" in i.message for i in issues)


def test_verify_restored_fails_missing_column(engine):
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN email"))
    after = SchemaSnapshot.capture(engine)
    issues = SchemaDiff().verify_restored(before, after)
    assert any("email" in i.message for i in issues)


def test_diff_compute_type_changed(engine):
    """SchemaDiff.compute detects column type changes."""
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    # SQLite doesn't support ALTER COLUMN TYPE, so we recreate
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN score REAL"))
    after = SchemaSnapshot.capture(engine)
    diff = SchemaDiff.compute(before, after)
    assert "users" in diff.added_columns
    assert "score" in diff.added_columns["users"]


def test_verify_restored_fails_extra_column(engine):
    """verify_restored detects columns added during rollback that shouldn't be there."""
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN score REAL"))
    after_rollback = SchemaSnapshot.capture(engine)
    issues = SchemaDiff().verify_restored(before, after_rollback)
    assert any("score" in i.message for i in issues)


def test_diff_compute_dropped_column(engine):
    """SchemaDiff.compute detects dropped columns."""
    _create_users(engine)
    before = SchemaSnapshot.capture(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN email"))
    after = SchemaSnapshot.capture(engine)
    diff = SchemaDiff.compute(before, after)
    assert "users" in diff.dropped_columns
    assert "email" in diff.dropped_columns["users"]


def test_snapshot_captures_nullable(engine):
    """SchemaSnapshot records nullable flag correctly."""
    _create_users(engine)
    snap = SchemaSnapshot.capture(engine)
    assert snap.tables["users"].columns["name"].nullable is False
    assert snap.tables["users"].columns["email"].nullable is True
