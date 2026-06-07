"""Unit tests for core/drift.py — load_metadata, compare_schema, describe_diff."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine


# ── load_metadata ────────────────────────────────────────────────────────────


def test_load_metadata_invalid_format_raises():
    from pytest_mrt.core.drift import load_metadata

    with pytest.raises(ValueError, match="Invalid metadata path"):
        load_metadata("myapp.models.Base")  # missing colon


def test_load_metadata_dotted_attr_raises():
    from pytest_mrt.core.drift import load_metadata

    with pytest.raises(ValueError, match="Dotted attribute"):
        load_metadata("myapp.models:Base.metadata")


def test_load_metadata_returns_metadata_from_base(tmp_path):
    from pytest_mrt.core.drift import load_metadata

    mod = ModuleType("_testmod_base")
    meta = sa.MetaData()

    class FakeBase:
        metadata = meta

    mod.FakeBase = FakeBase
    sys.modules["_testmod_base"] = mod
    try:
        result = load_metadata("_testmod_base:FakeBase")
        assert result is meta
    finally:
        del sys.modules["_testmod_base"]


def test_load_metadata_accepts_metadata_instance(tmp_path):
    from pytest_mrt.core.drift import load_metadata

    mod = ModuleType("_testmod_meta")
    meta = sa.MetaData()
    mod.meta = meta
    sys.modules["_testmod_meta"] = mod
    try:
        result = load_metadata("_testmod_meta:meta")
        assert result is meta
    finally:
        del sys.modules["_testmod_meta"]


# ── compare_schema ───────────────────────────────────────────────────────────


def test_compare_schema_no_diff_when_equal():
    from pytest_mrt.core.drift import compare_schema

    engine = create_engine("sqlite://")
    meta = sa.MetaData()
    sa.Table("users", meta, sa.Column("id", sa.Integer, primary_key=True))
    meta.create_all(engine)

    diffs = compare_schema(engine, meta)
    assert diffs == []
    engine.dispose()


def test_compare_schema_detects_missing_table():
    from pytest_mrt.core.drift import compare_schema

    engine = create_engine("sqlite://")
    # DB has no tables, but model has one
    meta = sa.MetaData()
    sa.Table("missing_table", meta, sa.Column("id", sa.Integer, primary_key=True))

    diffs = compare_schema(engine, meta)
    assert len(diffs) > 0
    engine.dispose()


def test_compare_schema_detects_extra_table():
    from pytest_mrt.core.drift import compare_schema

    engine = create_engine("sqlite://")
    # Create a table in DB that isn't in the model
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE orphan (id INTEGER PRIMARY KEY)"))

    meta = sa.MetaData()  # empty — no tables in model

    diffs = compare_schema(engine, meta)
    assert len(diffs) > 0
    engine.dispose()


# ── describe_diff ────────────────────────────────────────────────────────────


def test_describe_diff_add_table():
    from pytest_mrt.core.drift import describe_diff

    table = MagicMock()
    table.name = "users"
    diff = ("add_table", table)
    result = describe_diff(diff)
    assert "add table" in result and "users" in result


def test_describe_diff_remove_table():
    from pytest_mrt.core.drift import describe_diff

    table = MagicMock()
    table.name = "old_table"
    diff = ("remove_table", table)
    result = describe_diff(diff)
    assert "remove table" in result and "old_table" in result


def test_describe_diff_add_column():
    from pytest_mrt.core.drift import describe_diff

    col = MagicMock()
    col.name = "email"
    diff = ("add_column", None, "users", col)
    result = describe_diff(diff)
    assert "add column" in result and "users.email" in result


def test_describe_diff_remove_column():
    from pytest_mrt.core.drift import describe_diff

    col = MagicMock()
    col.name = "old_col"
    diff = ("remove_column", None, "users", col)
    result = describe_diff(diff)
    assert "remove column" in result and "users.old_col" in result


def test_describe_diff_modify_type():
    from pytest_mrt.core.drift import describe_diff

    diff = ("modify_type", None, "users", "age", sa.String(), sa.Integer())
    result = describe_diff(diff)
    assert "type mismatch" in result and "users.age" in result


def test_describe_diff_modify_nullable():
    from pytest_mrt.core.drift import describe_diff

    diff = ("modify_nullable", None, "users", "name", True, False)
    result = describe_diff(diff)
    assert "nullable mismatch" in result and "users.name" in result


def test_describe_diff_unknown_kind():
    from pytest_mrt.core.drift import describe_diff

    diff = ("unknown_op", "some_data")
    result = describe_diff(diff)
    assert "unknown_op" in result


def test_describe_diff_non_tuple():
    from pytest_mrt.core.drift import describe_diff

    result = describe_diff("not a tuple")
    assert "not a tuple" in result
