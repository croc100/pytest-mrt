from __future__ import annotations

from typing import Iterator

import pytest

from .config import MRTConfig
from .core.detector import RiskWarning, analyze_migrations
from .core.drift import compare_schema, describe_diff, load_metadata
from .core.runner import MigrationRunner
from .core.schema import SchemaSnapshot
from .core.seeder import SmartSeeder
from .core.verifier import RevisionResult, RollbackVerifier
from .exceptions import MRTConfigError


def _auto_detect_django(config: MRTConfig) -> MRTConfig:
    """
    If django_settings is not set but DJANGO_SETTINGS_MODULE is in the environment
    and alembic.ini is absent, automatically switch to Django mode.
    Returns a (possibly updated) MRTConfig.
    """
    import os
    from pathlib import Path

    if config.django_settings is not None:
        return config  # already explicit

    env_settings = os.environ.get("DJANGO_SETTINGS_MODULE")
    if not env_settings:
        return config  # no Django env var

    alembic_missing = not Path(config.alembic_ini).exists()
    if not alembic_missing:
        return config  # alembic.ini exists → user probably wants Alembic mode

    try:
        import django  # noqa: F401
    except ImportError:
        return config  # Django not installed

    import warnings

    warnings.warn(
        f"pytest-mrt: DJANGO_SETTINGS_MODULE='{env_settings}' detected and alembic.ini "
        f"not found — automatically using Django mode. "
        f"To make this explicit, set django_settings='{env_settings}' in MRTConfig.",
        stacklevel=3,
    )

    from dataclasses import replace

    return replace(config, django_settings=env_settings)


