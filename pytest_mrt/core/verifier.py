from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from .runner import MigrationRunner
from .schema import SchemaSnapshot, SchemaDiff
from .seeder import SmartSeeder, SeededRow


@dataclass
class RevisionResult:
    revision: str
    passed: bool
    skipped: bool = False
    skip_reason: str = ""
    failures: list[str] = field(default_factory=list)

    def failure_summary(self) -> str:
        return "\n".join(f"  - {f}" for f in self.failures)

    @property
    def risk_score(self) -> int:
        """0 = no failures. Each failure adds 25 points (max 100)."""
        return min(100, len(self.failures) * 25)


class RollbackVerifier:
    """
    For each revision:
      1. Seed real data into tables that exist BEFORE the migration
         (auto-generated or from custom_seeds)
      2. Upgrade → Downgrade
      3. Verify schema restored + data intact
    """

    def __init__(
        self,
        runner: MigrationRunner,
        skip: dict[str, str] | None = None,
        custom_seeds: dict[str, Callable[[], list[dict]]] | None = None,
    ):
        self.runner = runner
        self.skip = skip or {}
        self.custom_seeds = custom_seeds or {}

    def _reset_to(self, revision: str | None) -> None:
        self.runner.downgrade_base()
        if revision is not None:
            self.runner.upgrade(revision)

    def _build_seeder(self, schema: SchemaSnapshot) -> SmartSeeder:
        seeder = SmartSeeder(self.runner.engine)
        for tname, table_info in schema.tables.items():
            if tname in self.custom_seeds:
                rows = self.custom_seeds[tname]()
                pk_col = table_info.pk_cols[0] if table_info.pk_cols else "id"
                for row in rows:
                    seeder._rows.append(
                        SeededRow(table=tname, pk_col=pk_col, pk_val=row.get(pk_col), data=row)
                    )
                # Insert custom rows into DB
                from sqlalchemy import text
                for row in rows:
                    cols = ", ".join(f'"{c}"' for c in row)
                    placeholders = ", ".join(f":p_{c}" for c in row)
                    params = {f"p_{c}": v for c, v in row.items()}
                    try:
                        with self.runner.engine.begin() as conn:
                            conn.execute(
                                text(f'INSERT INTO "{tname}" ({cols}) VALUES ({placeholders})'),
                                params,
                            )
                    except Exception:
                        pass
            else:
                seeder.seed_table(table_info)
        return seeder

    def check_revision(self, revision: str) -> RevisionResult:
        if revision in self.skip:
            return RevisionResult(
                revision=revision, passed=True,
                skipped=True, skip_reason=self.skip[revision],
            )

        failures: list[str] = []
        schema_before = SchemaSnapshot.capture(self.runner.engine)
        seeder = self._build_seeder(schema_before)

        self.runner.upgrade(revision)
        self.runner.downgrade()

        schema_restored = SchemaSnapshot.capture(self.runner.engine)

        for issue in SchemaDiff().verify_restored(schema_before, schema_restored):
            failures.append(issue.message)
        failures.extend(seeder.verify())

        return RevisionResult(revision=revision, passed=len(failures) == 0, failures=failures)

    def check_all(self) -> list[RevisionResult]:
        results: list[RevisionResult] = []
        prev_revision: str | None = None
        self.runner.downgrade_base()

        for rev in self.runner.get_revisions():
            if self.runner.current_revision() != prev_revision:
                self._reset_to(prev_revision)

            result = self.check_revision(rev.revision)
            results.append(result)

            self._reset_to(rev.revision)
            prev_revision = rev.revision

        return results
