from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Callable

from .runner import MigrationRunner
from .schema import SchemaDiff, SchemaSnapshot
from .seeder import SeededRow, SmartSeeder, _q


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
      2. Upgrade → Downgrade
      3. Verify schema restored + data intact

    State contract:
      check_revision(rev) expects the DB to be at the revision BEFORE rev.
      After the call the DB is returned to that same pre-revision state,
      whether the check passes, fails, or throws.

      check_all() handles advancing through the chain efficiently in O(n)
      upgrade operations rather than the naive O(n²) downgrade-base approach.
    """

    def __init__(
        self,
        runner: MigrationRunner,
        skip: dict[str, str] | None = None,
        custom_seeds: dict[str, Callable[[], list[dict]]] | None = None,
        timeout: int | None = None,
        min_revision: str | None = None,
    ):
        self.runner = runner
        self.skip = skip or {}
        self.custom_seeds = custom_seeds or {}
        self.timeout = timeout
        self.min_revision = min_revision

    def _build_seeder(self, schema: SchemaSnapshot) -> SmartSeeder:
        seeder = SmartSeeder(self.runner.engine)
        for tname, table_info in schema.tables.items():
            if tname in self.custom_seeds:
                rows = self.custom_seeds[tname]()
                pk_col = table_info.pk_cols[0] if table_info.pk_cols else "id"
                for row in rows:
                    # Use dialect-aware quoting — fixes MySQL double-quote bug
                    def q(name: str) -> str:
                        return _q(self.runner.engine, name)

                    cols = ", ".join(q(c) for c in row)
                    placeholders = ", ".join(f":p_{c}" for c in row)
                    params = {f"p_{c}": v for c, v in row.items()}
                    from sqlalchemy import text

                    try:
                        with self.runner.engine.begin() as conn:
                            conn.execute(
                                text(f"INSERT INTO {q(tname)} ({cols}) VALUES ({placeholders})"),
                                params,
                            )
                    except Exception as exc:
                        import warnings

                        warnings.warn(
                            f"pytest-mrt: failed to insert custom seed row into '{tname}': {exc}",
                            stacklevel=2,
                        )
                        # Insert failed — do NOT track this row, otherwise verify()
                        # would report it as "lost after rollback" (false positive).
                        continue

                    # Only track rows that were actually inserted.
                    seeder._rows.append(
                        SeededRow(table=tname, pk_col=pk_col, pk_val=row.get(pk_col), data=row)
                    )
            else:
                seeder.seed_table(table_info)
        return seeder

    def _run_migration_check(
        self,
        revision: str,
        schema_before: SchemaSnapshot,
        seeder: SmartSeeder,
    ) -> list[str]:
        """upgrade → downgrade → verify. Extracted for timeout wrapping."""
        self.runner.upgrade(revision)
        self.runner.downgrade()
        schema_restored = SchemaSnapshot.capture(self.runner.engine)
        failures: list[str] = []
        for issue in SchemaDiff().verify_restored(schema_before, schema_restored):
            failures.append(issue.message)
        failures.extend(seeder.verify())
        return failures

    def check_revision(self, revision: str) -> RevisionResult:
        """
        Test that a single migration is safely reversible.

        Pre:  DB is at the state just BEFORE this revision (down_revision).
        Post: DB is restored to that same pre-revision state, guaranteed.
        """
        if revision in self.skip:
            return RevisionResult(
                revision=revision,
                passed=True,
                skipped=True,
                skip_reason=self.skip[revision],
            )

        start_revision = self.runner.current_revision()
        failures: list[str] = []

        try:
            schema_before = SchemaSnapshot.capture(self.runner.engine)
            seeder = self._build_seeder(schema_before)

            if self.timeout is not None:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self._run_migration_check, revision, schema_before, seeder
                    )
                    try:
                        failures = future.result(timeout=self.timeout)
                    except FuturesTimeout:
                        failures.append(
                            f"Migration timed out after {self.timeout}s — "
                            "upgrade() or downgrade() did not complete within the limit. "
                            "The migration may be deadlocked or running a long data operation. "
                            "Increase MRTConfig.migration_timeout or split the migration."
                        )
            else:
                failures = self._run_migration_check(revision, schema_before, seeder)

        except Exception as exc:
            failures.append(f"Unexpected error during check: {type(exc).__name__}: {exc}")
            # Best-effort state recovery: return DB to start_revision
            try:
                current = self.runner.current_revision()
                if current != start_revision:
                    self.runner.downgrade_base()
                    if start_revision is not None:
                        self.runner.upgrade(start_revision)
            except Exception as recovery_exc:
                failures.append(
                    f"State recovery failed after error — DB may be in unknown state: "
                    f"{recovery_exc}"
                )

        return RevisionResult(
            revision=revision,
            passed=len(failures) == 0,
            failures=failures,
        )

    def check_all(self) -> list[RevisionResult]:
        """
        Test every migration in the chain.

        Runs in O(n) upgrade operations:
          - Start from base
          - For each revision: check (up+down), then advance (up again)
          Rather than the naive pattern of downgrade_base before every check.

        Revisions at or before min_revision are skipped (advanced but not tested).
        """
        results: list[RevisionResult] = []
        self.runner.downgrade_base()

        # Build ordered list and find the floor index for min_revision
        revisions = self.runner.get_revisions()
        floor_idx: int | None = None
        if self.min_revision is not None:
            for i, rev in enumerate(revisions):
                if rev.revision == self.min_revision:
                    floor_idx = i
                    break

        for i, rev in enumerate(revisions):
            if floor_idx is not None and i <= floor_idx:
                # Below the floor — just advance, don't test
                results.append(
                    RevisionResult(
                        revision=rev.revision,
                        passed=True,
                        skipped=True,
                        skip_reason=(
                            f"At or before minimum_downgrade_revision floor ({self.min_revision})"
                        ),
                    )
                )
                try:
                    self.runner.upgrade(rev.revision)
                except Exception as exc:
                    results.append(
                        RevisionResult(
                            revision=f"chain-advance-{rev.revision}",
                            passed=False,
                            failures=[
                                f"Could not advance past floor revision {rev.revision}: {exc}. "
                                "Remaining migrations were not tested."
                            ],
                        )
                    )
                    break
                continue

            # DB is at the revision just before rev.revision
            result = self.check_revision(rev.revision)
            results.append(result)

            # Advance to rev.revision for the next iteration.
            # check_revision guarantees the DB is back at pre-rev state,
            # so a single upgrade() here is sufficient.
            try:
                self.runner.upgrade(rev.revision)
            except Exception as exc:
                # If we can't advance, stop the chain — subsequent checks
                # would be running against the wrong DB state.
                results.append(
                    RevisionResult(
                        revision=f"chain-advance-{rev.revision}",
                        passed=False,
                        failures=[
                            f"Could not advance to revision {rev.revision} after check: {exc}. "
                            "Remaining migrations were not tested."
                        ],
                    )
                )
                break

        return results
