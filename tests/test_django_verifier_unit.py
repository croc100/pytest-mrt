"""
Unit tests for DjangoRollbackVerifier — mocked runner and core dependencies.

All tests use a mock DjangoMigrationRunner so no real database or
Django installation is required.
"""

from __future__ import annotations

import unittest.mock as mock

import pytest

# ── helpers ───────────────────────────────────────────────────────────────


def _make_migration(app_label="myapp", name="0001_initial"):
    from pytest_mrt.adapters.django_runner import DjangoMigration

    return DjangoMigration(app_label=app_label, name=name)


@pytest.fixture
def mock_runner():
    runner = mock.MagicMock()
    runner.engine = mock.MagicMock()
    return runner


@pytest.fixture
def verifier(mock_runner):
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    return DjangoRollbackVerifier(mock_runner)


# ── check_migration — skip ────────────────────────────────────────────────


def test_check_migration_skipped(verifier):
    m = _make_migration()
    verifier.skip = {"myapp/0001_initial": "not reversible by design"}

    result = verifier.check_migration(m)

    assert result.skipped
    assert result.passed
    assert result.skip_reason == "not reversible by design"


# ── check_migration — pass / fail ─────────────────────────────────────────


def test_check_migration_passes(mock_runner):
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_snapshot = mock.MagicMock()
    mock_snapshot.tables = {}

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_snapshot),
        mock.patch.object(verifier, "_run_check", return_value=[]),
    ):
        result = verifier.check_migration(m)

    assert result.passed
    assert result.revision == "myapp/0001_initial"
    assert result.failures == []


def test_check_migration_fails(mock_runner):
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_snapshot = mock.MagicMock()
    mock_snapshot.tables = {}

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_snapshot),
        mock.patch.object(verifier, "_run_check", return_value=["Column 'x' was dropped"]),
    ):
        result = verifier.check_migration(m)

    assert not result.passed
    assert "Column 'x' was dropped" in result.failures


# ── check_migration — exception / recovery ───────────────────────────────


def test_check_migration_exception_triggers_recovery(mock_runner):
    """Exception in _run_check calls downgrade_app_zero for recovery."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_snapshot = mock.MagicMock()
    mock_snapshot.tables = {}

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_snapshot),
        mock.patch.object(verifier, "_run_check", side_effect=RuntimeError("boom")),
    ):
        result = verifier.check_migration(m)

    assert not result.passed
    assert any("RuntimeError" in f for f in result.failures)
    mock_runner.downgrade_app_zero.assert_called_once_with("myapp")


def test_check_migration_recovery_also_fails(mock_runner):
    """Both the original error and the recovery error appear in failures."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_snapshot = mock.MagicMock()
    mock_snapshot.tables = {}

    mock_runner.downgrade_app_zero.side_effect = RuntimeError("recovery failed")

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_snapshot),
        mock.patch.object(verifier, "_run_check", side_effect=RuntimeError("original")),
    ):
        result = verifier.check_migration(m)

    assert not result.passed
    assert any("recovery failed" in f for f in result.failures)


# ── check_migration — timeout ─────────────────────────────────────────────


def test_check_migration_timeout(mock_runner):
    """Timeout appends a descriptive message and the result is not passed."""
    from concurrent.futures import TimeoutError as FuturesTimeout

    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner, timeout=1)
    m = _make_migration()

    mock_snapshot = mock.MagicMock()
    mock_snapshot.tables = {}

    mock_future = mock.MagicMock()
    mock_future.result.side_effect = FuturesTimeout()

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_snapshot),
        mock.patch.object(verifier, "_build_seeder", return_value=mock.MagicMock()),
        mock.patch("pytest_mrt.adapters.django_verifier.ThreadPoolExecutor") as mock_pool,
    ):
        mock_pool.return_value.__enter__.return_value.submit.return_value = mock_future
        result = verifier.check_migration(m)

    assert not result.passed
    assert any("timed out" in f.lower() for f in result.failures)


# ── _run_check ────────────────────────────────────────────────────────────


