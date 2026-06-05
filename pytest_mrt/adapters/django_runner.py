"""
Django migration runner.

Wraps Django's MigrationExecutor to provide upgrade/downgrade operations
compatible with pytest-mrt's RollbackVerifier interface.

Requirements:
    pip install django
    DJANGO_SETTINGS_MODULE must be set, or pass settings_module= directly.

The runner configures Django's DATABASES['default'] from the provided db_url,
so SQLAlchemy and Django share the same connection target.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


@dataclass
class DjangoMigration:
    app_label: str
    name: str

    @property
    def revision(self) -> str:
        return f"{self.app_label}/{self.name}"

    @property
    def filename(self) -> str:
        return f"{self.name}.py"


def _sqlalchemy_url_to_django_db(db_url: str) -> dict[str, Any]:
    """Convert a SQLAlchemy URL to a Django DATABASES entry."""
    from sqlalchemy.engine.url import make_url

    url = make_url(db_url)
    dialect = url.drivername.split("+")[0]

    engine_map = {
        "sqlite": "django.db.backends.sqlite3",
        "postgresql": "django.db.backends.postgresql",
        "mysql": "django.db.backends.mysql",
        "oracle": "django.db.backends.oracle",
        "mssql": "mssql",
    }
    backend = engine_map.get(dialect, f"django.db.backends.{dialect}")

    db: dict[str, Any] = {"ENGINE": backend}

    if dialect == "sqlite":
        db["NAME"] = url.database or ":memory:"
    else:
        if url.database:
            db["NAME"] = url.database
        if url.host:
            db["HOST"] = url.host
        if url.port:
            db["PORT"] = str(url.port)
        if url.username:
            db["USER"] = url.username
        if url.password:
            db["PASSWORD"] = str(url.password)

    return db


def _configure_django(
    db_url: str,
    settings_module: str | None,
    project_dir: str | None,
    installed_apps: list[str],
) -> None:
    """Minimal Django setup sufficient for migration execution."""
    try:
        import django
        from django.conf import settings as django_settings
    except ImportError as exc:
        raise ImportError(
            "Django is required for dynamic rollback verification. "
            "Install it with: pip install django"
        ) from exc

    if django_settings.configured:
        return

    if project_dir:
        sys.path.insert(0, str(project_dir))

    if settings_module:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
        django.setup()
        # Override the database URL so SQLAlchemy and Django share the same target
        from django.conf import settings as s

        s.DATABASES["default"].update(_sqlalchemy_url_to_django_db(db_url))
        return

    # Minimal in-process configuration (no settings module)
    db_config = _sqlalchemy_url_to_django_db(db_url)
    django_settings.configure(
        DATABASES={"default": db_config},
        INSTALLED_APPS=installed_apps,
        USE_TZ=False,
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    )
    django.setup()


class DjangoMigrationRunner:
    """
    Runs Django migrations programmatically.

    State contract: mirrors MigrationRunner.
      - upgrade(app, migration) applies the migration.
      - downgrade(app, migration) rolls back to just before that migration.
      - downgrade_app_zero(app) rolls the entire app back to zero state.
    """

    def __init__(
        self,
        db_url: str,
        *,
        settings_module: str | None = None,
        project_dir: str | None = None,
        installed_apps: list[str] | None = None,
    ):
        self.db_url = db_url
        _configure_django(
            db_url,
            settings_module=settings_module,
            project_dir=project_dir,
            installed_apps=installed_apps or [],
        )
        self.engine: Engine = create_engine(db_url, poolclass=NullPool)

    # ── migration execution ───────────────────────────────────────────

    def _executor(self):
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        conn = connections["default"]
        conn.ensure_connection()
        return MigrationExecutor(conn)

    def upgrade(self, app_label: str, migration_name: str) -> None:
        executor = self._executor()
        executor.migrate([(app_label, migration_name)])

    def downgrade(self, app_label: str, migration_name: str) -> None:
        """Roll back to just before migration_name within app_label."""
        executor = self._executor()
        loader = executor.loader
        key = (app_label, migration_name)
        graph = loader.graph

        # node_map holds MigrationNode objects which have .parents/.children
        node = graph.node_map.get(key)
        if node is None:
            raise KeyError(f"Migration not found: {app_label}/{migration_name}")

        same_app_parents = [p.key for p in node.parents if p.key[0] == app_label]

        if same_app_parents:
            target = [same_app_parents[0]]
        else:
            target = [(app_label, None)]

        executor.migrate(target)

    def downgrade_app_zero(self, app_label: str) -> None:
        executor = self._executor()
        executor.migrate([(app_label, None)])

    # ── introspection ─────────────────────────────────────────────────

    def get_migrations(self, apps: list[str] | None = None) -> list[DjangoMigration]:
        """Return all migrations in topological order (oldest first)."""
        executor = self._executor()
        graph = executor.loader.graph

        # Use forwards_plan on each leaf to get stable topological order
        seen: set[tuple[str, str]] = set()
        result: list[DjangoMigration] = []

        for leaf in graph.leaf_nodes():
            for key in graph.forwards_plan(leaf):
                if key not in seen:
                    seen.add(key)
                    if apps is None or key[0] in apps:
                        result.append(DjangoMigration(app_label=key[0], name=key[1]))

        return result

    def current_state(self) -> set[tuple[str, str]]:
        """Set of (app_label, migration_name) currently applied."""
        executor = self._executor()
        return set(executor.loader.applied_migrations.keys())

    def dispose(self) -> None:
        self.engine.dispose()
        from django.db import connections

        connections["default"].close()
