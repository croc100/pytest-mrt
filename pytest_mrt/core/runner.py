from __future__ import annotations

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class MigrationRunner:
    def __init__(self, alembic_ini: str, db_url: str):
        self.db_url = db_url
        self.alembic_cfg = AlembicConfig(alembic_ini)
        self.alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        self.engine: Engine = create_engine(db_url)

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
