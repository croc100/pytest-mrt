# CLI & Fixture Reference

pytest-mrt has two interfaces:

- **`mrt` CLI** — analysis, fixing, and reporting without a database
- **`mrt` pytest fixture** — dynamic verification against a real database

## Command overview

| Command | What it does | Needs DB? |
|---|---|---|
| `mrt check <dir>` | Static analysis — 46 risk patterns | No |
| `mrt check <dir> --since <ref>` | Incremental scan — only migrations after a given revision | No |
| `mrt check <dir> --min-revision <rev>` | Skip revisions at or older than a floor revision | No |
| `mrt check <dir> --format json` | Structured JSON output for CI / downstream tools | No |
| `mrt check <dir> --format html` | Self-contained HTML safety report | No |
| `mrt check <dir> --watch` | Re-run on file change (dev mode) | No |
| `mrt fix <file>` | Auto-generate reverse operations for a single file | No |
| `mrt fix --apply` | Batch-fix all auto-fixable migrations in a directory | No |
| `mrt clean-backups` | Remove `_mrt_backups` rows after stable deployment | Yes |
| `mrt drift` | Compare live DB schema against ORM models | Yes |
| `mrt report <dir>` | HTML safety report of entire migration history | No |
| `mrt explain <file>` | AI explanation in plain English | No (needs API key) |
| `mrt version` | Show installed version | No |

---

## CLI: `mrt check`

Scans migration files for dangerous patterns. Fast, no database needed.

```bash
mrt check <path-to-versions-dir>
```

### Finding your versions directory

It's where your migration files (`.py` files with `revision = '...'`) live.

```
your-project/
├── alembic.ini
└── migrations/
    ├── env.py
    └── versions/         ← this is what you pass to mrt check
        ├── 001_create_users.py
        ├── 002_add_email.py
        └── 003_drop_phone.py
```

```bash
mrt check migrations/versions/
```

### Options

| Option | Description | Default |
|---|---|---|
| `--strict` | Also fail on warnings, not just errors | Off |
| `--format` | Output format: `table`, `json`, `html` | `table` |
| `--output <file>` | Write output to file (for `--format json` or `--format html`) | stdout / `mrt-report.html` |
| `--since <ref>` | Only check migrations after this revision (CI incremental scan) | Off |
| `--min-revision <rev>` | Skip revisions at or older than this floor | Off |
| `--watch` | Re-run on file change. Ctrl-C to stop. (`--format table` only) | Off |

#### `--since` — incremental scanning

In large codebases, scanning the full migration history on every PR is wasteful. `--since` limits the scan to migrations that come *after* the given revision in the migration dependency chain. The revision itself is excluded.

**Alembic** — pass a revision ID:

```bash
mrt check migrations/versions/ --since a1b2c3d4
```

Only revisions whose `down_revision` ancestry includes `a1b2c3d4` are scanned.

**Django** — pass `app_label.migration_name`:

```bash
mrt check myapp/migrations/ --since myapp.0010_add_email
```

`app_label` is the name of the Django app directory. `migration_name` is the migration filename **without** the `.py` extension:

```
your-project/
├── myapp/                          ← app_label: myapp
│   └── migrations/
│       ├── 0001_initial.py
│       ├── 0010_add_email.py       ← migration_name: 0010_add_email
│       └── 0011_add_phone.py       ← will be scanned (depends on 0010)
└── accounts/                       ← app_label: accounts
    └── migrations/
        └── 0001_initial.py
```

Only migrations that depend on `myapp.0010_add_email` (directly or transitively, across all apps) are scanned.

This is the recommended CI pattern: pass the last migration on the base branch so only the PR's new migrations are scanned.

> **Note:** When `--since` is active, graph-level checks (orphan detection, data-hole analysis) are skipped because they require the full migration history. Run without `--since` periodically or in a nightly job to catch graph-level issues.

#### Behavior when `--since` matches nothing

If the revision or migration name is not found in the target directory, `mrt check` prints a warning and exits with code `1`:

```
Warning: --since myapp.0010_add_email matched no migrations. Check the revision ID and try again.
```

Common causes:

- Typo in the app label or migration name (format must be `app_label.migration_name`, dot-separated)
- Wrong directory passed — for Django, pass `myapp/migrations/`, not the project root
- The migration has been squashed or renamed

#### `--min-revision` — permanent rollback floor

Unlike `--since` (which is for CI incremental scans), `--min-revision` is for permanently excluding old migrations you've decided not to test.

```bash
mrt check migrations/versions/ --min-revision a1b2c3d4
```

Only migrations that are newer than (descendants of) `a1b2c3d4` are analysed. If both `--since` and `--min-revision` are given, the stricter bound wins (intersection).

You can also set this permanently in `conftest.py`:

