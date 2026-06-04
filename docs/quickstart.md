# Getting Started

This guide walks you through setting up pytest-mrt from scratch, even if you've never written a pytest plugin before.

---

## What you need

- Python 3.10 or higher
- An existing project that uses [Alembic](https://alembic.sqlalchemy.org/) for database migrations
- A test database (separate from your production DB — see below)

---

## Step 1 — Install

```bash
pip install pytest-mrt
```

That's it. Because pytest-mrt is a **pytest plugin**, it automatically activates when you run `pytest`. You don't need to import it anywhere.

---

## Step 2 — Create a test database

pytest-mrt will run real migrations against a real database. **Never use your production database.**

=== "PostgreSQL"

    ```bash
    createdb myapp_test
    ```

    Your database URL will be:
    ```
    postgresql://localhost/myapp_test
    ```

=== "SQLite (simplest for CI)"

    No setup needed. Just use a file path:
    ```
    sqlite:///test.db
    ```

    SQLite is great for local development and CI. For production-like testing, use PostgreSQL.

---

## Step 3 — Create conftest.py

`conftest.py` is a special pytest file where you configure plugins. Create it in your project root (or test directory):

```python
# conftest.py
import os
from pytest_mrt import MRTConfig


def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",            # path to your alembic.ini file
        db_url="postgresql://localhost/myapp_test",  # your test database URL
    )
```

!!! tip "Use environment variables in CI"
    ```python
    def pytest_configure(config):
        config._mrt_config = MRTConfig(
            alembic_ini="alembic.ini",
            db_url=os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db"),
        )
    ```
    This way your local machine uses SQLite and CI uses PostgreSQL — no config changes needed.

---

## Step 4 — Write your first test

Create a test file:

```python
# tests/test_migrations.py


def test_all_migrations_are_reversible(mrt):
    """
    Checks every migration in your project.
    Seeds real data, runs upgrade, runs downgrade,
    and verifies nothing was lost.
    """
    mrt.assert_all_reversible()
```

!!! note "What is `mrt`?"
    `mrt` is a **pytest fixture** — a special argument that pytest automatically injects into your test function. You don't need to import or create it. Just add `mrt` as a parameter and it works.

---

## Step 5 — Run it

```bash
pytest tests/test_migrations.py -s -v
```

The `-s` flag is important — it lets the output render properly.

**If all migrations are safe:**
```
  ──────────── MRT — Migration Rollback Test ────────────

  ✓  001  reversible
  ✓  002  reversible
  ✓  003  reversible

  ╭──────────────────────────────────────────╮
  │  All 3 migration(s) are safely reversible│
  ╰──────────────────────────────────────────╯

PASSED
```

**If a migration is unsafe:**
```
  ✓  001  reversible
  ✓  002  reversible
  ✗  003  data loss detected
     └─ Table 'users': 3/3 rows lost after rollback

  ╭──────────────────────────────────────────────────╮
  │  1 migration(s) will cause data loss on rollback │
  ╰──────────────────────────────────────────────────╯

FAILED
```

---

## Testing only new migrations (recommended for CI)

Running all migrations on every PR can be slow. In CI, you usually only need to check the migration added in the current PR.

```python
# tests/test_migrations.py

def test_this_migration(mrt):
    """
    Replace 'abc1234' with the revision ID of your new migration.
    Find it at the top of your migration file:
      revision = 'abc1234'
    """
    result = mrt.check_revision("abc1234")
    assert result.passed, result.failure_summary()
```

If the migration is unsafe, `result.failure_summary()` prints exactly what went wrong:
```
  - Table 'users': 3/3 rows lost after rollback
```

---

## Static analysis — catch problems without running anything

Before touching your database, scan migration files for known dangerous patterns:

```bash
mrt check migrations/versions/
```

This is fast (no DB needed) and catches things like:

- `op.drop_column()` in upgrade — data loss even if downgrade re-adds the column
- `def downgrade(): pass` — rollback silently does nothing
- `ALTER TYPE ADD VALUE` — can't be rolled back in PostgreSQL
- ...and [21 more patterns](patterns.md)

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Clean — no issues |
| `1` | Errors found (will cause data loss or broken rollback) |

Add `--strict` to also fail on warnings:

```bash
mrt check migrations/versions/ --strict
```

---

## Adding to GitHub Actions

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pytest-mrt psycopg2-binary alembic

      - name: Static migration check (fast, no DB)
        run: mrt check migrations/versions/

      - name: Dynamic migration check (with real DB)
        env:
          TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/testdb
        run: pytest tests/test_migrations.py -v -s
```

---

## Configuration options

All options for `MRTConfig`:

```python
from pytest_mrt import MRTConfig

MRTConfig(
    alembic_ini="alembic.ini",   # Required. Path to your alembic.ini file.
    db_url="postgresql://...",   # Required. Test database URL. Never use production.
    seed_rows=3,                 # Optional. Rows inserted per table (default: 3).
                                 #   Increase if you want more thorough data checks.
)
```

---

## Common errors

### `MRTConfig not set`

```
AttributeError: 'Config' object has no attribute '_mrt_config'
```

You haven't created `conftest.py` or the `pytest_configure` function is missing. See [Step 3](#step-3-create-conftestpy).

---

### `could not connect to server`

```
sqlalchemy.exc.OperationalError: could not connect to server: Connection refused
```

Your test database isn't running, or the URL is wrong. Check:
```bash
# PostgreSQL
psql postgresql://localhost/myapp_test

# Should connect without errors
```

---

### `FAILED — Table not found`

The migration file references a table that doesn't exist yet. Make sure your migrations run in the correct order and `alembic.ini` points to the right versions directory.

---

### `Target database is not up to date`

Run `alembic upgrade head` on your test database first, then run the tests again. Or let pytest-mrt handle it — `assert_all_reversible()` starts from `base` automatically.

---

## What to read next

- [All 24 risk patterns explained →](patterns.md)
- [CLI reference →](cli.md)
- [Contributing a new pattern →](contributing.md)
