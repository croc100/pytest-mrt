from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .core.ast_analyzer import MigrationAST
    from .core.detector import RiskWarning


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
    # None = no timeout (default).
    migration_timeout: int | None = None