class MRTFixture:
    def __init__(self, config: MRTConfig):
        config = _auto_detect_django(config)
        self._config = config
        self._django_mode = config.django_settings is not None

        if self._django_mode:
            from .adapters.django_runner import DjangoMigrationRunner
            from .adapters.django_verifier import DjangoRollbackVerifier

            self._django_runner = DjangoMigrationRunner(
                db_url=config.db_url,
                settings_module=config.django_settings,
                project_dir=config.django_project_dir,
            )
            self._django_verifier = DjangoRollbackVerifier(
                self._django_runner,
                skip=config.skip,
                custom_seeds=config.custom_seeds,
                timeout=config.migration_timeout,
                min_revision=config.minimum_downgrade_revision,
            )
            # Expose engine for seeder compatibility
            self._runner = None  # type: ignore[assignment]
            self._seeder = SmartSeeder(self._django_runner.engine)
            self._verifier = None  # type: ignore[assignment]
        else:
            from pathlib import Path as _Path

            if not _Path(config.alembic_ini).exists():
                raise MRTConfigError(
                    f"alembic.ini not found: '{config.alembic_ini}'\n\n"
                    "Check the path and update MRTConfig(alembic_ini=...) in your conftest.py.\n"
                    "See: https://croc100.github.io/pytest-mrt/quickstart/"
                )

            self._runner = MigrationRunner(config.alembic_ini, config.db_url)
            self._seeder = SmartSeeder(self._runner.engine)
            self._verifier = RollbackVerifier(
                self._runner,
                skip=config.skip,
                custom_seeds=config.custom_seeds,
                timeout=config.migration_timeout,
                min_revision=config.minimum_downgrade_revision,
            )
            self._django_runner = None  # type: ignore[assignment]
            self._django_verifier = None  # type: ignore[assignment]

    # ── migration control ──────────────────────────────────────────────

    def upgrade(self, revision: str = "head") -> None:
        self._runner.upgrade(revision)

    def upgrade_to(self, revision: str) -> None:
        """Upgrade to a specific revision. Equivalent to upgrade(revision)."""
        self._runner.upgrade(revision)

    def upgrade_one(self) -> None:
        """Upgrade exactly one step from the current revision."""
        self._runner.upgrade("+1")

    def downgrade(self, revision: str = "-1") -> None:
        self._runner.downgrade(revision)

    def downgrade_one(self) -> None:
        """Downgrade exactly one step from the current revision."""
        self._runner.downgrade("-1")

    def downgrade_to(self, revision: str) -> None:
        """Downgrade to a specific revision."""
        self._runner.downgrade(revision)

    def current_revision(self) -> str | None:
        """Return the current Alembic revision, or None if at base."""
        if self._django_mode:
            raise RuntimeError("current_revision() is not available in Django mode.")
        return self._runner.current_revision()

    # ── manual seeding ────────────────────────────────────────────────

    def seed(self, table: str, rows: list[dict], pk_col: str = "id") -> None:
        snap = SchemaSnapshot.capture(self._seeder.engine)
        if table not in snap.tables:
            raise ValueError(f"Table '{table}' not found in current schema")
        self._seeder.seed_custom(table, pk_col, rows)

    # ── static analysis ───────────────────────────────────────────────

    def check_static(self, versions_dir: str | None = None) -> list[RiskWarning]:
        """
        Run static analysis on the migration files.
        Includes built-in checks + any custom_checks registered in MRTConfig.
        severity_overrides from config are applied to the results.
        """
        if versions_dir is None:
            versions_dir = self._runner.get_versions_dir()

        warnings = analyze_migrations(
            versions_dir,
            min_revision=self._config.minimum_downgrade_revision,
        )

        # Apply custom checks
        if self._config.custom_checks:
            import re as _re
            from pathlib import Path

            from .core.ast_analyzer import MigrationAST

            for path in sorted(Path(versions_dir).glob("*.py")):
                source = path.read_text()
                m_rev = _re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
                revision = m_rev.group(1) if m_rev else path.stem
                m = MigrationAST(source, revision, path.name)
                if not m._parse_error:
                    for check_fn in self._config.custom_checks:
                        warnings.extend(check_fn(m))

        # Apply severity overrides
        if self._config.severity_overrides:
            for w in warnings:
                if w.pattern in self._config.severity_overrides:
                    w.severity = self._config.severity_overrides[w.pattern]

        return warnings

    def assert_no_static_errors(self, versions_dir: str | None = None) -> None:
        """Fail the test if static analysis finds any errors."""
        warnings = self.check_static(versions_dir)
        errors = [w for w in warnings if w.severity == "error"]
        if errors:
            lines = [f"  [{w.revision}] {w.pattern}: {w.message}" for w in errors]
            pytest.fail("Static analysis found unsafe migration patterns:\n" + "\n".join(lines))

    # ── assertions ────────────────────────────────────────────────────

    def assert_data_intact(self) -> None:
        failures = self._seeder.verify()
        if failures:
            pytest.fail("Rollback caused data loss:\n" + "\n".join(f"  - {f}" for f in failures))

    def check_revision(self, revision: str) -> RevisionResult:
        if self._django_mode:
            raise RuntimeError(
                "check_revision() is not available in Django mode. "
                "Use check_migration(app_label, migration_name) instead."
            )
        return self._verifier.check_revision(revision)

    def check_migration(self, app_label: str, migration_name: str) -> RevisionResult:
        """Django mode: check a single migration by app + name."""
        if not self._django_mode:
            raise RuntimeError(
                "check_migration() is only available in Django mode. "
                "Use check_revision() for Alembic projects."
            )
        from .adapters.django_runner import DjangoMigration

        return self._django_verifier.check_migration(
            DjangoMigration(app_label=app_label, name=migration_name)
        )

    def check_all(self, apps: list[str] | None = None) -> list[RevisionResult]:
        if self._django_mode:
            return self._django_verifier.check_all(apps=apps or self._config.django_apps)
        return self._verifier.check_all()

    def assert_reversible(self, revision: str = "head") -> None:
        if self._django_mode:
            raise RuntimeError(
                "assert_reversible() is not available in Django mode. "
                "Use assert_all_reversible() to test all Django migrations."
            )
        result = self._verifier.check_revision(revision)
        if not result.passed:
            pytest.fail(
                f"Migration {revision} is not safely reversible:\n{result.failure_summary()}"
            )

    def assert_all_reversible(self, apps: list[str] | None = None) -> None:
        from .reporter import print_check_all_summary

        if self._django_mode:
            results = self._django_verifier.check_all(apps=apps or self._config.django_apps)
        else:
            results = self._verifier.check_all()

        print_check_all_summary(results)
        failed = [r for r in results if not r.passed]
        if failed:
            lines = []
            for r in failed:
                lines.append(f"  revision {r.revision}:")
                lines.append(r.failure_summary())
            pytest.fail("Some migrations are not safely reversible:\n" + "\n".join(lines))

    # ── schema drift ──────────────────────────────────────────────────

    def assert_schema_matches(
        self,
        target_metadata=None,
        metadata_path: str | None = None,
    ) -> None:
        """Fail if the DB schema does not match the SQLAlchemy model definitions.

        For Django mode, delegates to ``manage.py makemigrations --check``.

        Args:
            target_metadata: A SQLAlchemy ``MetaData`` instance (or declarative
                ``Base``) to compare against.  When omitted, falls back to
                ``MRTConfig.target_metadata`` (an import-path string).
            metadata_path: Import path override, e.g. ``"myapp.models:Base"``.
                Takes precedence over ``MRTConfig.target_metadata``.
        """
        if self._django_mode:
            self._assert_django_no_drift()
            return

        if target_metadata is None:
            path = metadata_path or self._config.target_metadata
            if path is None:
                raise ValueError(
                    "assert_schema_matches() requires either a target_metadata argument "
                    "or MRTConfig(target_metadata='myapp.models:Base')."
                )
            target_metadata = load_metadata(path)

        diffs = compare_schema(self._runner.engine, target_metadata)
        if diffs:
            lines = [f"  {describe_diff(d)}" for d in diffs]
            pytest.fail(
                f"Schema drift detected ({len(diffs)} difference(s)):\n" + "\n".join(lines)
            )

    def _assert_django_no_drift(self) -> None:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit as exc:
            if exc.code != 0:
                pytest.fail(
                    "Schema drift: model changes detected that don't have migrations.\n"
                    "Run `python manage.py makemigrations` to generate them."
                )
        except Exception as exc:
            pytest.fail(
                f"assert_schema_matches() failed while checking Django migrations: {exc}\n"
                "Check that DJANGO_SETTINGS_MODULE is set correctly and all models can be imported."
            )

    def reset(self) -> None:
        self._seeder.reset()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "mrt_default_tests",
        help="Set to 'false' to disable auto-collected built-in MRT tests.",
        default="true",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "mrt: migration rollback test")


