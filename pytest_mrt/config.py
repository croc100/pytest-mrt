from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    pass

# Default model for `mrt explain`. Override via MRTConfig(explain_model=...).
DEFAULT_EXPLAIN_MODEL = "claude-opus-4-5"


@dataclass
class MRTConfig:
    alembic_ini: str = "alembic.ini"
    db_url: str = ""
    seed_rows: int = 3

    # Skip specific revisions with a documented reason.
    # Skipped revisions are not tested and shown separately in reports.
    # Example:
    #   skip={"abc123": "Intentional data migration. Reviewed 2024-01-15. See ADR-007."}
    skip: dict[str, str] = field(default_factory=dict)

    # Override severity of specific patterns.
    # Example:
    #   severity_overrides={"INDEX without CONCURRENTLY": "error"}
    severity_overrides: dict[str, str] = field(default_factory=dict)

    # Custom seed functions per table: {"table_name": callable() -> list[dict]}
    # Replaces auto-generated seed data for that table.
    # Example:
    #   custom_seeds={"users": lambda: [{"id": 1, "name": "Alice"}]}
    custom_seeds: dict[str, Callable[[], list[dict]]] = field(default_factory=dict)

    # Plugin API: register additional static analysis checks.
    # Each function receives a MigrationAST and returns list[RiskWarning].
    # These run in addition to the built-in checks, not instead of them.
    #
    # Example:
    #   def my_check(m: MigrationAST) -> list[RiskWarning]:
    #       if some_condition(m):
    #           return [RiskWarning(m.revision, m.filename,
    #                               "My pattern", "explanation", "warning")]
    #       return []
    #
    #   config = MRTConfig(custom_checks=[my_check])
    custom_checks: list[Callable] = field(default_factory=list)

    # Per-migration timeout in seconds. Migrations that exceed this limit are
    # marked as failed rather than blocking the test suite indefinitely.
    # Set to None to disable the timeout entirely.
    migration_timeout: int = 60

    # ── Django dynamic rollback ────────────────────────────────────────
    # Set django_settings to enable dynamic rollback testing for Django projects.
    # When set, the `mrt` fixture uses DjangoMigrationRunner instead of
    # MigrationRunner. alembic_ini is ignored in Django mode.
    #
    # Example:
    #   MRTConfig(
    #       db_url="sqlite:///test.db",
    #       django_settings="myproject.settings_test",
    #   )
    django_settings: str | None = None

    # Restrict dynamic testing to specific Django apps.
    # None = test all installed apps that have migrations.
    # Example: django_apps=["users", "orders"]
    django_apps: list[str] | None = None

    # Path to the Django project root. Added to sys.path before import.
    # Required if the project is not on the Python path already.
    django_project_dir: str | None = None

    # Rollback testing floor — skip revisions at or older than this point.
    # Alembic: revision ID (e.g. "abc123def456").
    # Django: app_label.migration_name (e.g. "myapp.0050_baseline").
    # None = test all revisions (default).
    minimum_downgrade_revision: str | None = None

    # Model used by `mrt explain`. Defaults to DEFAULT_EXPLAIN_MODEL.
    # Override to use a different Claude model, e.g. "claude-3-5-haiku-latest".
    explain_model: str = DEFAULT_EXPLAIN_MODEL

    # Import path for the SQLAlchemy declarative Base (or MetaData) used by
    # assert_schema_matches() and the built-in test_mrt_schema_matches_models test.
    # Format: "myapp.models:Base" or "myapp.models:Base.metadata"
    # Example: target_metadata="myproject.db.models:Base"
    target_metadata: str | None = None
