"""
Oracle-specific integration tests.

Skipped automatically when TEST_DATABASE_URL is not set or not an Oracle URL.
Run locally:
    TEST_DATABASE_URL=oracle+oracledb://user:pass@localhost:1521/FREEPDB1 \
        pytest tests/test_oracle.py -v

Via docker-compose:
    docker compose run --service-ports oracle  # start Oracle Free
    TEST_DATABASE_URL=... pytest tests/test_oracle.py -v
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ORA_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not ORA_URL.startswith("oracle"),
    reason="TEST_DATABASE_URL not set to an Oracle URL",
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
def ora_env(tmp_path):
    ini, versions = _setup_alembic(tmp_path, ORA_URL)
    yield {"ini": ini, "versions": versions, "db_url": ORA_URL}


def _add_migration(versions_dir: str, filename: str, content: str) -> None:
    _write(Path(versions_dir) / filename, textwrap.dedent(content).lstrip())


def test_oracle_reversible_migration(ora_env):
    """Basic add/drop table is reversible on Oracle."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    _add_migration(
        ora_env["versions"],
        "001_create_users.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('ora_mrt_users',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
                sa.Column('email', sa.String(128), nullable=True),
            )

        def downgrade():
            op.drop_table('ora_mrt_users')
        """,
    )

    runner = MigrationRunner(ora_env["ini"], ora_env["db_url"])
    try:
        verifier = RollbackVerifier(runner)
        result = verifier.check_revision("001")
        assert result.passed, result.failure_summary()
    finally:
        runner.downgrade_base()
        runner.dispose()


def test_oracle_noop_downgrade_fails(ora_env):
    """noop downgrade() is caught on Oracle."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    _add_migration(
        ora_env["versions"],
        "001_create.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('ora_mrt_events',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
            )

        def downgrade():
            pass
        """,
    )

    runner = MigrationRunner(ora_env["ini"], ora_env["db_url"])
    try:
        verifier = RollbackVerifier(runner)
        result = verifier.check_revision("001")
        assert not result.passed
    finally:
        runner.downgrade_base()
        engine = create_engine(ora_env["db_url"])
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE ora_mrt_events"))
        engine.dispose()
        runner.dispose()


def test_oracle_check_all_reversible(ora_env):
    """check_all() works on a 2-migration Oracle chain."""
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    _add_migration(
        ora_env["versions"],
        "001_create.py",
        """
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('ora_mrt_products',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(128), nullable=False),
            )

        def downgrade():
            op.drop_table('ora_mrt_products')
        """,
    )

    _add_migration(
        ora_env["versions"],
        "002_add_price.py",
        """
        revision = '002'
        down_revision = '001'
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.add_column('ora_mrt_products',
                sa.Column('price', sa.Numeric(10, 2), nullable=True))

        def downgrade():
            op.drop_column('ora_mrt_products', 'price')
        """,
    )

    runner = MigrationRunner(ora_env["ini"], ora_env["db_url"])
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
