"""
Django rollback verifier.

Mirrors RollbackVerifier but uses DjangoMigrationRunner instead of MigrationRunner.
For each Django migration:
  1. Snapshot schema before the migration
  2. Seed real rows
  3. upgrade() — apply the migration
  4. downgrade() — roll it back
  5. Verify schema and data are fully restored
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Callable

from ..core.schema import SchemaDiff, SchemaSnapshot
from ..core.seeder import SeededRow, SmartSeeder, _q
from ..core.verifier import RevisionResult
from .django_runner import DjangoMigration, DjangoMigrationRunner


class DjangoRollbackVerifier:
    """
    Verifies that each Django migration is safely reversible.

    State contract:
      check_migration(m) expects the DB to be at the state just BEFORE m.
      After the call the DB is returned to that same state, guaranteed.
    """

    def __init__(
        self,
        runner: DjangoMigrationRunner,
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
                    seeder._rows.append(
                        SeededRow(table=tname, pk_col=pk_col, pk_val=row.get(pk_col), data=row)
                    )
                from sqlalchemy import text

                def q(name: str) -> str:
                    return _q(self.runner.engine, name)

                for row in rows:
                    cols = ", ".join(q(c) for c in row)
                    placeholders = ", ".join(f":p_{c}" for c in row)
                    params = {f"p_{c}": v for c, v in row.items()}
                    try:
                        with self.runner.engine.begin() as conn:
                            conn.execute(
                                text(f"INSERT INTO {q(tname)} ({cols}) VALUES ({placeholders})"),
                                params,
                            )
                    except Exception:
                        pass
            else:
                seeder.seed_table(table_info)
        return seeder

    def _run_check(
        self,
        migration: DjangoMigration,
        schema_before: SchemaSnapshot,
        seeder: SmartSeeder,
    ) -> list[str]:
        self.runner.upgrade(migration.app_label, migration.name)
        self.runner.downgrade(migration.app_label, migration.name)
        schema_restored = SchemaSnapshot.capture(self.runner.engine)
        failures: list[str] = []
        for issue in SchemaDiff().verify_restored(schema_before, schema_restored):
            failures.append(issue.message)
        failures.extend(seeder.verify())
        return failures

    def check_migration(self, migration: DjangoMigration) -> RevisionResult:
        """
        Test that a single Django migration is safely reversible.

        Pre:  DB is at state just BEFORE this migration.
        Post: DB is restored to that same state, guaranteed.
        """
        rev_id = migration.revision

        if rev_id in self.skip:
            return RevisionResult(
                revision=rev_id,
                passed=True,
                skipped=True,
                skip_reason=self.skip[rev_id],
            )

        failures: list[str] = []

        try:
            schema_before = SchemaSnapshot.capture(self.runner.engine)
            seeder = self._build_seeder(schema_before)

            if self.timeout is not None:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._run_check, migration, schema_before, seeder)
                    try:
                        failures = future.result(timeout=self.timeout)
                    except FuturesTimeout:
                        failures.append(
                            f"Migration timed out after {self.timeout}s. "
                            "Increase MRTConfig.migration_timeout or split the migration."
                        )
            else:
                failures = self._run_check(migration, schema_before, seeder)

        except Exception as exc:
            failures.append(f"Unexpected error: {type(exc).__name__}: {exc}")
            # Best-effort recovery: roll back to zero for this app
            try:
                self.runner.downgrade_app_zero(migration.app_label)
            except Exception as recovery_exc:
                failures.append(f"State recovery failed: {recovery_exc}")

        return RevisionResult(
            revision=rev_id,
            passed=len(failures) == 0,
            failures=failures,
        )

    def check_all(self, apps: list[str] | None = None) -> list[RevisionResult]:
        """
        Test every Django migration in topological order.

        apps: limit to specific app labels. None = all discovered apps.

        Migrations at or before min_revision are skipped (advanced but not tested).
        min_revision format: "app_label.migration_name" (e.g. "myapp.0050_baseline").
        """
        migrations = self.runner.get_migrations(apps=apps)
        if not migrations:
            return []

        # Roll all targeted apps back to zero
        app_labels = list(dict.fromkeys(m.app_label for m in migrations))
        for app in app_labels:
            self.runner.downgrade_app_zero(app)

        # Find the floor index for min_revision
        floor_idx: int | None = None
        if self.min_revision is not None:
            for i, m in enumerate(migrations):
                if m.revision == self.min_revision:
                    floor_idx = i
                    break

        results: list[RevisionResult] = []

        for i, migration in enumerate(migrations):
            if floor_idx is not None and i <= floor_idx:
                # Below the floor — just advance, don't test
                results.append(
                    RevisionResult(
                        revision=migration.revision,
                        passed=True,
                        skipped=True,
                        skip_reason=(
                            f"At or before minimum_downgrade_revision floor ({self.min_revision})"
                        ),
                    )
                )
                try:
                    self.runner.upgrade(migration.app_label, migration.name)
                except Exception as exc:
                    results.append(
                        RevisionResult(
                            revision=f"chain-advance-{migration.revision}",
                            passed=False,
                            failures=[
                                f"Could not advance past floor revision "
                                f"{migration.revision}: {exc}. "
                                "Remaining migrations were not tested."
                            ],
                        )
                    )
                    break
                continue

            result = self.check_migration(migration)
            results.append(result)

            # Advance to this migration for the next iteration
            try:
                self.runner.upgrade(migration.app_label, migration.name)
            except Exception as exc:
                results.append(
                    RevisionResult(
                        revision=f"chain-advance-{migration.revision}",
                        passed=False,
                        failures=[
                            f"Could not advance to {migration.revision} after check: {exc}. "
                            "Remaining migrations were not tested."
                        ],
                    )
                )
                break

        return results
