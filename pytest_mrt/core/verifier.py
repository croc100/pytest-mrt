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
    For each revision under test:
      1. Seed data into tables that exist BEFORE this migration (pre-upgrade state)
      2. Upgrade to the revision
      3. Downgrade one step
      4. Verify schema is exactly restored + seeded data survived
    """

    def __init__(self, runner: MigrationRunner):
        self.runner = runner

    def check_revision(self, revision: str) -> RevisionResult:
        seeder = SmartSeeder(self.runner.engine)
        failures: list[str] = []

        # Capture state before this migration
        schema_before = SchemaSnapshot.capture(self.runner.engine)

        # Seed into pre-existing tables — these rows must survive rollback
        seeder.seed_all(schema_before.tables)

        # Apply and then revert the migration
        self.runner.upgrade(revision)
        self.runner.downgrade()

        schema_restored = SchemaSnapshot.capture(self.runner.engine)

        # Schema must be exactly as before (no missing tables, no leftover tables)
        diff = SchemaDiff()
        for issue in diff.verify_restored(schema_before, schema_restored):
            failures.append(issue.message)

        # Data seeded before upgrade must survive the round-trip
        failures.extend(seeder.verify())

        return RevisionResult(
            revision=revision,
            passed=len(failures) == 0,
            failures=failures,
        )

    def check_all(self) -> list[RevisionResult]:
        """Test every revision independently in sequence."""
        results: list[RevisionResult] = []
        self.runner.downgrade_base()

        for rev in self.runner.get_revisions():
            result = self.check_revision(rev.revision)
            results.append(result)
            # Advance to this revision so the next check starts from correct state
            self.runner.upgrade(rev.revision)

        return results
