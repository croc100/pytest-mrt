# CLI & Fixture Reference

pytest-mrt has two interfaces:

- **`mrt` CLI** — analysis, fixing, and reporting without a database
- **`mrt` pytest fixture** — dynamic verification against a real database

## Command overview

| Command | What it does | Needs DB? |
|---|---|---|
| `mrt check <dir>` | Static analysis — 44 risk patterns | No |
| `mrt check <dir> --since <ref>` | Incremental scan — only migrations since a git ref | No |
| `mrt fix <file>` | Auto-generate reverse operations (Alembic + Django) | No |
| `mrt clean-backups` | Remove `_mrt_backups` rows after stable deployment | Yes |
| `mrt drift` | Compare live DB schema against ORM models | Yes |
| `mrt report <dir>` | HTML safety report of entire migration history | No |
| `mrt explain <file>` | AI explanation in plain English | No (needs API key) |
| `mrt version` | Show installed version | No |

---

- **`mrt` CLI** — static analysis, runs without a database
- **`mrt` pytest fixture** — dynamic verification, runs migrations against a real database

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
| `--since <ref>` | Only check migrations added since this git revision / tag | Off |

#### `--since` — incremental scanning

In large codebases, scanning the full migration history on every PR is wasteful. `--since` limits the scan to migrations whose files were added after the given git ref:

```bash
mrt check migrations/versions/ --since main
mrt check myapp/migrations/ --since v1.2.0
mrt check myapp/migrations/ --since HEAD~5
```

This is the recommended setup for CI: check only the migrations that changed in the current PR branch.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | No problems found |
| `1` | One or more errors (or warnings with `--strict`) |

Use the exit code in CI to fail the pipeline automatically.

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
mrt fix <migration-file>          # preview
mrt fix <migration-file> --apply  # write to file
```

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
# pytest-mrt 1.3.0
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
)
```
