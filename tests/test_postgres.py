"""
PostgreSQL-specific integration tests.

Skipped automatically when TEST_DATABASE_URL is not set or not a PostgreSQL URL.
Run locally:
    TEST_DATABASE_URL=postgresql://user:pass@localhost/mrt_test pytest tests/test_postgres.py -v
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

PG_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not PG_URL.startswith("postgresql"),
    reason="TEST_DATABASE_URL not set to a PostgreSQL URL",
)


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip())


def _setup_alembic(tmp: Path, db_url: str) -> tuple[str, str]:
    versions = tmp / "versions"
    versions.mkdir()

    _write(
        tmp / "alembic.ini",
        f"""
        [alembic]
        script_location = {tmp}
        sqlalchemy.url = {db_url}
    """,
    )

    _write(
        tmp / "env.py",
        """
        from alembic import context
        from sqlalchemy import engine_from_config, pool

        config = context.config

        def run_migrations_online():
            connectable = engine_from_config(
                config.get_section(config.config_ini_section),
                prefix="sqlalchemy.",
                poolclass=pool.NullPool,
            )
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=None)
                with context.begin_transaction():
                    context.run_migrations()

        run_migrations_online()
    """,
    )

    _write(
        tmp / "script.py.mako",
        """
        \"\"\"${message}\"\"\"
        revision = '${up_revision}'
        down_revision = ${repr(down_revision)}
        branch_labels = ${repr(branch_labels)}
        depends_on = ${repr(depends_on)}

        def upgrade(): ${upgrades if upgrades else "pass"}
        def downgrade(): ${downgrades if downgrades else "pass"}
    """,
    )

    return str(tmp / "alembic.ini"), str(versions)


@pytest.fixture()
def pg_env(tmp_path):
    ini, versions = _setup_alembic(tmp_path, PG_URL)
    yield {"ini": ini, "versions": versions, "db_url": PG_URL}


# ── helpers ──────────────────────────────────────────────────────────


def _add_migration(versions_dir: str, filename: str, content: str) -> None:
    _write(Path(versions_dir) / filename, textwrap.dedent(content).lstrip())


# ── tests ─────────────────────────────────────────────────────────────


def test_pg_reversible_migration(pg_env):
    """Basic add/drop column is reversible on PostgreSQL."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    _add_migration(
        pg_env["versions"],
        "001_create_users.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('pg_mrt_users',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
                sa.Column('email', sa.String(128), nullable=True),
            )

        def downgrade():
            op.drop_table('pg_mrt_users')
        """,
    )

    runner = MigrationRunner(pg_env["ini"], pg_env["db_url"])
    try:
        verifier = RollbackVerifier(runner)
        result = verifier.check_revision("001")
        assert result.passed, result.failure_summary()
    finally:
        runner.downgrade_base()
        runner.dispose()


def test_pg_noop_downgrade_fails(pg_env):
    """noop downgrade() is caught on PostgreSQL."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    _add_migration(
        pg_env["versions"],
        "001_create.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('pg_mrt_events',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
            )

        def downgrade():
            pass
        """,
    )

    runner = MigrationRunner(pg_env["ini"], pg_env["db_url"])
    try:
        verifier = RollbackVerifier(runner)
        result = verifier.check_revision("001")
        assert not result.passed
        assert any(
            "still exists" in f.lower() or "incomplete" in f.lower() for f in result.failures
        )
    finally:
        runner.downgrade_base()
        # Clean up table left behind by noop downgrade
        engine = create_engine(pg_env["db_url"])
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS pg_mrt_events"))
        engine.dispose()
        runner.dispose()


def test_pg_seeder_inserts_and_verifies(pg_env):
    """SmartSeeder works correctly on PostgreSQL (NullPool, quoting)."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.schema import SchemaSnapshot
    from pytest_mrt.core.seeder import SmartSeeder

    _add_migration(
        pg_env["versions"],
        "001_create.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('pg_mrt_items',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('title', sa.String(128), nullable=False),
            )

        def downgrade():
            op.drop_table('pg_mrt_items')
        """,
    )

    runner = MigrationRunner(pg_env["ini"], pg_env["db_url"])
    try:
        runner.upgrade("001")
        snap = SchemaSnapshot.capture(runner.engine)
        assert "pg_mrt_items" in snap.tables

        seeder = SmartSeeder(runner.engine)
        seeder.seed_table(snap.tables["pg_mrt_items"])
        failures = seeder.verify()
        assert failures == [], failures
    finally:
        runner.downgrade_base()
        runner.dispose()


def test_pg_check_all_reversible(pg_env):
    """check_all() works on a 2-migration PostgreSQL chain."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    _add_migration(
        pg_env["versions"],
        "001_create.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('pg_mrt_products',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(128), nullable=False),
            )

        def downgrade():
            op.drop_table('pg_mrt_products')
        """,
    )

    _add_migration(
        pg_env["versions"],
        "002_add_price.py",
        """
        revision = '002'
        down_revision = '001'
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.add_column('pg_mrt_products',
                sa.Column('price', sa.Numeric(10, 2), nullable=True))

        def downgrade():
            op.drop_column('pg_mrt_products', 'price')
        """,
    )

    runner = MigrationRunner(pg_env["ini"], pg_env["db_url"])
    try:
        verifier = RollbackVerifier(runner)
        results = verifier.check_all()
        assert len(results) == 2
        assert all(r.passed for r in results), "\n".join(
            r.failure_summary() for r in results if not r.passed
        )
    finally:
        runner.downgrade_base()
        runner.dispose()
