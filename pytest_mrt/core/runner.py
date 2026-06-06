from __future__ import annotations

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


class MigrationRunner:
    def __init__(self, alembic_ini: str, db_url: str):
        self.db_url = db_url
        self.alembic_cfg = AlembicConfig(alembic_ini)
        self.alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        # Check for env.py early and give a clear error for Django users
        try:
            script = ScriptDirectory.from_config(self.alembic_cfg)
            import os as _os

            env_py = _os.path.join(script.dir, "env.py")
            if not _os.path.exists(env_py):
                raise FileNotFoundError(
                    f"env.py not found in '{script.dir}'.\n\n"
                    "  This is required for Alembic dynamic verification.\n"
                    "  If you are using Django migrations, use django_settings instead:\n\n"
                    "    MRTConfig(\n"
                    "        db_url=os.environ['TEST_DATABASE_URL'],\n"
                    "        django_settings='myproject.settings_test',\n"
                    "    )\n\n"
                    "  See: https://croc100.github.io/pytest-mrt/quickstart/#django"
                )
        except Exception as exc:
            if "env.py" in str(exc) or "django_settings" in str(exc):
                raise
            # Other ScriptDirectory errors are caught later during actual migration runs
        # NullPool for SQLite: each connection is closed immediately after use,
        # preventing ResourceWarning from unclosed file handles in tests.
        from sqlalchemy.engine.url import make_url

        _dialect = make_url(db_url).drivername.split("+")[0]
        # Use NullPool for all dialects in test environments to prevent
        # connection leaks across migrations and ensure clean state.
        pool_cls = NullPool
        self.engine: Engine = create_engine(db_url, poolclass=pool_cls)

    def dispose(self) -> None:
        """Release all pooled connections."""
        self.engine.dispose()

    def upgrade(self, revision: str = "head") -> None:
        command.upgrade(self.alembic_cfg, revision)

    def downgrade(self, revision: str = "-1") -> None:
        command.downgrade(self.alembic_cfg, revision)

    def downgrade_base(self) -> None:
        command.downgrade(self.alembic_cfg, "base")

    def current_revision(self) -> str | None:
        from alembic.runtime.migration import MigrationContext

        with self.engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()

    def get_revisions(self) -> list:
        """All revisions in upgrade order (oldest → newest)."""
        script = ScriptDirectory.from_config(self.alembic_cfg)
        return list(reversed(list(script.walk_revisions("base", "heads"))))

    def get_versions_dir(self) -> str:
        script = ScriptDirectory.from_config(self.alembic_cfg)
        return script.dir
