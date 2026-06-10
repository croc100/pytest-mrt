# Changelog

All notable changes to pytest-mrt are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [1.4.0] — 2026-06-10

### Added
- **`mrt check --format json`** — structured JSON output with `version`, `checked_at`, `summary` (errors/warnings counts), and `findings[]` per issue. Each finding includes a `fixable` flag. Use `--output <file>` to write to a file instead of stdout. Designed for CI integration and downstream tooling. (#67)
- **`mrt check --format html`** — generates a self-contained HTML safety report directly from `mrt check`. Replaces the separate `mrt report` command for most use cases. `--output` defaults to `mrt-report.html`. Exit codes consistent with table output. (#63)
- **`mrt check --watch`** — re-runs analysis automatically whenever a migration file changes. Uses 1-second stat polling with no extra dependencies. Ctrl-C exits cleanly. Only available with `--format table`. (#62)
- **`mrt check --min-revision <rev>`** — skip revisions at or older than the specified floor. Alembic: revision ID. Django: `app_label.migration_name`. Mirrors `MRTConfig.minimum_downgrade_revision`. Intersects with `--since` when both are given. (#66)
- **`MRTConfig.minimum_downgrade_revision`** — new config field for setting a permanent rollback testing floor in `conftest.py`. Now honoured by `check_static()` in the pytest fixture. (#66)
- **`mrt fix --apply` batch mode** — omit the file argument to fix all auto-fixable migrations in a directory. `--dry-run` previews without writing. `--dir` overrides auto-detection of the migrations directory. (#64)
- **Django squashmigrations detection** — two new rules:
  - **MRT601** (error): squashed migration (`replaces` attribute present) contains `RunPython` without `reverse_code` — rollback silently does nothing
  - **MRT602** (warning): migration filename contains "squash" but declares no `replaces` list — Django may apply it on top of the original migrations (#65)

### Fixed
- **MRT601 false positive** — `RunPython(forward, backward)` with `reverse_code` as the second positional argument was incorrectly flagged. Now checks both keyword and positional arguments.
- **`--min-revision` message showed inverted count** — the message reported the number of newer migrations being kept as "skipping N older", which was backwards.
- **`plugin.py` ignored `minimum_downgrade_revision`** — `check_static()` never passed `MRTConfig.minimum_downgrade_revision` to `analyze_migrations()`.
- **`mrt fix` batch auto-detection could scan project root** — removed the cwd fallback from `_find_migration_dir`; now exits with an error if no standard migrations directory is found, rather than recursively scanning the entire project.

---

## [1.3.1] — 2026-06-08

### Fixed
- **Error message quality** — when `alembic.ini` is missing, pytest-mrt now reports the error once at session start and exits cleanly instead of printing the same message for every collected test (typically 7 times with duplicate tracebacks). Fixes the "During handling of the above exception" noise in test output. (#55)
- **`mrt init` db_url quoting bug** — the generated `conftest.py` previously wrote `db_url=sqlite:///test.db` (invalid Python). Now correctly writes `db_url="sqlite:///test.db"`. Python expressions such as `os.environ['TEST_DATABASE_URL']` are passed through as-is. Prompts and next-steps output also improved. (#54)
- **`mrt check --since` empty-match warning** — `--since <ref>` that matched no migrations previously ran silently on the full set. Now exits with a clear warning and exit code 1. Also notes that graph checks (orphan / data-hole detection) are skipped in `--since` mode. (#52)
- **Django `mrt fix` unsupported operations** — `mrt fix` on Django migrations containing `AddField` (NOT NULL without default), `AlterField`, `RenameField`, or `RenameModel` now exits with code 1 and explains what must be fixed manually instead of silently producing no output. (#51)
- **Django migration downgrade with branch merges** — `downgrade(app, migration)` previously used the first parent as the rollback target, which caused sibling branch migrations to be incorrectly rolled back when a merge migration was applied. Fixed by building the rollback plan directly from `MigrationGraph.backwards_plan()`. (#50)

---

## [1.3.0] — 2026-06-08

### Added
- **`mrt check --since <revision>`** — scan only migrations added after a given migration revision. Eliminates re-scanning the full history on every PR in large codebases. Alembic: pass a revision ID (`--since a1b2c3d4`). Django: pass `app_label.migration_name` (`--since myapp.0010_add_email`).
- **pre-commit hook integration** — `.pre-commit-hooks.yaml` ships with pytest-mrt. Add `mrt check` to your pre-commit pipeline with two lines:
  ```yaml
  - repo: https://github.com/croc100/pytest-mrt
    rev: v1.3.0
    hooks:
      - id: mrt-check
  ```
- **Django-aware `mrt fix`** — `mrt fix <migration.py>` now works on Django migrations:
  - `RunSQL` without `reverse_sql`: adds `reverse_sql=migrations.RunSQL.noop`
  - `RunPython` without `reverse_code`: adds `reverse_code=migrations.RunPython.noop`
  - `RemoveField`: injects a `RunPython(backup, restore)` operation before the field removal. The backup function copies column data to `_mrt_backups` using keyset pagination (safe for large tables, no server-side cursors). The restore function writes the data back when rolling back.
  - `DeleteModel`: same as `RemoveField` but backs up all columns. The restore function uses `disable_constraint_checking()` to handle FK dependencies safely.
  - Inline type codec (`__mrt_enc` / `__mrt_dec`) injected once per migration — no runtime pytest-mrt dependency in production migrations. Handles `Decimal`, `datetime` (naive + tz-aware), `date`, `time`, `UUID`, `bytes`.
  - Use `--apply` to write the fix to the file.
- **`mrt clean-backups`** — removes backup rows from `_mrt_backups` after deployment is confirmed stable. Supports `--label` to remove a single migration's backup, `--list` to preview, `--yes` to skip confirmation.

### Changed
- `mrt fix` output for Django migrations includes a `[Django]` tag and a per-operation table (Line / Operation / Fix / Confidence).

---

## [1.2.0] — 2026-06-07

### Added
- **Rule codes**: Every static analysis rule now has a stable `MRTxxx` code (e.g. `MRT201` for DROP COLUMN). Codes appear in the CLI table and JSON output.
- **`# noqa: MRTxxx` suppression**: Silence specific warnings per-line using the ruff/flake8 convention that Python developers already know.
  - `# noqa: MRT201` — suppress one rule on that line
  - `# noqa: MRT201, MRT202` — suppress multiple rules
  - `# noqa` — suppress all MRT warnings on that line
  - `# mrt: ignore` — legacy alias, still supported for backwards compatibility

---


## [1.1.0] — 2026-06-07

### Added
- **Built-in default tests**: Five tests are now auto-collected when `MRTConfig` is registered in `conftest.py` — no imports required. Tests: `test_mrt_single_head`, `test_mrt_upgrade`, `test_mrt_downgrade_base`, `test_mrt_static_no_errors`, `test_mrt_schema_matches_models`. Disable with `mrt_default_tests = "false"` in `pytest.ini` / `pyproject.toml`.
- **Schema drift detection**: `MRTFixture.assert_schema_matches()` — fails if the DB schema after running all migrations does not match the SQLAlchemy model definitions. Accepts a `MetaData` instance or an import-path string (`"myapp.models:Base"`). Django mode delegates to `manage.py makemigrations --check`.
- **`mrt drift` CLI command**: `mrt drift myapp.models:Base --config alembic.ini --db-url sqlite:///test.db` — runs migrations to head, compares schema against models, prints a diff table, exits 1 on drift.
- **`MRTConfig.target_metadata`**: New field (`str | None`) — import path for the SQLAlchemy `Base` or `MetaData` used by `assert_schema_matches()` and `test_mrt_schema_matches_models`.

---

## [1.0.1] — 2026-06-06

### Fixed
- Replace `FileNotFoundError` in `MRTFixture` with `pytest.fail()` for cleaner test output when `alembic.ini` is missing (PR #22).

### Changed
- Extract hardcoded `"claude-opus-4-5"` model name to `config.DEFAULT_EXPLAIN_MODEL` constant; add `MRTConfig.explain_model` field to allow overriding the model without modifying CLI code (PR #22).
- Add `License :: OSI Approved :: MIT License` classifier to PyPI metadata (PR #25).

### Refactored
- Introduce `pytest_mrt/exceptions.py` with `MRTConfigError`; decouple `MRTFixture` from pytest by raising a plain Python exception instead of calling `pytest.fail()` directly — the `mrt` fixture wrapper now handles the conversion (PR #24).

---

## [1.0.0] — 2026-06-06

First stable release. All v1.0 target criteria met.

### Highlights

- **Full database coverage**: PostgreSQL, SQLite, MySQL/MariaDB, Oracle, SQL Server
- **Full migration framework coverage**: Alembic (static + dynamic) and Django (static + dynamic)
- **30+ static analysis patterns** with false-positive test suite and public accuracy report
- **Stable public API**: `MRTConfig`, `mrt` fixture, `mrt check` CLI — breaking changes will be versioned
- **Production/Stable** PyPI classifier

### Changed
- `Development Status` classifier: `4 - Beta` → `5 - Production/Stable`
- Version: `0.9.0` → `1.0.0`

---

## [0.9.0] — 2026-06-06

### Added
- **Django dynamic rollback verification**: `DjangoMigrationRunner` and `DjangoRollbackVerifier` — runs `manage.py migrate <app> <prev>` programmatically and verifies schema/data restoration. Enable with `MRTConfig(django_settings="myproject.settings_test", db_url=...)`.
- **`MRTConfig.django_settings`**: Django settings module to activate Django mode in the `mrt` fixture.
- **`MRTConfig.django_apps`**: restrict dynamic testing to specific Django app labels.
- **`MRTConfig.django_project_dir`**: optional path added to `sys.path` before Django import.
- **`MRTFixture.check_migration(app, name)`**: check a single Django migration by app label + name.
- **`MRTFixture.check_all(apps=[...])`**: test all Django migrations, optionally filtered by app.
- **Oracle support**: `pip install pytest-mrt[oracle]` — uses `python-oracledb` driver; CI tests against Oracle Free 23c.
- **SQL Server support**: `pip install pytest-mrt[mssql]` — uses `pymssql` driver; CI tests against SQL Server 2022.
- **`tests/test_oracle.py`**: Oracle integration tests (reversible migration, noop downgrade, chain).
- **`tests/test_mssql.py`**: SQL Server integration tests (same coverage).
- **`tests/test_django_dynamic.py`**: Django dynamic rollback tests with an in-process SQLite setup.
- **CI**: `test-django` job (Django 4.2/5.0/5.1 matrix), `test-oracle` job, `test-mssql` job added.
- **GitHub Discussions** enabled on the repository.

### Changed
- `MigrationRunner` now uses `NullPool` for all database dialects (previously only SQLite and MySQL). Prevents connection leaks across migrations in all test environments.

---

## [0.8.0] — 2026-06-06

### Added
- **MySQL CI**: new `test-mysql` job in CI runs integration tests against MySQL 8 on every push and pull request.
- **`docs/accuracy.md`**: per-pattern accuracy report documenting what each of the 30 Alembic patterns and 8 Django patterns catches and doesn't catch, with false-positive risk ratings.
- **3 new static patterns** (27 → 30):
  - `DROP FOREIGN KEY without reverse` — `op.drop_constraint(..., type_='foreignkey')` in upgrade without matching `op.create_foreign_key()` in downgrade.
  - `CREATE TRIGGER without DROP` — raw SQL `CREATE TRIGGER` in upgrade without a corresponding `DROP TRIGGER` in downgrade.
  - `CREATE TYPE without DROP` — `CREATE TYPE` (PostgreSQL ENUM/composite) in upgrade without `DROP TYPE` in downgrade.
- **Actionable error messages**: each warning now includes a concrete suggestion, e.g. "Add `op.drop_column('users', 'email')` to downgrade()" instead of a generic description.
- **False-positive test suite** (`tests/test_false_positives.py`): 30+ cases that must not trigger any warning, guarding against regressions in pattern specificity.
- **API stability declaration** (`docs/api.md`): `MRTConfig`, `mrt` fixture, and `mrt check` CLI are declared stable; internal modules are marked private.
- **Exit code breakdown**: `mrt check` now returns `0` (no findings), `1` (warnings only), or `2` (one or more errors), enabling fine-grained CI gating.
- **PostgreSQL CI** (`test-postgres` job): runs the full `tests/test_postgres.py` suite against PostgreSQL 16 on every push.

### Changed
- **`migration_timeout` default**: changed from `None` (unlimited) to `60` seconds. Migrations hanging longer than 60 seconds now fail with an actionable message instead of blocking the test suite indefinitely. Override with `MRTConfig(migration_timeout=None)` to restore unlimited behavior.

### Improved
- **Test coverage**: 45% → 88%, covering CLI, plugin, Django detector, HTML reporter, seeder, and verifier.
- **MySQL `NullPool`**: `MigrationRunner` now passes `poolclass=NullPool` for MySQL connections, preventing connection pool exhaustion during parallel test runs.
- **Python 3.13 support**: CI matrix extended to include Python 3.13; all tests pass.
- **CI linting**: ruff and mypy checks enforced in CI on every push.

---

## [0.7.0] — 2026-06-05

### Added
- **Cross-migration chain analysis** (`core/graph.py`): new `MigrationGraph` engine builds a full dependency graph and detects patterns invisible to per-file analysis:
  - `Data hole chain` — migration A drops column X, migration B re-adds X; rolling back both restores the schema but permanently loses the original data
  - `Orphaned migration` — migrations unreachable from any head that may run unexpectedly during downgrade
- **Plugin API**: `MRTConfig(custom_checks=[fn])` — register additional static analysis functions that run alongside built-in checks. Functions receive a `MigrationAST` and return `list[RiskWarning]`.
- **Severity overrides**: `MRTConfig(severity_overrides={"INDEX without CONCURRENTLY": "error"})` — promote or demote any pattern's severity project-wide.
- **`MRTFixture.check_static()`** — run static analysis (built-in + custom checks) from a test, without needing a database.
- **`MRTFixture.assert_no_static_errors()`** — convenience assertion that fails the test if any static error is detected.
- **`MRTConfig.migration_timeout`** — per-migration timeout in seconds.

### Fixed
- **AST scope bug**: `_walk_calls` previously used `ast.walk` which recursed into nested `FunctionDef` nodes inside `upgrade()`/`downgrade()`. Helper functions defined inside migration functions were incorrectly attributed to the outer function's call list, causing false positives and missed detections.
- **Batch context propagation**: `_is_batch_context` was fragile when the function scope changed; replaced with explicit `in_batch` flag propagation through the AST traversal. `op.batch_alter_table` calls now reliably detected.
- **MySQL double-quote bug in custom seeds**: `verifier._build_seeder` used hardcoded `"table"` double-quote identifiers for custom seed rows, breaking MySQL. Now uses dialect-aware `_q()`.
- **`bulk_insert` reverse check logic**: was accepting any `op.execute()` call in downgrade as a valid reverse for `op.bulk_insert()`. Now requires `op.delete()` or an `execute()` containing a `DELETE` statement.

### Improved
- **Seeder — ENUM support**: queries actual ENUM values from PostgreSQL (`pg_enum`) and MySQL (`INFORMATION_SCHEMA`) rather than generating invalid strings.
- **Seeder — unique constraint awareness**: inspects DB unique constraints before inserting; appends `row_index` to string/int values in unique columns to prevent collision failures that previously caused silent seed skips.
- **Seeder — auto-PK detection**: detects `SERIAL`/`BIGSERIAL` and `nextval()` server defaults in addition to type string matching, correctly skipping PostgreSQL sequence-backed PKs.
- **Seeder — type normalization in `verify()`**: `_normalize_for_compare` strips timezone/microseconds from datetimes, converts `Decimal` to `float`, and `memoryview` to `bytes` before equality comparison — eliminates false failures from driver-specific type representations.
- **Verifier — O(n) `check_all`**: previously called `downgrade_base()` before every migration check, resulting in O(n²) upgrade operations for a chain of n migrations. Now O(n): after `check_revision`, the DB is at the pre-migration state and a single `upgrade()` advances to the next revision.
- **Verifier — state recovery**: `check_revision` now catches unexpected exceptions and attempts to restore the DB to the pre-check state, preventing a failed migration check from leaving the database in an unknown state for subsequent checks.
- **Detector — `ADD COLUMN with DEFAULT`**: split into two separate checks distinguishing Python-side defaults (always rewrites table) from `server_default` (safe on PostgreSQL 11+). Removed false positive for PostgreSQL 11+.

---

## [0.6.1] — 2026-06-05

### Fixed
- **`sa.text()` SQL extraction**: `MigrationAST.sql_content()` now extracts SQL from `op.execute(sa.text("..."))` patterns. Previously, SQL inside `sa.text()` wrappers was silently skipped, causing TRUNCATE, DROP VIEW, ENUM, and other SQL-based checks to miss these calls.
- **`op.bulk_insert()` reverse check**: fixed logic bug where any `op.execute()` in downgrade was accepted as a valid reverse for `op.bulk_insert()`.
- **`_check_sql_text_wrapper` stub removed**: was a no-op placeholder; SQL extraction is now handled transparently by `sql_content()`.

### Added
- **Line number column** in `mrt check` table output — each finding now shows the exact source line, making it easier to navigate directly to the problem.

---

## [0.6.0] — 2026-05-XX

### Added
- **AST-based static analysis**: replaced regex-based detection with full Python AST parsing — eliminates false positives from commented-out code, understands keyword arguments, and provides line numbers.
- **Django migrations support**: `mrt check` auto-detects Django migration files and runs a separate set of Django-specific checks (RemoveField, DeleteModel, AddField NOT NULL, AlterField NOT NULL, RunSQL without reverse_sql, RunSQL with TRUNCATE/DROP, RunPython without reverse_code, AddIndex without atomic=False).
- **`context.execute()` detection**: detects `context.execute()` / `ctx.execute()` as alternatives to `op.execute()` with the same risks.
- **`op.bulk_insert()` without reverse** detection.

### Improved
- 24 → 27+ static analysis patterns.

---

## [0.5.0] — 2026-04-XX

### Added
- `mrt init` — scaffolds `conftest.py` and test file automatically.
- `--skip` / `MRTConfig(skip={...})` — skip specific revisions with a documented reason.
- `--custom-seeds` / `MRTConfig(custom_seeds={...})` — override auto-generated seed data per table.
- JSON output format (`mrt check --format json`).
- Risk score per revision (`RevisionResult.risk_score`).

---

## [0.4.0] — 2026-03-XX

### Added
- `mrt fix` — auto-generates a missing or broken `downgrade()` function, shows a diff, applies with `--apply`.
- `mrt report` — generates an HTML safety report of the entire migration history.
- `mrt explain` — AI-powered plain-English explanation of what a migration does (`pip install pytest-mrt[ai]`).

---

## [0.3.0] — 2026-02-XX

### Added
- `batch_alter_table` context detection — drop/drop-constraint inside batch operations correctly attributed and flagged.
- `NOT NULL` via raw SQL without reverse detection.
- `NOT NULL` without restoring `nullable` in downgrade detection.

---

## [0.2.0] — 2026-01-XX

### Added
- `mrt check` CLI command — static analysis without a database.
- `--strict` flag — exit 1 on warnings as well as errors.
- `mrt version` command.

---

## [0.1.0] — 2025-12-XX

### Added
- Initial release: `mrt` pytest fixture with `assert_all_reversible()`.
- SQLite and PostgreSQL dynamic verification.
- 14 static analysis patterns via regex.
- `SmartSeeder` — auto-seeds rows before each migration and verifies data survival after rollback.
