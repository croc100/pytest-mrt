# API Reference

Complete reference for all public classes, methods, and CLI commands.

---

## `MRTConfig`

```python
from pytest_mrt import MRTConfig
```

Configuration object passed to `pytest_configure` to set up migration rollback testing.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `alembic_ini` | `str` | `"alembic.ini"` | Path to your `alembic.ini` file (ignored in Django mode) |
| `db_url` | `str` | `""` | SQLAlchemy database URL for the test database |
| `seed_rows` | `int` | `3` | Number of rows to seed per table during rollback verification |
| `skip` | `dict[str, str]` | `{}` | Revisions to skip, with documented reasons |
| `severity_overrides` | `dict[str, str]` | `{}` | Override severity of specific risk patterns |
| `custom_seeds` | `dict[str, Callable]` | `{}` | Custom seed functions per table |
| `custom_checks` | `list[Callable]` | `[]` | Additional static analysis check functions (Alembic only) |
| `migration_timeout` | `int \| None` | `60` | Per-migration timeout in seconds (`None` = no limit) |
| `minimum_downgrade_revision` | `str \| None` | `None` | Skip revisions at or before this floor in `check_all()` |
| `target_metadata` | `str \| None` | `None` | Import path for SQLAlchemy `Base`/`MetaData` used by `assert_schema_matches()` |
| `django_settings` | `str \| None` | `None` | Django settings module — enables Django mode |
| `django_apps` | `list[str] \| None` | `None` | Restrict dynamic testing to specific Django app labels |
| `django_project_dir` | `str \| None` | `None` | Path added to `sys.path` before Django import |
| `explain_model` | `str` | `"claude-opus-4-5"` | Claude model used by `mrt explain` |

### Example (Alembic)

```python
# conftest.py
import os
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url=os.environ["TEST_DATABASE_URL"],
        seed_rows=5,
        skip={
            "abc123": "Intentional one-way data migration. Reviewed 2025-01-15. See ADR-007."
        },
        severity_overrides={
            "INDEX without CONCURRENTLY": "error",
        },
        custom_seeds={
            "users": lambda: [{"id": 1, "name": "Alice", "email": "alice@example.com"}],
        },
        minimum_downgrade_revision="a1b2c3d4",
        target_metadata="myapp.models:Base",
    )
```

### Example (Django)

```python
# conftest.py
import os
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        db_url=os.environ["TEST_DATABASE_URL"],
        django_settings="myproject.settings_test",
        django_apps=["users", "orders"],
    )
```

### `skip`

Documents why a specific revision is exempt from rollback testing. Skipped revisions appear in reports as "skipped" (not failed).

```python
skip={
    "1a2b3c4d": "RunPython data migration — irreversible by design. ADR-12.",
    "5e6f7a8b": "Adds NOT NULL column to 500M-row table — zero-downtime handled externally.",
}
```

### `severity_overrides`

Promotes warnings to errors (or demotes errors to warnings) for specific risk pattern names. Pattern names match the `pattern` field in `mrt check --format json` output.

```python
severity_overrides={
    "INDEX without CONCURRENTLY": "error",
    "noop downgrade": "warning",
}
```

### `custom_checks`

Each function receives a `MigrationAST` and returns a list of `RiskWarning` objects. Custom checks run in addition to the built-in checks. Alembic mode only.

```python
from pytest_mrt.core.ast_analyzer import MigrationAST
from pytest_mrt.core.detector import RiskWarning

def check_no_truncate(m: MigrationAST) -> list[RiskWarning]:
    if "TRUNCATE" in m.source.upper():
        return [RiskWarning(
            revision=m.revision,
            file=m.filename,
            pattern="TRUNCATE in migration",
            message="TRUNCATE destroys all rows. Use DELETE with a WHERE clause instead.",
            severity="error",
        )]
    return []

config = MRTConfig(custom_checks=[check_no_truncate])
```

---

## `MRTFixture`

The `mrt` pytest fixture. Obtained via the `mrt` fixture parameter — do not instantiate directly.

```python
def test_migrations(mrt):
    mrt.assert_all_reversible()
```

### Migration control

> **Django mode**: `upgrade_*`, `downgrade_*`, and `current_revision()` are Alembic-only and raise `RuntimeError` in Django mode. Use `check_migration()` / `check_all()` for Django projects.

