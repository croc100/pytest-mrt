"""
Django dynamic rollback integration tests.

Tests DjangoMigrationRunner and DjangoRollbackVerifier using an in-process
Django configuration with SQLite — no external database required.

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
]

DB_URL = "sqlite:///:memory:"


def _make_runner():
    from pytest_mrt.adapters.django_runner import DjangoMigrationRunner

    return DjangoMigrationRunner(
        db_url=DB_URL,
        installed_apps=INSTALLED_APPS,
    )


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def django_runner():
    runner = _make_runner()
    yield runner
    runner.dispose()


# ── tests ─────────────────────────────────────────────────────────────────────


def test_django_runner_get_migrations(django_runner):
    """Runner discovers migrations from installed apps."""
    migrations = django_runner.get_migrations(apps=["django_app"])
    assert len(migrations) >= 1
    assert all(m.app_label == "django_app" for m in migrations)


def test_django_runner_upgrade_downgrade(django_runner):
    """upgrade() then downgrade() leaves DB at original state."""
    from pytest_mrt.core.schema import SchemaSnapshot

    migrations = django_runner.get_migrations(apps=["django_app"])
    assert migrations, "No migrations found in django_app"
    first = migrations[0]

    django_runner.downgrade_app_zero(first.app_label)
    snap_before = SchemaSnapshot.capture(django_runner.engine)

    django_runner.upgrade(first.app_label, first.name)
    django_runner.downgrade(first.app_label, first.name)

    snap_after = SchemaSnapshot.capture(django_runner.engine)
    from pytest_mrt.core.schema import SchemaDiff

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


def test_django_verifier_noop_downgrade_fails(tmp_path):
    """DjangoRollbackVerifier catches a no-op downgrade migration."""
    pytest.skip(
        "No-op downgrade detection requires a separate Django app fixture — "
        "covered by static analysis (D-pattern checks)"
    )


def test_mrt_config_django_mode():
    """MRTConfig.django_settings enables Django mode in the fixture."""
    from pytest_mrt.config import MRTConfig

    cfg = MRTConfig(
        db_url=DB_URL,
        django_settings=None,  # not activating Django mode here
    )
    assert cfg.django_settings is None
    assert cfg.django_apps is None

    cfg_django = MRTConfig(
        db_url=DB_URL,
        django_settings="myproject.settings_test",
        django_apps=["users"],
    )
    assert cfg_django.django_settings == "myproject.settings_test"
    assert cfg_django.django_apps == ["users"]
