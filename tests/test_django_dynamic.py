"""
Django dynamic rollback integration tests.

Tests DjangoMigrationRunner and DjangoRollbackVerifier using an in-process
Django configuration with a file-backed SQLite database — no external database
required, but Django must be installed.

Uses a named SQLite file (via tmp_path_factory) so that both Django's own
connection and SQLAlchemy's engine see the same database.  The :memory: URI
with NullPool would give each engine.connect() call a fresh, empty database,
making SchemaSnapshot comparisons meaningless.

Skipped automatically when Django is not installed.
"""

from __future__ import annotations

import pytest

django = pytest.importorskip("django", reason="Django not installed")


# ── minimal Django project setup ─────────────────────────────────────────────

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "tests.django_app",
    "tests.django_bad_app",
]


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def django_runner(tmp_path_factory):
    from pytest_mrt.adapters.django_runner import DjangoMigrationRunner

    db_path = tmp_path_factory.mktemp("django_db") / "test.db"
    db_url = f"sqlite:///{db_path}"

    runner = DjangoMigrationRunner(
        db_url=db_url,
        installed_apps=INSTALLED_APPS,
    )
    yield runner
    runner.dispose()


# ── tests ─────────────────────────────────────────────────────────────────────


def test_django_runner_get_migrations(django_runner):
    """Runner discovers migrations from installed apps."""
    migrations = django_runner.get_migrations(apps=["django_app"])
    assert len(migrations) >= 1
    assert all(m.app_label == "django_app" for m in migrations)


def test_django_runner_upgrade_downgrade(django_runner):
    """upgrade() then downgrade() leaves DB schema unchanged."""
    from pytest_mrt.core.schema import SchemaDiff, SchemaSnapshot

    migrations = django_runner.get_migrations(apps=["django_app"])
    assert migrations, "No migrations found in django_app"
    first = migrations[0]

    django_runner.downgrade_app_zero(first.app_label)
    snap_before = SchemaSnapshot.capture(django_runner.engine)

    django_runner.upgrade(first.app_label, first.name)
    django_runner.downgrade(first.app_label, first.name)

    snap_after = SchemaSnapshot.capture(django_runner.engine)
    issues = SchemaDiff().verify_restored(snap_before, snap_after)
    assert issues == [], [i.message for i in issues]


def test_django_verifier_check_all_pass(django_runner):
    """check_all() passes for a correctly reversible Django migration chain."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    verifier = DjangoRollbackVerifier(django_runner, timeout=30)
    results = verifier.check_all(apps=["django_app"])

    assert results, "No results — no migrations found"
    failed = [r for r in results if not r.passed]
    assert not failed, "\n".join(r.failure_summary() for r in failed)


def test_django_verifier_noop_downgrade_fails(django_runner):
    """DjangoRollbackVerifier detects a migration whose downgrade is a no-op."""
    from pytest_mrt.adapters.django_verifier import DjangoRollbackVerifier

    verifier = DjangoRollbackVerifier(django_runner, timeout=30)
    results = verifier.check_all(apps=["django_bad_app"])

    assert results, "No results — django_bad_app migration not found"
    # The first result must be a failure: schema drift (leaked table not dropped)
    first = results[0]
    assert not first.passed, (
        "Expected noop downgrade to be detected as a failure, but it passed"
    )
    assert any("leaked" in f.lower() or "still exists" in f.lower() for f in first.failures), (
        f"Expected 'still exists' schema error, got: {first.failures}"
    )


def test_mrt_config_django_mode():
    """MRTConfig.django_settings enables Django mode in the fixture."""
    from pytest_mrt.config import MRTConfig

    cfg = MRTConfig(
        db_url="sqlite:///test.db",
        django_settings=None,
    )
    assert cfg.django_settings is None
    assert cfg.django_apps is None

    cfg_django = MRTConfig(
        db_url="sqlite:///test.db",
        django_settings="myproject.settings_test",
        django_apps=["users"],
    )
    assert cfg_django.django_settings == "myproject.settings_test"
    assert cfg_django.django_apps == ["users"]