#### `mrt.upgrade(revision="head")`

Run `alembic upgrade` to the given revision.

```python
mrt.upgrade("head")
mrt.upgrade("001abc")
```

#### `mrt.upgrade_to(revision)`

Upgrade to a specific revision. Equivalent to `upgrade(revision)`.

```python
mrt.upgrade_to("abc123")
```

#### `mrt.upgrade_one()`

Upgrade exactly one step from the current revision.

```python
mrt.upgrade_one()
```

#### `mrt.downgrade(revision="-1")`

Run `alembic downgrade` by one step or to a specific revision.

```python
mrt.downgrade()         # roll back one step
mrt.downgrade("base")   # roll back to empty schema
```

#### `mrt.downgrade_one()`

Downgrade exactly one step from the current revision.

```python
mrt.downgrade_one()
```

#### `mrt.downgrade_to(revision)`

Downgrade to a specific revision.

```python
mrt.downgrade_to("abc123")
mrt.downgrade_to("base")
```

#### `mrt.current_revision() → str | None`

Return the current Alembic revision ID, or `None` if at base.

```python
rev = mrt.current_revision()
assert rev == "abc123"
```

---

### Static analysis

> Not available in Django mode — raises `RuntimeError`. Use `check_migration()` / `check_all()` for Django rollback testing.

#### `mrt.check_static(versions_dir=None) → list[RiskWarning]`

Run static analysis on migration files. Returns all detected risk warnings.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `versions_dir` | `None` | Path to Alembic versions directory. Defaults to the path from `alembic.ini`. |

```python
warnings = mrt.check_static()
errors = [w for w in warnings if w.severity == "error"]
```

#### `mrt.assert_no_static_errors(versions_dir=None)`

Fail the test if static analysis finds any `error`-severity risks.

```python
def test_no_unsafe_migrations(mrt):
    mrt.assert_no_static_errors()
```

---

### Rollback verification

#### `mrt.check_revision(revision) → RevisionResult`

Test a single Alembic revision for safe reversibility. The database must be at the state just _before_ this revision when called. Alembic mode only.

```python
mrt.upgrade("001abc")
result = mrt.check_revision("002def")
assert result.passed
```

#### `mrt.check_migration(app_label, migration_name) → RevisionResult`

Test a single Django migration by app label and migration name. Django mode only.

```python
result = mrt.check_migration("users", "0003_add_phone")
assert result.passed
```

#### `mrt.check_all(apps=None) → list[RevisionResult]`

Test every migration in the chain. Runs in O(n) upgrade operations. In Django mode, pass `apps` to restrict to specific app labels (overrides `MRTConfig.django_apps` for this call).

```python
results = mrt.check_all()
failed = [r for r in results if not r.passed]
```

#### `mrt.assert_reversible(revision="head")`

Assert that a single Alembic revision is safely reversible. Fails the test if not. Alembic mode only.

```python
def test_latest_migration(mrt):
    mrt.assert_reversible()
```

#### `mrt.assert_all_reversible(apps=None)`

Assert every migration in the chain is safely reversible. Prints a summary table and fails if any migration fails. Works for both Alembic and Django.

```python
def test_all_migrations(mrt):
    mrt.assert_all_reversible()
```

---

### Data integrity

#### `mrt.seed(table, rows, pk_col="id")`

Manually seed rows into a table at the current schema state. Combine with step control methods for mid-chain data assertions.

```python
def test_data_migration(mrt):
    mrt.upgrade_to("abc123")
    mrt.seed("users", [{"id": 1, "name": "Alice"}])
    mrt.upgrade_one()
    mrt.downgrade_one()
    mrt.assert_data_intact()
```

#### `mrt.assert_data_intact()`

Assert that all previously seeded rows still exist and have their original values.

#### `mrt.reset()`

Clear the internal seed state. Called automatically at fixture teardown.

---

### Schema drift

#### `mrt.assert_schema_matches(target_metadata=None, metadata_path=None)`

Fail if the DB schema does not match the SQLAlchemy model definitions. In Django mode, delegates to `manage.py makemigrations --check`.

```python
from myapp.models import Base

def test_no_drift(mrt):
    mrt.upgrade("head")
    mrt.assert_schema_matches(Base)
```

Or configure once via `MRTConfig(target_metadata="myapp.models:Base")` and rely on the built-in `test_mrt_schema_matches_models`.