```python
config._mrt_config = MRTConfig(
    alembic_ini="alembic.ini",
    db_url="sqlite:///test.db",
    minimum_downgrade_revision="a1b2c3d4",
)
```

#### `--format json` — structured output

```bash
mrt check migrations/versions/ --format json
mrt check migrations/versions/ --format json --output results.json
```

Output schema:

```json
{
  "version": "1.4.0",
  "checked_at": "2026-06-10T11:00:00Z",
  "summary": { "total_issues": 2, "errors": 1, "warnings": 1 },
  "findings": [
    {
      "file": "003_drop_column.py",
      "line": 14,
      "rule": "MRT103",
      "severity": "error",
      "pattern": "DROP COLUMN in upgrade",
      "message": "Column dropped — data permanently lost on rollback",
      "fixable": false
    }
  ]
}
```

Pipe to `jq` for filtering:

```bash
mrt check migrations/versions/ --format json | jq '.findings[] | select(.severity == "error")'
```

#### `--format html` — HTML report

```bash
mrt check migrations/versions/ --format html
mrt check migrations/versions/ --format html --output report.html
```

Generates a self-contained HTML file (no external dependencies) with a summary table and per-revision cards. Exit codes are identical to table output.

#### `--watch` — dev mode

```bash
mrt check migrations/versions/ --watch
```

Re-runs the check whenever any `.py` file in the directory changes. Uses 1-second polling with no extra dependencies. Press Ctrl-C to stop.

Only available with `--format table`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | No problems found |
| `1` | Warnings found (without `--strict`), or `--since`/`--min-revision` matched no migrations |
| `2` | Errors found, or warnings found with `--strict` |

Use exit code `2` to fail the pipeline on actionable findings:

```bash
mrt check migrations/versions/ --strict
# exits 0 (clean) or 2 (errors or warnings)
# exits 1 only if warnings exist but --strict is not set
```

### Example output

```
                         Rollback Risk Analysis
╭──────────┬─────────────────────────────┬─────────┬──────┬─────────┬──────────────────────────────────╮
│ Revision │ Pattern                     │ Sev     │ Line │ Code    │ Message                          │
├──────────┼─────────────────────────────┼─────────┼──────┼─────────┼──────────────────────────────────┤
│ 003      │ DROP COLUMN in upgrade      │ error   │   14 │ MRT103  │ Column dropped — data            │
│          │                             │         │      │         │ permanently lost on rollback     │
├──────────┼─────────────────────────────┼─────────┼──────┼─────────┼──────────────────────────────────┤
│ 004      │ No-op downgrade             │ error   │    8 │ MRT102  │ downgrade() does nothing         │
├──────────┼─────────────────────────────┼─────────┼──────┼─────────┼──────────────────────────────────┤
│ 005      │ INDEX without CONCURRENTLY  │ warning │   19 │ MRT207  │ Locks table during index build   │
╰──────────┴─────────────────────────────┴─────────┴──────┴─────────┴──────────────────────────────────╯

2 error(s), 1 warning(s)
```

When there are no problems:

```
✓ No rollback risks detected.
```

---

## CLI: `mrt fix`

Auto-generates missing reverse operations. Works for both Alembic and Django migrations.

```bash
# Single-file mode
mrt fix <migration-file>           # preview suggested fix
mrt fix <migration-file> --apply   # write fix to file

# Batch mode (v1.4.0)
mrt fix --apply                    # fix all auto-fixable migrations in the detected directory
mrt fix --apply --dry-run          # preview without writing
mrt fix --apply --dir <path>       # specify the directory explicitly
```

### Batch mode options

| Option | Description |
|---|---|
| `--apply` | Required to write fixes. Without a file argument, scans the whole directory. |
| `--dry-run` | Preview what would change without writing. Use with `--apply`. |
| `--dir <path>` | Directory to scan. Auto-detected from cwd if omitted (`migrations/`, `alembic/versions/`, `versions/`). |

### Alembic

Generates a missing or stub `downgrade()` function with the inverse operations inferred from `upgrade()`.

### Django (v1.3.0)

Detects and fixes four operation types:

| Operation | Fix | Confidence |
|---|---|---|
| `RunSQL` without `reverse_sql` | Adds `reverse_sql=migrations.RunSQL.noop` | High |
| `RunPython` without `reverse_code` | Adds `reverse_code=migrations.RunPython.noop` | Medium |
| `RemoveField` | Injects `RunPython(backup, restore)` before the op | Medium |
| `DeleteModel` | Injects `RunPython(backup, restore)` before the op | Medium |

For `RemoveField` and `DeleteModel`, the generated code:

1. **Backs up** the column/row data into a `_mrt_backups` table using keyset pagination (safe for large tables, no server-side cursors required)
2. **Restores** the data when the migration is reversed, with constraint checking disabled for FK safety
3. **Inlines a type codec** (`__mrt_enc`/`__mrt_dec`) directly into the migration file — no runtime dependency on pytest-mrt in your production migrations

