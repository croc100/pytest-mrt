"""
MRTTestCase — unittest.TestCase integration for Django migration rollback testing.

Usage::

    from pytest_mrt.django_testcase import MRTTestCase

    class TestRemovePhoneField(MRTTestCase):
        db_url      = "sqlite:///test.db"
        migrate_from = ("myapp", "0009_add_phone")
        migrate_to   = ("myapp", "0010_remove_phone")

        def test_rollback_is_safe(self):
            self.assertRollbackSafe()

        def test_existing_rows_survive(self):
            User = self.old_apps.get_model("myapp", "User")
            User.objects.create(name="Alice", phone="+1-555-0100")
            self.assertDataIntact()
"""

from __future__ import annotations

import os
import unittest
from typing import Any


class MRTTestCase(unittest.TestCase):
    """
    Base class for Django migration rollback tests without pytest.

    Subclass and set:
      - ``db_url``      — SQLAlchemy-style DB URL (or set DATABASE_URL env var)
      - ``migrate_from`` — (app_label, migration_name) — starting state
      - ``migrate_to``   — (app_label, migration_name) — migration under test

    Then call ``assertRollbackSafe()`` or ``assertDataIntact()`` in test methods.
    """

    db_url: str = ""
    migrate_from: tuple[str, str]
    migrate_to: tuple[str, str]

    # ── class-level setup ─────────────────────────────────────────────

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

        db_url = cls.db_url or os.environ.get("DATABASE_URL", "")
        if not db_url:
            raise RuntimeError(
                "MRTTestCase requires a database URL. "
                "Set the 'db_url' class attribute or the DATABASE_URL environment variable."
            )

        if not hasattr(cls, "migrate_from") or not hasattr(cls, "migrate_to"):
            raise RuntimeError(
                "MRTTestCase requires 'migrate_from' and 'migrate_to' class attributes. "
                "Example: migrate_from = ('myapp', '0009_prev') ; migrate_to = ('myapp', '0010_target')"
            )

        from .adapters.django_runner import DjangoMigrationRunner
        from .adapters.django_verifier import DjangoRollbackVerifier

        cls._runner = DjangoMigrationRunner(db_url)
        cls._verifier = DjangoRollbackVerifier(cls._runner)

        # Bring the DB to the state just before migrate_to
        cls._runner.upgrade(*cls.migrate_from)

    @classmethod
    def tearDownClass(cls) -> None:
        # Best-effort: roll the test app back to zero so other test classes
        # start clean. Swallow errors so teardown never masks test failures.
        try:
            cls._runner.downgrade_app_zero(cls.migrate_to[0])
        except Exception:
            pass
        super().tearDownClass()

    # ── per-test setup ────────────────────────────────────────────────

    def setUp(self) -> None:
        # Guarantee migrate_from state at the start of each test method.
        self._runner.upgrade(*self.migrate_from)

    # ── public API ────────────────────────────────────────────────────

    @property
    def old_apps(self) -> Any:
        """Historical Django app registry at the migrate_from state.

        Use this to create model instances that match the schema *before*
        the migration under test::

            User = self.old_apps.get_model("myapp", "User")
            User.objects.create(name="Alice")
        """
        return self._historical_apps(self.migrate_from)

    @property
    def apps(self) -> Any:
        """Historical Django app registry at the migrate_to state."""
        return self._historical_apps(self.migrate_to)

    def assertRollbackSafe(self) -> None:
        """Assert that the migration under test is safely reversible.

        Runs the full pytest-mrt check:
          1. Snapshot schema before the migration
          2. Seed real rows into all tables
          3. Upgrade to migrate_to
          4. Downgrade back to migrate_from
          5. Verify schema and all seeded rows are fully restored

        Fails the test with a detailed message if any data or schema is lost.
        """
        from .adapters.django_runner import DjangoMigration

        migration = DjangoMigration(
            app_label=self.migrate_to[0],
            name=self.migrate_to[1],
        )
        result = self._verifier.check_migration(migration)
        self.assertTrue(
            result.passed,
            msg=f"Migration {self.migrate_to[0]}.{self.migrate_to[1]} is not safely reversible:\n"
            + "\n".join(f"  - {f}" for f in result.failures),
        )

    def assertDataIntact(self) -> None:
        """Assert that data created before the migration survives rollback.

        Call this after seeding your own data in the test::

            def test_user_survives(self):
                User = self.old_apps.get_model("myapp", "User")
                User.objects.create(name="Alice")
                self.assertDataIntact()   # Alice must still exist after rollback

        Upgrades to migrate_to, then downgrades back to migrate_from, and
        verifies the seeded rows are still present.
        """
        from .core.schema import SchemaDiff, SchemaSnapshot
        from .core.seeder import SmartSeeder

        engine = self._runner.engine
        schema_before = SchemaSnapshot.capture(engine)

        # Seed rows for tables that the user hasn't already populated
        seeder = SmartSeeder(engine)
        for tname, table_info in schema_before.tables.items():
            seeder.seed_table(table_info)

        self._runner.upgrade(*self.migrate_to)
        self._runner.downgrade(*self.migrate_to)

        schema_after = SchemaSnapshot.capture(engine)
        schema_issues = list(SchemaDiff().verify_restored(schema_before, schema_after))
        data_issues = seeder.verify()

        failures = [i.message for i in schema_issues] + list(data_issues)
        self.assertFalse(
            failures,
            msg="Data or schema was not fully restored after rollback:\n"
            + "\n".join(f"  - {f}" for f in failures),
        )

    # ── internals ─────────────────────────────────────────────────────

    @staticmethod
    def _historical_apps(target: tuple[str, str]) -> Any:
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        conn = connections["default"]
        executor = MigrationExecutor(conn)
        state = executor.loader.project_state(target, at_end=True)
        return state.apps
