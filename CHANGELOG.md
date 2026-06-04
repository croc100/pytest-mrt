# Changelog

All notable changes to pytest-mrt are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

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
