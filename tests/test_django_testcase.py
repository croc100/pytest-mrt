"""
Unit tests for MRTTestCase — mocked runner and verifier, no real DB required.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock

import pytest


# ── helpers ───────────────────────────────────────────────────────────────


def _make_result(passed=True, failures=None):
    from pytest_mrt.core.verifier import RevisionResult

    return RevisionResult(
        revision="myapp/0010_target",
        passed=passed,
        failures=failures or [],
    )


def _make_testcase_class(db_url="sqlite:///test.db", migrate_from=None, migrate_to=None):
    """Return a concrete MRTTestCase subclass with the given config."""
    from pytest_mrt.django_testcase import MRTTestCase

    class ConcreteCase(MRTTestCase):
        pass

    ConcreteCase.db_url = db_url
    ConcreteCase.migrate_from = migrate_from or ("myapp", "0009_prev")
    ConcreteCase.migrate_to = migrate_to or ("myapp", "0010_target")
    return ConcreteCase


# ── setUpClass validation ─────────────────────────────────────────────────


def test_setup_raises_without_db_url():
    from pytest_mrt.django_testcase import MRTTestCase

    class NoDb(MRTTestCase):
        migrate_from = ("myapp", "0009_prev")
        migrate_to = ("myapp", "0010_target")

    with pytest.raises(RuntimeError, match="database URL"):
        with mock.patch.dict("os.environ", {}, clear=True):
            NoDb.setUpClass()


def test_setup_raises_without_migrate_attrs():
    from pytest_mrt.django_testcase import MRTTestCase

    class NoMigrate(MRTTestCase):
        db_url = "sqlite:///test.db"

    with pytest.raises(RuntimeError, match="migrate_from"):
        with (
            mock.patch(
                "pytest_mrt.adapters.django_runner.DjangoMigrationRunner.__init__",
                return_value=None,
            ),
        ):
            NoMigrate.setUpClass()


# ── assertRollbackSafe ────────────────────────────────────────────────────


def _setup_testcase_with_mocks(cls):
    """Attach mock _runner and _verifier directly — bypasses setUpClass."""
    runner = mock.MagicMock()
    runner.engine = mock.MagicMock()
    verifier = mock.MagicMock()
    cls._runner = runner
    cls._verifier = verifier
    return runner, verifier


def test_assert_rollback_safe_passes():
    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)
    verifier.check_migration.return_value = _make_result(passed=True)

    instance = Cls()
    instance.assertRollbackSafe()  # should not raise


def test_assert_rollback_safe_fails_with_message():
    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)
    verifier.check_migration.return_value = _make_result(
        passed=False,
        failures=["Table 'users': 3/3 rows lost after rollback"],
    )

    instance = Cls()
    with pytest.raises(AssertionError, match="3/3 rows lost"):
        instance.assertRollbackSafe()


def test_assert_rollback_safe_uses_migrate_to():
    from pytest_mrt.adapters.django_runner import DjangoMigration

    Cls = _make_testcase_class(
        migrate_from=("accounts", "0001_initial"),
        migrate_to=("accounts", "0002_add_email"),
    )
    runner, verifier = _setup_testcase_with_mocks(Cls)
    verifier.check_migration.return_value = _make_result(passed=True)

    instance = Cls()
    instance.assertRollbackSafe()

    called_migration = verifier.check_migration.call_args[0][0]
    assert called_migration.app_label == "accounts"
    assert called_migration.name == "0002_add_email"


# ── assertDataIntact ──────────────────────────────────────────────────────


def test_assert_data_intact_passes():
    from pytest_mrt.core.schema import SchemaSnapshot, SchemaDiff
    from pytest_mrt.core.seeder import SmartSeeder

    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock.MagicMock(tables={})),
        mock.patch.object(SchemaDiff, "verify_restored", return_value=[]),
        mock.patch("pytest_mrt.core.seeder.SmartSeeder", return_value=mock.MagicMock(verify=lambda: [])),
    ):
        instance = Cls()
        instance.assertDataIntact()  # should not raise

    runner.upgrade.assert_called_with(*Cls.migrate_to)
    runner.downgrade.assert_called_with(*Cls.migrate_to)


def test_assert_data_intact_fails_on_data_loss():
    from pytest_mrt.core.schema import SchemaSnapshot, SchemaDiff
    from pytest_mrt.core.seeder import SmartSeeder

    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)

    mock_seeder = mock.MagicMock()
    mock_seeder.verify.return_value = ["Table 'users': 2/3 rows lost after rollback"]

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock.MagicMock(tables={})),
        mock.patch.object(SchemaDiff, "verify_restored", return_value=[]),
        mock.patch("pytest_mrt.core.seeder.SmartSeeder", return_value=mock_seeder),
    ):
        instance = Cls()
        with pytest.raises(AssertionError, match="2/3 rows lost"):
            instance.assertDataIntact()


# ── setUp restores migrate_from state ─────────────────────────────────────


def test_setup_restores_migrate_from():
    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)

    instance = Cls()
    instance.setUp()

    runner.upgrade.assert_called_once_with(*Cls.migrate_from)


# ── tearDownClass rolls back ───────────────────────────────────────────────


def test_teardown_calls_downgrade_zero():
    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)

    Cls.tearDownClass()

    runner.downgrade_app_zero.assert_called_once_with(Cls.migrate_to[0])


def test_teardown_swallows_errors():
    Cls = _make_testcase_class()
    runner, verifier = _setup_testcase_with_mocks(Cls)
    runner.downgrade_app_zero.side_effect = RuntimeError("DB gone")

    Cls.tearDownClass()  # should not raise
