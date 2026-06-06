from __future__ import annotations

from typing import Iterator

import pytest

from .config import MRTConfig
from .core.detector import RiskWarning, analyze_migrations
from .core.runner import MigrationRunner
from .core.schema import SchemaSnapshot
from .core.seeder import SmartSeeder
from .core.verifier import RevisionResult, RollbackVerifier
from .exceptions import MRTConfigError


def _auto_detect_django(config: MRTConfig) -> MRTConfig:
    """
    If django_settings is not set but DJANGO_SETTINGS_MODULE is in the environment
    and alembic.ini is absent, automatically switch to Django mode.
    Returns a (possibly updated) MRTConfig.
    """
    import os
    from pathlib import Path

    if config.django_settings is not None:
        return config  # already explicit

    env_settings = os.environ.get("DJANGO_SETTINGS_MODULE")
    if not env_settings:
        return config  # no Django env var

    alembic_missing = not Path(config.alembic_ini).exists()
    if not alembic_missing:
        return config  # alembic.ini exists → user probably wants Alembic mode

    try:
        import django  # noqa: F401
    except ImportError:
        return config  # Django not installed

    import warnings

    warnings.warn(
        f"pytest-mrt: DJANGO_SETTINGS_MODULE='{env_settings}' detected and alembic.ini "
        f"not found — automatically using Django mode. "
        f"To make this explicit, set django_settings='{env_settings}' in MRTConfig.",
        stacklevel=3,
    )

    from dataclasses import replace

    return replace(config, django_settings=env_settings)


