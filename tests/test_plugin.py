"""Integration tests for MRTFixture (plugin.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from pytest_mrt.config import MRTConfig
from pytest_mrt.plugin import MRTFixture


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip())


def _setup_alembic(tmp: Path, db_path: str) -> tuple[str, str]:
    versions = tmp / "versions"
    versions.mkdir()

    _write(
        tmp / "alembic.ini",
        f"""
        [alembic]
        script_location = {tmp}
        sqlalchemy.url = sqlite:///{db_path}
    """,
    )

    _write(
        tmp / "env.py",
        """
        from alembic import context
        from sqlalchemy import engine_from_config, pool

        config = context.config

        def run_migrations_offline():
            url = config.get_main_option("sqlalchemy.url")
            context.configure(url=url, target_metadata=None, literal_binds=True)
            with context.begin_transaction():
                context.run_migrations()

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

        if context.is_offline_mode():
            run_migrations_offline()
        else:
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
def alembic_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    ini, versions = _setup_alembic(tmp_path, db_path)
    db_url = f"sqlite:///{db_path}"
    yield {"ini": ini, "versions": versions, "db_url": db_url, "tmp": tmp_path}


def _add_migration(versions_dir: str, filename: str, content: str) -> None:
    _write(Path(versions_dir) / filename, content)


def _simple_reversible_migration(versions_dir: str) -> None:
    _add_migration(
        versions_dir,
        "001_users.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('users',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
            )

        def downgrade():
            op.drop_table('users')
    """),
    )


# ── MRTFixture construction ────────────────────────────────────────────


def test_mrt_fixture_upgrade_downgrade(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)

    fixture.upgrade("001")
    engine = create_engine(alembic_env["db_url"])
    with engine.connect() as conn:
        tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    table_names = [t[0] for t in tables]
    assert "users" in table_names
    engine.dispose()

    fixture.downgrade()
    engine = create_engine(alembic_env["db_url"])
    with engine.connect() as conn:
        tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    table_names = [t[0] for t in tables]
    assert "users" not in table_names
    engine.dispose()

    fixture.reset()


def test_mrt_fixture_assert_reversible_passes(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    fixture.assert_reversible("001")
    fixture.reset()


def test_mrt_fixture_assert_reversible_fails_on_noop(alembic_env):
    _add_migration(
        alembic_env["versions"],
        "001_noop.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('events',
                sa.Column('id', sa.Integer, primary_key=True),
                sa.Column('name', sa.String(64), nullable=False),
            )

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    result = fixture.check_revision("001")
    assert not result.passed
    fixture.reset()


def test_mrt_fixture_assert_all_reversible_passes(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])
    _add_migration(
        alembic_env["versions"],
        "002_add_email.py",
        textwrap.dedent("""
        revision = '002'
        down_revision = '001'
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.add_column('users', sa.Column('email', sa.String(128), nullable=True))

        def downgrade():
            op.drop_column('users', 'email')
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    fixture.assert_all_reversible()
    fixture.reset()


