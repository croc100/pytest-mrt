from __future__ import annotations
import pytest

from .config import MRTConfig
from .core.runner import MigrationRunner
from .core.seeder import SmartSeeder
from .core.verifier import RevisionResult, RollbackVerifier


class MRTFixture:
    def __init__(self, config: MRTConfig):
        self._runner = MigrationRunner(config.alembic_ini, config.db_url)
        self._seeder = SmartSeeder(self._runner.engine)
        self._verifier = RollbackVerifier(
            self._runner,
            skip=config.skip,
            custom_seeds=config.custom_seeds,
        )

    # ── migration control ──────────────────────────────────────────────

    def upgrade(self, revision: str = "head") -> None:
        self._runner.upgrade(revision)

    def downgrade(self, revision: str = "-1") -> None:
        self._runner.downgrade(revision)

    # ── manual seeding ────────────────────────────────────────────────

    def seed(self, table: str, rows: list[dict], pk_col: str = "id") -> None:
        from .core.schema import SchemaSnapshot
        snap = SchemaSnapshot.capture(self._runner.engine)
        if table in snap.tables:
            self._seeder.seed_table(snap.tables[table])
        else:
            raise ValueError(f"Table '{table}' not found in current schema")

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
            pytest.fail(f"Migration {revision} is not safely reversible:\n{result.failure_summary()}")

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