---

## `RevisionResult`

Return type of `mrt.check_revision()`, `mrt.check_migration()`, and elements of `mrt.check_all()`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `revision` | `str` | The revision ID (Alembic) or `app/name` (Django) |
| `passed` | `bool` | `True` if rollback was safe |
| `skipped` | `bool` | `True` if this revision is in `MRTConfig.skip` |
| `skip_reason` | `str` | The documented reason for skipping |
| `failures` | `list[str]` | Human-readable failure messages |
| `risk_score` | `int` | 0–100 risk score (25 per failure, capped at 100) |

#### `result.failure_summary() → str`

Returns a formatted string of all failure messages.

```python
result = mrt.check_revision("001abc")
if not result.passed:
    print(result.failure_summary())
```

---

## `RiskWarning`

Returned by `mrt.check_static()` and by `custom_checks` functions.

| Attribute | Type | Description |
|-----------|------|-------------|
| `revision` | `str` | Revision ID or filename stem |
| `file` | `str` | Migration filename |
| `pattern` | `str` | Short pattern name (e.g. `"DROP COLUMN in upgrade"`) |
| `message` | `str` | Human-readable explanation |
| `severity` | `str` | `"error"` or `"warning"` |
| `line` | `int \| None` | Line number in the migration file |
| `code` | `str` | Rule code (e.g. `"MRT201"`) |

---

## CLI Commands

### `mrt check <versions_dir>`

Statically analyze migration files for rollback risk patterns. Auto-detects Django migrations.

```
mrt check alembic/versions/
mrt check myapp/migrations/ --strict
mrt check alembic/versions/ --format json --output report.json
mrt check alembic/versions/ --format html --output report.html
mrt check alembic/versions/ --watch
mrt check alembic/versions/ --since a1b2c3d4
mrt check alembic/versions/ --check-compat
```

| Option | Default | Description |
|--------|---------|-------------|
| `--strict` | `False` | Treat warnings as errors (exit 2) |
| `--format` / `-f` | `table` | Output format: `table`, `json`, or `html` |
| `--output` / `-o` | `None` | Write output to file. For `--format html` defaults to `mrt-report.html`. |
| `--since` | `None` | Only check migrations added after this revision. Alembic: revision ID. Django: `app_label.migration_name`. Graph checks (orphan, data-hole detection) are skipped when `--since` is active. |
| `--min-revision` | `None` | Skip revisions at or older than this point. Alembic: revision ID. Django: `app_label.migration_name`. Mirrors `MRTConfig.minimum_downgrade_revision`. |
| `--watch` / `-w` | `False` | Re-run automatically when migration files change. `--format table` only. Ctrl-C to stop. |
| `--check-compat` | `False` | Also run rolling-deploy compatibility checks (MRT701–MRT705). Alembic only. |

**Exit codes:** `0` = no findings, `1` = warnings only, `2` = one or more errors (or warnings with `--strict`)

**JSON output schema:**

```json
{
  "version": "1.6.0",
  "checked_at": "2026-06-17T12:00:00Z",
  "summary": { "total_issues": 1, "errors": 1, "warnings": 0 },
  "findings": [
    {
      "file": "001_create_users.py",
      "line": 12,
      "rule": "MRT201",
      "severity": "error",
      "pattern": "DROP COLUMN in upgrade",
      "message": "op.drop_column('users', 'email') — data permanently lost on rollback"
    }
  ]
}
```

---

### `mrt drift <metadata_path>`

Compare the live DB schema against SQLAlchemy model definitions and print a diff.

```
mrt drift myapp.models:Base --config alembic.ini --db-url sqlite:///test.db
```

Exits `1` if drift is detected, `0` if schema matches.

---

### `mrt init`

Scaffold `conftest.py` and `test_migrations.py` for your project. Auto-detects `alembic.ini`.

```
mrt init
```

---

### `mrt explain <migration_file>`

Explain a migration in plain English using Claude AI.

```
mrt explain alembic/versions/001_create_users.py
```

Requires: `pip install pytest-mrt[ai]` and `ANTHROPIC_API_KEY` environment variable.

Override the model with `MRTConfig(explain_model="claude-haiku-4-5-20251001")`.

---

### `mrt version`

Print the installed version.

```
mrt version
```
