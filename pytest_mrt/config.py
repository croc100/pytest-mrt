from __future__ import annotations
from dataclasses import dataclass, field


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
    # If provided, replaces auto-generated seed data for that table.
    # Example:
    #   custom_seeds={"users": lambda: [{"id": 1, "name": "Alice"}]}
    custom_seeds: dict[str, object] = field(default_factory=dict)
