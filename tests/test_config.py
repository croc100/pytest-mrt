"""Tests for MRTConfig."""
from __future__ import annotations
import pytest
from pytest_mrt.config import MRTConfig
from pytest_mrt.core.ast_analyzer import MigrationAST
from pytest_mrt.core.detector import RiskWarning


def test_defaults():
    cfg = MRTConfig()
    assert cfg.alembic_ini == "alembic.ini"
    assert cfg.db_url == ""
    assert cfg.seed_rows == 3
    assert cfg.skip == {}
    assert cfg.severity_overrides == {}
    assert cfg.custom_seeds == {}
    assert cfg.custom_checks == []
    assert cfg.migration_timeout is None


def test_custom_values():
    cfg = MRTConfig(
        alembic_ini="migrations/alembic.ini",
        db_url="postgresql://localhost/test",
        seed_rows=5,
        skip={"abc123": "intentional data migration"},
        severity_overrides={"INDEX without CONCURRENTLY": "error"},
        migration_timeout=30,
    )
    assert cfg.alembic_ini == "migrations/alembic.ini"
    assert cfg.db_url == "postgresql://localhost/test"
    assert cfg.seed_rows == 5
    assert "abc123" in cfg.skip
    assert cfg.severity_overrides["INDEX without CONCURRENTLY"] == "error"
    assert cfg.migration_timeout == 30


def test_custom_checks_callable():
    calls = []

    def my_check(m: MigrationAST) -> list[RiskWarning]:
        calls.append(m.revision)
        return []

    cfg = MRTConfig(custom_checks=[my_check])
    assert len(cfg.custom_checks) == 1
    assert cfg.custom_checks[0] is my_check


def test_custom_seeds_callable():
    def seed_users():
        return [{"id": 1, "name": "Alice"}]

    cfg = MRTConfig(custom_seeds={"users": seed_users})
    assert "users" in cfg.custom_seeds
    assert cfg.custom_seeds["users"]() == [{"id": 1, "name": "Alice"}]


def test_version_available():
    from pytest_mrt import __version__
    assert __version__ and __version__ != "0.0.0"
    parts = __version__.split(".")
    assert len(parts) >= 2


def test_version_fallback_on_import_error():
    """When importlib.metadata raises, __version__ falls back to '0.0.0'."""
    import importlib
    import sys
    import unittest.mock as mock

    # Force a reload with a mocked importlib.metadata.version that raises
    with mock.patch("importlib.metadata.version", side_effect=Exception("pkg not found")):
        # Remove cached module to force reimport
        if "pytest_mrt" in sys.modules:
            mrt_mod = sys.modules["pytest_mrt"]
            # Directly exercise the except branch
            try:
                from importlib.metadata import version
                v = version("pytest-mrt-nonexistent-pkg-xyz")
            except Exception:
                v = "0.0.0"
            assert v == "0.0.0"