def pytest_sessionstart(session: pytest.Session) -> None:
    """Validate MRTConfig once at session start.

    Catches obvious setup errors (missing alembic.ini, etc.) before any test
    runs, so the user sees one clear error instead of the same message repeated
    for every collected test.
    """
    cfg: MRTConfig | None = getattr(session.config, "_mrt_config", None)
    if cfg is None:
        return

    cfg = _auto_detect_django(cfg)

    # Django mode — no alembic.ini needed
    if cfg.django_settings is not None:
        return

    from pathlib import Path

    if not Path(cfg.alembic_ini).exists():
        msg = (
            f"alembic.ini not found: '{cfg.alembic_ini}'\n\n"
            "Check the path and update MRTConfig(alembic_ini=...) in your conftest.py.\n\n"
            "If you are using Django migrations (not Alembic), set django_settings instead:\n\n"
            "    config._mrt_config = MRTConfig(\n"
            "        db_url=os.environ['TEST_DATABASE_URL'],\n"
            "        django_settings='myproject.settings_test',\n"
            "    )\n\n"
            "See: https://croc100.github.io/pytest-mrt/quickstart/"
        )
        pytest.exit(msg, returncode=4)


def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Prepend built-in default tests when MRTConfig is registered."""
    if getattr(config, "_mrt_config", None) is None:
        return
    if config.getini("mrt_default_tests") == "false":
        return

    from pathlib import Path

    try:
        from _pytest.python import Module as _PytestModule

        import pytest_mrt.default_tests as _dt

        dt_path = Path(_dt.__file__)
        module = _PytestModule.from_parent(session, path=dt_path)
        new_items: list[pytest.Item] = [i for i in module.collect() if isinstance(i, pytest.Item)]
        items[:0] = new_items
    except Exception as _exc:
        import warnings

        warnings.warn(
            f"pytest-mrt: failed to inject built-in default tests: {_exc}\n"
            "Set mrt_default_tests = 'false' in pytest.ini to suppress this warning.",
            stacklevel=2,
        )


@pytest.fixture
def mrt(request: pytest.FixtureRequest) -> Iterator[MRTFixture]:
    cfg: MRTConfig = getattr(request.config, "_mrt_config", None) or MRTConfig()
    # Capture error outside the except block to avoid "During handling of the
    # above exception, another exception occurred" in the traceback output.
    config_error: str | None = None
    try:
        fixture = MRTFixture(cfg)
    except MRTConfigError as e:
        config_error = str(e)
    if config_error is not None:
        pytest.fail(config_error, pytrace=False)
        return  # unreachable; keeps type checkers happy
    yield fixture
    fixture.reset()
