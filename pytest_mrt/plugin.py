from __future__ import annotations

import pytest

from .config import MRTConfig
from .core.detector import RiskWarning, analyze_migrations
from .core.runner import MigrationRunner
from .core.schema import SchemaSnapshot
from .core.seeder import SmartSeeder
from .core.verifier import RevisionResult, RollbackVerifier


class MRTFixture:
    def __init__(self, config: MRTConfig):
        self._config = config
        self._runner = MigrationRunner(config.alembic_ini, config.db_url)
        self._seeder = SmartSeeder(self._runner.engine)
        self._verifier = RollbackVerifier(
            self._runner,
            skip=config.skip,
            custom_seeds=config.custom_seeds,
            timeout=config.migration_timeout,
        )

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
        return self._verifier.check_revision(revision)

    def check_all(self) -> list[RevisionResult]:
        return self._verifier.check_all()

    def assert_reversible(self, revision: str = "head") -> None:
        result = self._verifier.check_revision(revision)
        if not result.passed:
            pytest.fail(
                f"Migration {revision} is not safely reversible:\n{result.failure_summary()}"
            )

    def assert_all_reversible(self) -> None:
        from .reporter import print_check_all_summary

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
def mrt(request: pytest.FixtureRequest) -> MRTFixture:
    cfg: MRTConfig = getattr(request.config, "_mrt_config", None) or MRTConfig()
    fixture = MRTFixture(cfg)
    yield fixture
    fixture.reset()