def test_run_check_no_issues(mock_runner):
    """Returns empty list when schema is restored and data is intact."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaDiff, SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_schema = mock.MagicMock()
    mock_seeder = mock.MagicMock()
    mock_seeder.verify.return_value = []

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_schema),
        mock.patch.object(SchemaDiff, "verify_restored", return_value=[]),
    ):
        failures = verifier._run_check(m, mock_schema, mock_seeder)

    assert failures == []
    mock_runner.upgrade.assert_called_once_with("myapp", "0001_initial")
    mock_runner.downgrade.assert_called_once_with("myapp", "0001_initial")


def test_run_check_schema_issue(mock_runner):
    """Schema diff failures are included in the returned list."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaDiff, SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_schema = mock.MagicMock()
    mock_seeder = mock.MagicMock()
    mock_seeder.verify.return_value = []

    mock_issue = mock.MagicMock()
    mock_issue.message = "Table 'users' was dropped"

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_schema),
        mock.patch.object(SchemaDiff, "verify_restored", return_value=[mock_issue]),
    ):
        failures = verifier._run_check(m, mock_schema, mock_seeder)

    assert "Table 'users' was dropped" in failures


def test_run_check_data_issue(mock_runner):
    """Seeder verification failures are included in the returned list."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.schema import SchemaDiff, SchemaSnapshot

    verifier = DjangoRollbackVerifier(mock_runner)
    m = _make_migration()

    mock_schema = mock.MagicMock()
    mock_seeder = mock.MagicMock()
    mock_seeder.verify.return_value = ["Row id=1 was deleted from 'users'"]

    with (
        mock.patch.object(SchemaSnapshot, "capture", return_value=mock_schema),
        mock.patch.object(SchemaDiff, "verify_restored", return_value=[]),
    ):
        failures = verifier._run_check(m, mock_schema, mock_seeder)

    assert "Row id=1 was deleted from 'users'" in failures


# ── _build_seeder ─────────────────────────────────────────────────────────


def test_build_seeder_auto_seeds_table(mock_runner):
    """seed_table is called for tables without a custom seed function."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    verifier = DjangoRollbackVerifier(mock_runner)

    mock_table_info = mock.MagicMock()
    mock_schema = mock.MagicMock()
    mock_schema.tables = {"users": mock_table_info}

    with mock.patch("pytest_mrt.adapters.django_verifier.SmartSeeder") as mock_cls:
        mock_instance = mock.MagicMock()
        mock_cls.return_value = mock_instance
        verifier._build_seeder(mock_schema)

    mock_instance.seed_table.assert_called_once_with(mock_table_info)


def _setup_engine_quote(mock_runner):
    """Make engine.dialect.identifier_preparer.quote() return a quoted string."""
    mock_runner.engine.dialect.identifier_preparer.quote.side_effect = lambda n: f'"{n}"'


def test_build_seeder_custom_seed_appends_rows(mock_runner):
    """Custom seed rows are inserted and appended to seeder._rows."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    _setup_engine_quote(mock_runner)

    custom_rows = [{"id": 1, "name": "test"}]
    verifier = DjangoRollbackVerifier(
        mock_runner,
        custom_seeds={"users": lambda: custom_rows},
    )

    mock_table_info = mock.MagicMock()
    mock_table_info.pk_cols = ["id"]
    mock_schema = mock.MagicMock()
    mock_schema.tables = {"users": mock_table_info}

    mock_conn = mock.MagicMock()
    mock_runner.engine.begin.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_runner.engine.begin.return_value.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("pytest_mrt.adapters.django_verifier.SmartSeeder") as mock_cls:
        mock_instance = mock.MagicMock()
        mock_instance._rows = []
        mock_cls.return_value = mock_instance
        verifier._build_seeder(mock_schema)

    assert len(mock_instance._rows) == 1


def test_build_seeder_custom_seed_no_pk_cols(mock_runner):
    """When pk_cols is empty, 'id' is used as the default pk column."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    _setup_engine_quote(mock_runner)

    custom_rows = [{"id": 42, "val": "x"}]
    verifier = DjangoRollbackVerifier(
        mock_runner,
        custom_seeds={"items": lambda: custom_rows},
    )

    mock_table_info = mock.MagicMock()
    mock_table_info.pk_cols = []  # empty → fallback to "id"
    mock_schema = mock.MagicMock()
    mock_schema.tables = {"items": mock_table_info}

    mock_conn = mock.MagicMock()
    mock_runner.engine.begin.return_value.__enter__ = mock.MagicMock(return_value=mock_conn)
    mock_runner.engine.begin.return_value.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("pytest_mrt.adapters.django_verifier.SmartSeeder") as mock_cls:
        mock_instance = mock.MagicMock()
        mock_instance._rows = []
        mock_cls.return_value = mock_instance
        verifier._build_seeder(mock_schema)

    appended = mock_instance._rows[0]
    assert appended.pk_col == "id"


