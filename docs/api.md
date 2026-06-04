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
| `alembic_ini` | `str` | `"alembic.ini"` | Path to your `alembic.ini` file |
| `db_url` | `str` | `""` | SQLAlchemy database URL for the test database |
| `seed_rows` | `int` | `3` | Number of rows to seed per table during rollback verification |
| `skip` | `dict[str, str]` | `{}` | Revisions to skip, with documented reasons |
| `severity_overrides` | `dict[str, str]` | `{}` | Override severity of specific risk patterns |
| `custom_seeds` | `dict[str, Callable]` | `{}` | Custom seed functions per table |
| `custom_checks` | `list[Callable]` | `[]` | Additional static analysis check functions |
| `migration_timeout` | `int \| None` | `None` | Per-migration timeout in seconds (`None` = no limit) |

### Example

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

Promotes warnings to errors (or demotes errors to warnings) for specific risk pattern names. Pattern names match the `pattern` field in the JSON output of `mrt check`.

```python
severity_overrides={
    "INDEX without CONCURRENTLY": "error",      # treat as error in your org
    "noop downgrade": "warning",                 # already handled by your deploy process
}
```

### `custom_checks`

Each function receives a `MigrationAST` and returns a list of `RiskWarning` objects. Custom checks run in addition to the built-in checks.

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

#### `mrt.upgrade(revision="head")`

Run `alembic upgrade` to the given revision.

```python
mrt.upgrade("head")     # upgrade to latest
mrt.upgrade("001abc")   # upgrade to a specific revision
```

#### `mrt.downgrade(revision="-1")`

Run `alembic downgrade` by one step (or to a specific revision).

```python
mrt.downgrade()         # roll back one step
mrt.downgrade("base")   # roll back to empty schema
```

---

### Static analysis

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

Test a single revision for safe reversibility. The database must be at the state just _before_ this revision when called.

Returns a `RevisionResult` (see below).

```python
mrt.upgrade("001abc")
result = mrt.check_revision("002def")
assert result.passed
```

#### `mrt.check_all() → list[RevisionResult]`

Test every migration in the chain. Internally runs in O(n) upgrade operations.

```python
results = mrt.check_all()
failed = [r for r in results if not r.passed]
```

#### `mrt.assert_reversible(revision="head")`

Assert that a single revision is safely reversible. Fails the test if not.

```python
def test_latest_migration(mrt):
    mrt.assert_reversible()
```

#### `mrt.assert_all_reversible()`

Assert every migration in the chain is safely reversible. Prints a summary table and fails if any migration fails.

```python
def test_all_migrations(mrt):
    mrt.assert_all_reversible()
```

---

### Data integrity

#### `mrt.seed(table, rows, pk_col="id")`

Manually seed rows into a table (currently open schema).

```python
mrt.upgrade("001abc")
mrt.seed("users", [{"id": 1, "name": "Alice"}])
```

#### `mrt.assert_data_intact()`

Assert that all previously seeded rows still exist and have their original values.

```python
mrt.upgrade("head")
mrt.downgrade()
mrt.assert_data_intact()
```

#### `mrt.reset()`

Clear the internal seed state. Called automatically at fixture teardown.

---

## `RevisionResult`

Return type of `mrt.check_revision()` and elements of `mrt.check_all()`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `revision` | `str` | The Alembic revision ID |
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
| `pattern` | `str` | Short pattern name (e.g. `"DROP COLUMN"`) |
| `message` | `str` | Human-readable explanation |
| `severity` | `str` | `"error"` or `"warning"` |
| `line` | `int \| None` | Line number in the migration file |

---

## CLI Commands

### `mrt check <versions_dir>`

Statically analyze migration files for rollback risks.

```
mrt check alembic/versions/
mrt check alembic/versions/ --strict
mrt check alembic/versions/ --format json
```

| Option | Default | Description |
|--------|---------|-------------|
| `--strict` | `False` | Exit 1 on warnings as well as errors |
| `--format` / `-f` | `table` | Output format: `table` or `json` |

**Exit codes:** `0` = safe, `1` = errors found (or warnings with `--strict`)

**JSON output schema:**

```json
[
  {
    "revision": "001abc",
    "file": "001_create_users.py",
    "pattern": "DROP COLUMN",
    "severity": "error",
    "message": "op.drop_column('users', 'email') — data permanently lost...",
    "line": 12
  }
]
```

---

### `mrt fix <migration_file>`

Suggest or apply a missing/broken `downgrade()` function.

```
mrt fix alembic/versions/001_create_users.py
mrt fix alembic/versions/001_create_users.py --apply
```

| Option | Default | Description |
|--------|---------|-------------|
| `--apply` | `False` | Write the suggested fix to the file |

---

### `mrt report <versions_dir>`

Generate an HTML safety report for all migrations.

```
mrt report alembic/versions/
mrt report alembic/versions/ --output report.html
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output` / `-o` | `migration_report.html` | Output file path |

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

---

### `mrt version`

Print the installed version.

```
mrt version
```