class MRTFixture:
    def __init__(self, config: MRTConfig):
        config = _auto_detect_django(config)
        self._config = config
        self._django_mode = config.django_settings is not None

        if self._django_mode:
            from .adapters.django_runner import DjangoMigrationRunner
            from .adapters.django_verifier import DjangoRollbackVerifier

            self._django_runner = DjangoMigrationRunner(
                db_url=config.db_url,
                settings_module=config.django_settings,
                project_dir=config.django_project_dir,
            )
            self._django_verifier = DjangoRollbackVerifier(
                self._django_runner,
                skip=config.skip,
                custom_seeds=config.custom_seeds,
                timeout=config.migration_timeout,
            )
            # Expose engine for seeder compatibility
            self._runner = None  # type: ignore[assignment]
            self._seeder = SmartSeeder(self._django_runner.engine)
            self._verifier = None  # type: ignore[assignment]
        else:
            from pathlib import Path as _Path

            if not _Path(config.alembic_ini).exists():
                raise MRTConfigError(
                    f"\n\n  alembic.ini not found: '{config.alembic_ini}'\n\n"
                    "  If you are using Django migrations (not Alembic), use:\n\n"
                    "    config._mrt_config = MRTConfig(\n"
                    "        db_url=os.environ['TEST_DATABASE_URL'],\n"
                    "        django_settings='myproject.settings_test',\n"
                    "    )\n\n"
                    "  See: https://croc100.github.io/pytest-mrt/quickstart/#django"
                )

            self._runner = MigrationRunner(config.alembic_ini, config.db_url)
            self._seeder = SmartSeeder(self._runner.engine)
            self._verifier = RollbackVerifier(
                self._runner,
                skip=config.skip,
                custom_seeds=config.custom_seeds,
                timeout=config.migration_timeout,
            )
            self._django_runner = None  # type: ignore[assignment]
            self._django_verifier = None  # type: ignore[assignment]

    # ── migration control ──────────────────────────────────────────────

    def upgrade(self, revision: str = "head") -> None:
        self._runner.upgrade(revision)

    def downgrade(self, revision: str = "-1") -> None:
        self._runner.downgrade(revision)

    # ── manual seeding ────────────────────────────────────────────────

    def seed(self, table: str, rows: list[dict], pk_col: str = "id") -> None:
        snap = SchemaSnapshot.capture(self._runner.engine)
        if table in snap.tables:
            self._seeder.seed_table(snap.tables[table])
        else:
            raise ValueError(f"Table '{table}' not found in current schema")

    # ── static analysis ───────────────────────────────────────────────

    def check_static(self, versions_dir: str | None = None) -> list[RiskWarning]:
        """
        Run static analysis on the migration files.
        Includes built-in checks + any custom_checks registered in MRTConfig.
        severity_overrides from config are applied to the results.
        """
        if versions_dir is None:
            versions_dir = self._runner.get_versions_dir()

        warnings = analyze_migrations(versions_dir)

        # Apply custom checks
        if self._config.custom_checks:
            import re as _re
            from pathlib import Path

            from .core.ast_analyzer import MigrationAST

            for path in sorted(Path(versions_dir).glob("*.py")):
                source = path.read_text()
                m_rev = _re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
                revision = m_rev.group(1) if m_rev else path.stem
                m = MigrationAST(source, revision, path.name)
                if not m._parse_error:
                    for check_fn in self._config.custom_checks:
                        warnings.extend(check_fn(m))

        # Apply severity overrides
        if self._config.severity_overrides:
            for w in warnings:
                if w.pattern in self._config.severity_overrides:
                    w.severity = self._config.severity_overrides[w.pattern]

        return warnings

    def assert_no_static_errors(self, versions_dir: str | None = None) -> None:
        """Fail the test if static analysis finds any errors."""
        warnings = self.check_static(versions_dir)
        errors = [w for w in warnings if w.severity == "error"]
        if errors:
            lines = [f"  [{w.revision}] {w.pattern}: {w.message}" for w in errors]
            pytest.fail("Static analysis found unsafe migration patterns:\n" + "\n".join(lines))

    # ── assertions ────────────────────────────────────────────────────

    def assert_data_intact(self) -> None:
        failures = self._seeder.verify()
        if failures:
            pytest.fail("Rollback caused data loss:\n" + "\n".join(f"  - {f}" for f in failures))

    def check_revision(self, revision: str) -> RevisionResult:
        if self._django_mode:
            raise RuntimeError(
                "check_revision() is not available in Django mode. "
                "Use check_migration(app_label, migration_name) instead."
            )
        return self._verifier.check_revision(revision)

    def check_migration(self, app_label: str, migration_name: str) -> RevisionResult:
        """Django mode: check a single migration by app + name."""
        if not self._django_mode:
            raise RuntimeError(
                "check_migration() is only available in Django mode. "
                "Use check_revision() for Alembic projects."
            )
        from .adapters.django_runner import DjangoMigration

        return self._django_verifier.check_migration(
            DjangoMigration(app_label=app_label, name=migration_name)
        )

    def check_all(self, apps: list[str] | None = None) -> list[RevisionResult]:
        if self._django_mode:
            return self._django_verifier.check_all(apps=apps or self._config.django_apps)
        return self._verifier.check_all()

    def assert_reversible(self, revision: str = "head") -> None:
        if self._django_mode:
            raise RuntimeError(
                "assert_reversible() is not available in Django mode. "
                "Use assert_all_reversible() to test all Django migrations."
            )
        result = self._verifier.check_revision(revision)
        if not result.passed:
            pytest.fail(
                f"Migration {revision} is not safely reversible:\n{result.failure_summary()}"
            )

    def assert_all_reversible(self, apps: list[str] | None = None) -> None:
        from .reporter import print_check_all_summary

        if self._django_mode:
            results = self._django_verifier.check_all(apps=apps or self._config.django_apps)
        else:
            results = self._verifier.check_all()

        print_check_all_summary(results)
        failed = [r for r in results if not r.passed]
        if failed:
            lines = []
            for r in failed:
                lines.append(f"  revision {r.revision}:")
                lines.append(r.failure_summary())
            pytest.fail("Some migrations are not safely reversible:\n" + "\n".join(lines))

    def reset(self) -> None:
        self._seeder.reset()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "mrt: migration rollback test")


@pytest.fixture
def mrt(request: pytest.FixtureRequest) -> Iterator[MRTFixture]:
    cfg: MRTConfig = getattr(request.config, "_mrt_config", None) or MRTConfig()
    try:
        fixture = MRTFixture(cfg)
    except MRTConfigError as e:
        pytest.fail(str(e), pytrace=False)
    yield fixture
    fixture.reset()