def test_mrt_fixture_check_revision(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    result = fixture.check_revision("001")
    assert result.passed
    fixture.reset()


def test_mrt_fixture_check_all(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    results = fixture.check_all()
    assert len(results) == 1
    assert all(r.passed for r in results)
    fixture.reset()


def test_mrt_fixture_check_all_min_revision_skips_floor(alembic_env):
    v = alembic_env["versions"]
    _add_migration(
        v,
        "001_first.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute("SELECT 1")
        def downgrade():
            op.execute("SELECT 1")
        """),
    )
    _add_migration(
        v,
        "002_second.py",
        textwrap.dedent("""
        revision = '002'
        down_revision = '001'
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.execute("SELECT 1")
        def downgrade():
            op.execute("SELECT 1")
        """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
        minimum_downgrade_revision="001",
    )
    fixture = MRTFixture(cfg)
    results = fixture.check_all()
    fixture.reset()

    assert len(results) == 2
    assert results[0].skipped
    assert "floor" in results[0].skip_reason
    assert not results[1].skipped
    assert results[1].passed


def test_mrt_fixture_check_static(alembic_env):
    _add_migration(
        alembic_env["versions"],
        "001_risky.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.drop_column('users', 'email')

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    warnings = fixture.check_static(alembic_env["versions"])
    assert len(warnings) > 0


def test_mrt_fixture_assert_no_static_errors_fails(alembic_env):
    _add_migration(
        alembic_env["versions"],
        "001_noop_down.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.drop_column('users', 'email')

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    warnings = fixture.check_static(alembic_env["versions"])
    errors = [w for w in warnings if w.severity == "error"]
    assert len(errors) > 0
    fixture.reset()


def test_mrt_fixture_custom_seeds(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
        custom_seeds={"users": lambda: [{"id": 99, "name": "TestUser"}]},
    )
    fixture = MRTFixture(cfg)
    result = fixture.check_revision("001")
    assert result.passed
    fixture.reset()


def test_mrt_fixture_severity_overrides(alembic_env):
    _add_migration(
        alembic_env["versions"],
        "001_risky.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        from alembic import op

        def upgrade():
            op.drop_column('users', 'email')

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
        severity_overrides={"noop downgrade": "warning"},
    )
    fixture = MRTFixture(cfg)
    warnings = fixture.check_static(alembic_env["versions"])
    noop_warnings = [w for w in warnings if w.pattern == "noop downgrade"]
    if noop_warnings:
        assert all(w.severity == "warning" for w in noop_warnings)
    fixture.reset()


def test_mrt_fixture_skip(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
        skip={"001": "intentional data migration"},
    )
    fixture = MRTFixture(cfg)
    result = fixture.check_revision("001")
    assert result.passed
    assert result.skipped
    assert result.skip_reason == "intentional data migration"
    fixture.reset()


def test_mrt_fixture_assert_data_intact(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    fixture.upgrade("001")
    fixture.assert_data_intact()
    fixture.downgrade()
    fixture.reset()


def test_mrt_fixture_custom_check(alembic_env):
    _simple_reversible_migration(alembic_env["versions"])

    custom_called = []

    def my_check(m):
        custom_called.append(m.revision)
        return []

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
        custom_checks=[my_check],
    )
    fixture = MRTFixture(cfg)
    fixture.check_static(alembic_env["versions"])
    assert len(custom_called) > 0
    fixture.reset()


def test_mrt_fixture_seed_valid_table(alembic_env):
    """seed() inserts into an existing table without error."""
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    fixture.upgrade("001")
    fixture.seed("users", [{"id": 99, "name": "Alice"}])
    fixture.downgrade()
    fixture.reset()


def test_mrt_fixture_seed_invalid_table_raises(alembic_env):
    """seed() raises ValueError when the table doesn't exist."""
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    fixture.upgrade("001")
    with pytest.raises(ValueError, match="not found"):
        fixture.seed("nonexistent_table", [{"id": 1}])
    fixture.downgrade()
    fixture.reset()


def test_mrt_fixture_check_static_no_versions_dir(alembic_env):
    """check_static() without versions_dir uses runner.get_versions_dir()."""
    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    # Should not raise — derives versions_dir from alembic config
    warnings = fixture.check_static()
    assert isinstance(warnings, list)
    fixture.reset()


def test_mrt_fixture_assert_data_intact_failure(alembic_env):
    """assert_data_intact() calls pytest.fail when seeded rows are missing."""
    from pytest_mrt.core.seeder import SeededRow

    _simple_reversible_migration(alembic_env["versions"])

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    fixture.upgrade("001")

    # Inject a ghost row that doesn't actually exist in the DB
    fixture._seeder._rows.append(SeededRow("users", "id", 9999, {"id": 9999, "name": "ghost"}))

    with pytest.raises(BaseException):
        fixture.assert_data_intact()

    fixture.downgrade()
    fixture.reset()


def test_mrt_fixture_assert_reversible_failure_calls_fail(alembic_env):
    """assert_reversible() calls pytest.fail on non-reversible migration."""
    _add_migration(
        alembic_env["versions"],
        "001_noop_d.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('things',
                sa.Column('id', sa.Integer, primary_key=True),
            )

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)

    with pytest.raises(BaseException):
        fixture.assert_reversible("001")

    fixture.reset()


def test_mrt_fixture_assert_all_reversible_failure_calls_fail(alembic_env):
    """assert_all_reversible() calls pytest.fail when any migration fails."""
    _add_migration(
        alembic_env["versions"],
        "001_noop_d2.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('gadgets',
                sa.Column('id', sa.Integer, primary_key=True),
            )

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)

    with pytest.raises(BaseException):
        fixture.assert_all_reversible()

    fixture.reset()


def test_mrt_pytest_fixture_via_pytester(pytester, alembic_env):
    """The mrt pytest fixture yields an MRTFixture and is properly cleaned up."""
    pytester.makeconftest(f"""
        from pytest_mrt import MRTConfig
        def pytest_configure(config):
            config._mrt_config = MRTConfig(
                alembic_ini="{alembic_env["ini"]}",
                db_url="{alembic_env["db_url"]}",
            )
    """)
    pytester.makepyfile("""
        from pytest_mrt.plugin import MRTFixture
        def test_fixture_type(mrt):
            assert isinstance(mrt, MRTFixture)
        def test_fixture_has_config(mrt):
            assert mrt._config is not None
    """)
    # Disable default test injection so this test focuses on fixture wiring only.
    pytester.makeini("[pytest]\nmrt_default_tests = false\n")
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


def test_mrt_fixture_risk_score(alembic_env):
    _add_migration(
        alembic_env["versions"],
        "001_noop.py",
        textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None

        import sqlalchemy as sa
        from alembic import op

        def upgrade():
            op.create_table('events',
                sa.Column('id', sa.Integer, primary_key=True),
            )

        def downgrade():
            pass
    """),
    )

    cfg = MRTConfig(
        alembic_ini=alembic_env["ini"],
        db_url=alembic_env["db_url"],
    )
    fixture = MRTFixture(cfg)
    result = fixture.check_revision("001")
    assert not result.passed
    assert result.risk_score > 0
    fixture.reset()


# ── _auto_detect_django ────────────────────────────────────────────────


def test_auto_detect_django_switches_mode_when_env_set_and_no_ini(tmp_path, monkeypatch):
    """_auto_detect_django sets django_settings from env when alembic.ini is missing."""
    import unittest.mock as mock

    from pytest_mrt.plugin import _auto_detect_django

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "myproject.settings_test")
    monkeypatch.chdir(tmp_path)  # no alembic.ini here

    # Ensure Django import succeeds even if not installed
    with mock.patch.dict("sys.modules", {"django": mock.MagicMock()}):
        cfg = MRTConfig(db_url="sqlite:///test.db")
        result = _auto_detect_django(cfg)
    assert result.django_settings == "myproject.settings_test"


def test_auto_detect_django_no_switch_when_alembic_ini_exists(tmp_path, monkeypatch):
    """_auto_detect_django does not switch when alembic.ini exists."""
    from pytest_mrt.plugin import _auto_detect_django

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "myproject.settings_test")
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    monkeypatch.chdir(tmp_path)

    cfg = MRTConfig(alembic_ini=str(tmp_path / "alembic.ini"), db_url="sqlite:///test.db")
    result = _auto_detect_django(cfg)
    assert result.django_settings is None


def test_auto_detect_django_no_switch_when_env_not_set(tmp_path, monkeypatch):
    """_auto_detect_django does nothing when DJANGO_SETTINGS_MODULE is not set."""
    from pytest_mrt.plugin import _auto_detect_django

    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.chdir(tmp_path)

    cfg = MRTConfig(db_url="sqlite:///test.db")
    result = _auto_detect_django(cfg)
    assert result.django_settings is None


def test_auto_detect_django_no_switch_when_explicit_django_settings(tmp_path, monkeypatch):
    """_auto_detect_django leaves explicit django_settings alone."""
    from pytest_mrt.plugin import _auto_detect_django

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "env.settings")
    monkeypatch.chdir(tmp_path)

    cfg = MRTConfig(db_url="sqlite:///test.db", django_settings="explicit.settings")
    result = _auto_detect_django(cfg)
    assert result.django_settings == "explicit.settings"


# ── MRTFixture missing alembic.ini ─────────────────────────────────────


def test_mrt_fixture_raises_on_missing_alembic_ini(tmp_path, monkeypatch):
    """MRTFixture raises MRTConfigError when alembic.ini is missing."""
    from pytest_mrt.exceptions import MRTConfigError

    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)

    cfg = MRTConfig(alembic_ini=str(tmp_path / "nonexistent.ini"), db_url="sqlite:///test.db")
    with pytest.raises(MRTConfigError, match="alembic.ini not found"):
        MRTFixture(cfg)


# ── MigrationRunner missing env.py ─────────────────────────────────────


def test_migration_runner_raises_on_missing_env_py(tmp_path):
    """MigrationRunner raises FileNotFoundError with Django hint when env.py is absent."""
    from pytest_mrt.core.runner import MigrationRunner

    ini = tmp_path / "alembic.ini"
    ini.write_text(f"[alembic]\nscript_location = {tmp_path}\n")

    with pytest.raises(FileNotFoundError, match="django_settings"):
        MigrationRunner(str(ini), "sqlite:///test.db")
