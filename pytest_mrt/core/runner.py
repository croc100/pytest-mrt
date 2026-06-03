from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text


class MigrationRunner:
    def __init__(self, alembic_ini: str, db_url: str):
        self.db_url = db_url
        self.alembic_cfg = AlembicConfig(alembic_ini)
        self.alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        self.engine = create_engine(db_url)

    def upgrade(self, revision: str = "head") -> None:
        command.upgrade(self.alembic_cfg, revision)

    def downgrade(self, revision: str = "-1") -> None:
        command.downgrade(self.alembic_cfg, revision)

    def current_revision(self) -> str | None:
        from alembic.runtime.migration import MigrationContext
        with self.engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()

    def get_table_names(self) -> list[str]:
        from sqlalchemy import inspect
        with self.engine.connect() as conn:
            inspector = inspect(conn)
            return inspector.get_table_names()

    def count_rows(self, table: str) -> int:
        with self.engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            return result.scalar()

    def fetch_rows(self, table: str, pk_col: str, pk_vals: list) -> list[dict]:
        if not pk_vals:
            return []
        placeholders = ", ".join(f":v{i}" for i in range(len(pk_vals)))
        params = {f"v{i}": v for i, v in enumerate(pk_vals)}
        with self.engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT * FROM {table} WHERE {pk_col} IN ({placeholders})"),
                params,
            )
            return [dict(row._mapping) for row in result]
