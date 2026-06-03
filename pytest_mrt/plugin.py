import pytest
from .config import MRTConfig
from .core.runner import MigrationRunner
from .core.verifier import RollbackVerifier


class MRTFixture:
    def __init__(self, config: MRTConfig):
        self._config = config
        self._runner = MigrationRunner(config.alembic_ini, config.db_url)
        self._verifier = RollbackVerifier(self._runner)

    def upgrade(self, revision: str = "head") -> None:
        self._runner.upgrade(revision)

    def downgrade(self, revision: str = "-1") -> None:
        self._runner.downgrade(revision)

    def seed(self, table: str, rows: list[dict], pk_col: str = "id") -> None:
        self._verifier.seed(table, rows, pk_col)

    def assert_data_intact(self) -> None:
        failures = self._verifier.verify()
        if failures:
            msg = "Rollback caused data loss:\n" + "\n".join(f"  - {f}" for f in failures)
            pytest.fail(msg)

    def assert_reversible(self, revision: str = "head") -> None:
        self.upgrade(revision)
        self.downgrade()
        self.assert_data_intact()

    def assert_all_reversible(self) -> None:
        self._runner.upgrade("head")
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(self._runner.alembic_cfg)
        revisions = list(script.walk_revisions())
        failures = []
        for rev in reversed(revisions):
            try:
                self._runner.upgrade(rev.revision)
                self._runner.downgrade("-1")
            except Exception as e:
                failures.append(f"{rev.revision}: {e}")
        if failures:
            pytest.fail("Some migrations are not reversible:\n" + "\n".join(f"  - {f}" for f in failures))


def pytest_configure(config):
    config.addinivalue_line("markers", "mrt: mark test as a migration rollback test")


@pytest.fixture
def mrt(request):
    marker = request.node.get_closest_marker("mrt")
    cfg = MRTConfig()

    mrt_config = getattr(request.config, "_mrt_config", None)
    if mrt_config:
        cfg = mrt_config

    fixture = MRTFixture(cfg)
    yield fixture
    fixture._verifier.reset()
