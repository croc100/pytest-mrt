# CLI & Fixture Reference

pytest-mrt has two interfaces:

- **`mrt` CLI** — analysis, fixing, and reporting without a database
- **`mrt` pytest fixture** — dynamic verification against a real database

## Command overview

| Command | What it does | Needs DB? |
|---|---|---|
| `mrt check <dir>` | Static analysis — 44 risk patterns | No |
| `mrt fix <file>` | Auto-generate missing or broken downgrade() | No |
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

## CLI: `mrt version`

```bash
mrt version
# pytest-mrt 1.2.0
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