After you've confirmed the deployment is stable and rollback is no longer needed:

```bash
mrt clean-backups --db $DATABASE_URL
mrt clean-backups --db $DATABASE_URL --label 0042_remove_user_phone --yes
```

#### Known limitations (documented in generated code)

- Type fidelity depends on the codec: complex custom types may not round-trip perfectly
- Very large tables (millions of rows) increase migration time proportionally
- The backup table (`_mrt_backups`) persists until explicitly cleaned

---

## CLI: `mrt clean-backups` (v1.3.0)

Removes rows from the `_mrt_backups` table created by Django `mrt fix` backup/restore operations.

```bash
mrt clean-backups --db <database-url>
mrt clean-backups --db $DATABASE_URL --list        # preview without deleting
mrt clean-backups --db $DATABASE_URL --label 0042  # delete one migration's backup
mrt clean-backups --db $DATABASE_URL --yes         # skip confirmation prompt
```

### Options

| Option | Description |
|---|---|
| `--db` | SQLAlchemy database URL. Also reads from `DATABASE_URL` env var. |
| `--label` | Delete only rows for this migration label. Omit to delete all backup data. |
| `--list`, `-l` | List backup labels and row counts without deleting. |
| `--yes`, `-y` | Skip the confirmation prompt. |

---

## CLI: `mrt version`

```bash
mrt version
# pytest-mrt 1.3.1
```

---

## Pytest fixture: `mrt`

The `mrt` fixture is the main interface for dynamic testing. Add `mrt` as a parameter to any test function and it becomes available automatically — no import needed.

```python
def test_something(mrt):   # ← just add 'mrt' here
    ...
```

### Setup (required)

The fixture needs to know where your `alembic.ini` is and which database to use. Configure this in `conftest.py`:

```python
# conftest.py
import os
from pytest_mrt import MRTConfig


def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url=os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db"),
    )
```

### `mrt.assert_all_reversible()`

Tests every migration in your project, in order. This is the recommended starting point.

```python
def test_all_migrations(mrt):
    mrt.assert_all_reversible()
```

What it does for each revision:

1. Seeds real rows into all existing tables
2. Runs `alembic upgrade` to that revision
3. Runs `alembic downgrade -1`
4. Checks the schema is exactly the same as before
5. Checks all seeded rows are still there

If anything fails, the test fails with a detailed message:

```
FAILED: Some migrations are not safely reversible:
  revision 003:
    - Table 'users': 3/3 rows lost after rollback
```

---

### `mrt.check_revision(revision_id)`

Tests a single revision. Returns a result object you can inspect.

```python
def test_new_migration(mrt):
    result = mrt.check_revision("abc1234")

    # Simple pass/fail
    assert result.passed, result.failure_summary()
```

```python
def test_with_details(mrt):
    result = mrt.check_revision("abc1234")

    if not result.passed:
        print(result.failures)     # list of failure strings
        print(result.revision)     # the revision ID
        pytest.fail(result.failure_summary())
```

**Where to find the revision ID:**

Open any migration file and look at the top:
```python
# migrations/versions/003_drop_phone.py

revision = 'abc1234'    # ← this is the revision ID
down_revision = 'xyz789'
```

---

### `mrt.assert_reversible(revision_id)`

Like `check_revision()` but raises a pytest failure directly instead of returning a result.

```python
def test_migration_003(mrt):
    mrt.assert_reversible("abc1234")
```

---

### Manual control

For custom scenarios where you want to control each step:

```python
def test_custom_scenario(mrt):
    # Move to a specific state
    mrt.upgrade("abc1234")

    # Run downgrade
    mrt.downgrade()

    # Check data integrity
    mrt.assert_data_intact()
```

---

## MRTConfig reference

```python
from pytest_mrt import MRTConfig

MRTConfig(
    alembic_ini="alembic.ini",
    # Required.
    # Path to your alembic.ini file, relative to where you run pytest.
    # Usually this is in your project root.

    db_url="postgresql://localhost/myapp_test",
    # Required.
    # Database URL for the test database.
    # NEVER use your production database URL here.
    # Supported: postgresql://, sqlite:///

    seed_rows=3,
    # Optional. Default: 3.
    # Number of rows inserted per table before each rollback test.
    # Higher values catch more edge cases but make tests slower.

    minimum_downgrade_revision=None,
    # Optional. Default: None (test all revisions).
    # Rollback testing floor — skip revisions at or older than this point.
    # Alembic: revision ID (e.g. "abc123def456").
    # Django: app_label.migration_name (e.g. "myapp.0050_baseline").
    # Also settable from the CLI with --min-revision.
)
```
