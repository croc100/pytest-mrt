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
      - ``db_url``       — SQLAlchemy-style DB URL (or set DATABASE_URL env var)
      - ``migrate_from`` — (app_label, migration_name) — starting state
      - ``migrate_to``   — (app_label, migration_name) — migration under test
      - ``db_alias``     — Django database alias used by the runner (default: ``"default"``)

    Then call ``assertRollbackSafe()`` or ``assertDataIntact()`` in test methods.
    """

    db_url: str = ""
    db_alias: str = "default"  # Django DB alias configured by DjangoMigrationRunner
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

        Snapshots all pre-existing rows (user-created in setUp or the test
        body), seeds additional rows via SmartSeeder, runs upgrade+downgrade,
        then verifies that BOTH sets of rows are fully restored.

        Call this after seeding your own data::

            def test_user_survives(self):
                User = self.old_apps.get_model("myapp", "User")
                User.objects.create(name="Alice")
                self.assertDataIntact()   # Alice must still exist after rollback
        """
        from sqlalchemy import text

        from .core.schema import SchemaDiff, SchemaSnapshot
        from .core.seeder import SmartSeeder

        engine = self._runner.engine
        schema_before = SchemaSnapshot.capture(engine)

        # --- 1. Snapshot PKs of all rows that ALREADY EXIST (user-created via setUp /
        #        test body).  Must happen before SmartSeeder inserts its own rows so we
        #        can distinguish user data from synthetic seed data.
        existing_pks: dict[str, set] = {}
        with engine.connect() as conn:
            for tname, tinfo in schema_before.tables.items():
                if tinfo.pk_cols:
                    pk_col = tinfo.pk_cols[0]
                    rows = (
                        conn.execute(
                            text(f"SELECT {pk_col} FROM {tname}")  # noqa: S608
                        )
                        .scalars()
                        .all()
                    )
                    if rows:
                        existing_pks[tname] = set(rows)

        # --- 2. Seed additional rows so the round-trip runs against non-trivial data ---
        seeder = SmartSeeder(engine)
        for tname, table_info in schema_before.tables.items():
            seeder.seed_table(table_info)

        # --- 3. Migration round-trip with error recovery ---
        try:
            self._runner.upgrade(*self.migrate_to)
            self._runner.downgrade(*self.migrate_to)
        except Exception:
            # Best-effort recovery: roll back to zero so the next test doesn't
            # start from an inconsistent migration state.
            try:
                self._runner.downgrade_app_zero(self.migrate_to[0])
            except Exception:
                pass
            raise

        # --- 4. Verify schema was fully restored ---
        schema_after = SchemaSnapshot.capture(engine)
        schema_issues = list(SchemaDiff().verify_restored(schema_before, schema_after))

        # --- 5. Verify SmartSeeder rows survived ---
        data_issues = list(seeder.verify())

        # --- 6. Verify user-created rows survived ---
        user_row_failures: list[str] = []
        if existing_pks:
            with engine.connect() as conn:
                for tname, before_pks in existing_pks.items():
                    if tname not in schema_after.tables:
                        continue  # already reported as a schema-level issue
                    tinfo = schema_before.tables[tname]
                    pk_col = tinfo.pk_cols[0]
                    after_pks = set(
                        conn.execute(
                            text(f"SELECT {pk_col} FROM {tname}")  # noqa: S608
                        )
                        .scalars()
                        .all()
                    )
                    lost = before_pks - after_pks
                    if lost:
                        user_row_failures.append(
                            f"Table '{tname}': {len(lost)}/{len(before_pks)}"
                            f" pre-existing row(s) lost after rollback"
                        )

        failures = [i.message for i in schema_issues] + data_issues + user_row_failures
        self.assertFalse(
            failures,
            msg="Data or schema was not fully restored after rollback:\n"
            + "\n".join(f"  - {f}" for f in failures),
        )

    # ── internals ─────────────────────────────────────────────────────

    @classmethod
    def _historical_apps(cls, target: tuple[str, str]) -> Any:
        """Return the historical Django app registry at the given migration state.

        Uses ``cls.db_alias`` (default: ``"default"``).  Override ``db_alias``
        on the subclass when ``DjangoMigrationRunner`` was configured to use a
        non-default connection alias.
        """
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        conn = connections[cls.db_alias]
        executor = MigrationExecutor(conn)
        state = executor.loader.project_state(target, at_end=True)
        return state.apps
