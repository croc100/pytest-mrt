from __future__ import annotations
from dataclasses import dataclass, field

from .runner import MigrationRunner
from .schema import SchemaSnapshot, SchemaDiff
from .seeder import SmartSeeder


@dataclass
class RevisionResult:
    revision: str
    passed: bool
    failures: list[str] = field(default_factory=list)

    def failure_summary(self) -> str:
        return "\n".join(f"  - {f}" for f in self.failures)


class RollbackVerifier:
    """
    For each revision:
      1. Seed real data into tables that exist BEFORE this migration
      2. Upgrade to the revision
      3. Downgrade one step
      4. Verify schema exactly restored + seeded data survived with correct values
    """

    def __init__(self, runner: MigrationRunner):
        self.runner = runner

    def _reset_to(self, revision: str | None) -> None:
        """Reliably move DB to a specific revision, handling noop downgrades."""
        self.runner.downgrade_base()
        if revision is not None:
            self.runner.upgrade(revision)

    def check_revision(self, revision: str) -> RevisionResult:
        seeder = SmartSeeder(self.runner.engine)
        failures: list[str] = []

        schema_before = SchemaSnapshot.capture(self.runner.engine)
        seeder.seed_all(schema_before.tables)

        self.runner.upgrade(revision)
        self.runner.downgrade()

        schema_restored = SchemaSnapshot.capture(self.runner.engine)

        diff = SchemaDiff()
        for issue in diff.verify_restored(schema_before, schema_restored):
            failures.append(issue.message)

        failures.extend(seeder.verify())

        return RevisionResult(
            revision=revision,
            passed=len(failures) == 0,
            failures=failures,
        )

    def check_all(self) -> list[RevisionResult]:
        """
        Test every revision independently in sequence.
        After each check, hard-reset the DB state to handle noop downgrades
        and other edge cases that leave the DB in an inconsistent state.
        """
        results: list[RevisionResult] = []
        prev_revision: str | None = None

        self.runner.downgrade_base()

        for rev in self.runner.get_revisions():
            # Ensure we start each revision check from the correct state
            # This handles noop downgrades leaving the schema out of sync
            current = self.runner.current_revision()
            if current != prev_revision:
                self._reset_to(prev_revision)

            result = self.check_revision(rev.revision)
            results.append(result)

            # Hard reset to this revision for the next iteration
            # Necessary because a failed downgrade may leave the schema out of sync
            self._reset_to(rev.revision)
            prev_revision = rev.revision

        return results