def test_build_seeder_custom_seed_insert_exception_is_swallowed(mock_runner):
    """INSERT failure during custom seeding does not propagate."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    _setup_engine_quote(mock_runner)

    custom_rows = [{"id": 1}]
    verifier = DjangoRollbackVerifier(
        mock_runner,
        custom_seeds={"users": lambda: custom_rows},
    )

    mock_table_info = mock.MagicMock()
    mock_table_info.pk_cols = ["id"]
    mock_schema = mock.MagicMock()
    mock_schema.tables = {"users": mock_table_info}

    # engine.begin() raises, simulating an INSERT failure
    mock_runner.engine.begin.side_effect = Exception("unique violation")

    with mock.patch("pytest_mrt.adapters.django_verifier.SmartSeeder") as mock_cls:
        mock_instance = mock.MagicMock()
        mock_instance._rows = []
        mock_cls.return_value = mock_instance
        # Should not raise
        verifier._build_seeder(mock_schema)


# ── check_all ─────────────────────────────────────────────────────────────


def test_check_all_empty(mock_runner):
    """check_all() returns [] immediately when no migrations are found."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    mock_runner.get_migrations.return_value = []
    verifier = DjangoRollbackVerifier(mock_runner)

    assert verifier.check_all() == []
    mock_runner.downgrade_app_zero.assert_not_called()


def test_check_all_rolls_apps_to_zero_first(mock_runner):
    """check_all() calls downgrade_app_zero once per discovered app."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.verifier import RevisionResult

    m1 = _make_migration(app_label="myapp", name="0001_initial")
    m2 = _make_migration(app_label="otherapp", name="0001_initial")
    mock_runner.get_migrations.return_value = [m1, m2]

    verifier = DjangoRollbackVerifier(mock_runner)
    mock_result = RevisionResult(revision="x", passed=True)

    with mock.patch.object(verifier, "check_migration", return_value=mock_result):
        verifier.check_all()

    called_apps = [c.args[0] for c in mock_runner.downgrade_app_zero.call_args_list]
    assert set(called_apps) == {"myapp", "otherapp"}


def test_check_all_returns_one_result_per_migration(mock_runner):
    """check_all() returns exactly one RevisionResult per migration."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.verifier import RevisionResult

    migrations = [_make_migration(name=f"000{i}_m") for i in range(3)]
    mock_runner.get_migrations.return_value = migrations

    verifier = DjangoRollbackVerifier(mock_runner)
    mock_result = RevisionResult(revision="x", passed=True)

    with mock.patch.object(verifier, "check_migration", return_value=mock_result):
        results = verifier.check_all()

    assert len(results) == 3


def test_check_all_chain_advance_failure_stops_early(mock_runner):
    """When advancing after a migration fails, remaining migrations are skipped."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier
    from pytest_mrt.core.verifier import RevisionResult

    m1 = _make_migration(name="0001_initial")
    m2 = _make_migration(name="0002_add")
    mock_runner.get_migrations.return_value = [m1, m2]
    mock_runner.upgrade.side_effect = RuntimeError("advance failed")

    verifier = DjangoRollbackVerifier(mock_runner)
    mock_result = RevisionResult(revision="myapp/0001_initial", passed=True)

    with mock.patch.object(verifier, "check_migration", return_value=mock_result):
        results = verifier.check_all()

    # check_migration result for m1 + chain-advance error (m2 never runs)
    assert len(results) == 2
    assert results[0].passed
    assert not results[1].passed
    assert "chain-advance" in results[1].revision
    assert "advance failed" in results[1].failures[0]
