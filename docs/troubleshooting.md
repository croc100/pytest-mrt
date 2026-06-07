# Troubleshooting

---

## Setup errors

### `AttributeError: 'Config' object has no attribute '_mrt_config'`

```
AttributeError: 'Config' object has no attribute '_mrt_config'
```

**Cause:** `conftest.py` is missing or the `pytest_configure` function isn't set up.

**Fix:** Create `conftest.py` in your project root (where you run `pytest` from):

```python
# conftest.py
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url="postgresql://localhost/myapp_test",
    )
```

Make sure `pytest_configure` is a top-level function, not inside a class.

---

### `FileNotFoundError: alembic.ini not found`

**Cause:** The path to `alembic.ini` is wrong relative to where you run `pytest`.

**Fix:** Run `pytest` from the directory that contains `alembic.ini`, or use an absolute path:

```python
import os

MRTConfig(
    alembic_ini=os.path.join(os.path.dirname(__file__), "alembic.ini"),
    db_url="...",
)
```

---

### `could not connect to server: Connection refused`

```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError)
could not connect to server: Connection refused
```

**Cause:** The database server isn't running, or the URL is wrong.

**Fix:**

```bash
# Check PostgreSQL is running
pg_isready -h localhost

# Test the connection manually
psql postgresql://localhost/myapp_test

# Check the URL format
# postgresql://user:password@host:port/dbname
# sqlite:///path/to/file.db     (relative)
# sqlite:////absolute/path.db   (absolute, 4 slashes)
```

---

### `Target database is not up to date`

```
alembic.util.exc.CommandError: Target database is not up to date.
```

**Cause:** pytest-mrt starts from `alembic downgrade base`, but Alembic's `base` state requires the migration history to be clean.

**Fix:** Make sure your test database has no leftover state from previous test runs. Add to your `conftest.py`:

```python
from pytest_mrt import MRTConfig
from sqlalchemy import create_engine, text

def pytest_configure(config):
    db_url = "postgresql://localhost/myapp_test"

    # Drop and recreate the test database before each run
    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    config._mrt_config = MRTConfig(alembic_ini="alembic.ini", db_url=db_url)
```

---

## Test failures

### `Table 'X' no longer exists after rollback`

```
FAILED: Table 'users' no longer exists after rollback — all data lost
```

**Cause:** The migration drops a table in `upgrade()` and doesn't recreate it in `downgrade()`, OR `downgrade()` is a no-op that doesn't reverse a CREATE TABLE.

**Which migration is it?** Run `mrt check` to find it immediately:

```bash
mrt check migrations/versions/
```

**Common fix for CREATE TABLE with no-op downgrade:**
```python
def downgrade():
    op.drop_table("users")  # reverse the CREATE TABLE
```

---

### `X/Y rows lost after rollback`

```
FAILED: Table 'users': 3/3 rows lost after rollback
```

**Cause:** The migration drops a column or truncates data in `upgrade()`. The schema comes back in `downgrade()`, but the actual row data was destroyed.

**This is the most important thing pytest-mrt catches.** The migration passes `alembic downgrade` but leaves your data in a bad state.

**Which column?** Look for `op.drop_column()` in the migration's `upgrade()` function. The static analysis will have caught it too:

```bash
mrt check migrations/versions/
# Should show: DROP COLUMN in upgrade → error
```

---

### `Column 'X' value changed after rollback`

```
FAILED: Table 'users': column 'status' value changed after rollback
(expected 'active', got 'inactive')
```

**Cause:** The `downgrade()` function modifies data incorrectly — it doesn't fully restore the pre-migration state.

**Fix:** Check your `downgrade()` UPDATE statements. The values after rollback must exactly match what existed before the migration ran.

---

### `Table 'X' still exists after rollback — downgrade is incomplete`

```
FAILED: Table 'events' still exists after rollback — downgrade is incomplete
```

**Cause:** The migration creates a table in `upgrade()` but `downgrade()` is `pass` or empty.

**Fix:**
```python
def downgrade():
    op.drop_table("events")
```

---

### `Column 'X' still present after rollback — downgrade is incomplete`

**Cause:** The migration adds a column in `upgrade()` but doesn't remove it in `downgrade()`.

**Fix:**
```python
def downgrade():
    op.drop_column("users", "bio")
```

---

## Static analysis

### A pattern is flagged but my migration is intentional

Some patterns are warnings, not errors. If your migration intentionally drops a column (for example, after a confirmed data migration), you can:

1. **Acknowledge it** — the warning tells reviewers to double-check the PR
2. **Run with `--strict` only on errors** — omit `--strict` to let warnings pass CI

You can suppress a specific warning on any line using `# noqa: MRTxxx` (same convention as ruff/flake8):

```python
def upgrade():
    op.drop_column("users", "phone")  # noqa: MRT103
```

To suppress all MRT warnings on a line, use a bare `# noqa`. To suppress by severity instead, run `mrt check` without `--strict` — this makes warnings non-blocking while still reporting them.

---

### `mrt check` reports `Multiple heads`

```
error: Revisions 002a, 002b all branch from '001' — migration graph has multiple heads
```

**Cause:** Two developers created migrations independently from the same parent revision.

**Fix:**
```bash
alembic merge heads -m "merge 002a and 002b"
alembic upgrade head
```

This creates a merge migration that resolves the conflict.

---

### False positive on `op.execute()`

`op.execute()` is flagged as a warning when the `downgrade()` function has no corresponding `op.execute()`. If both `upgrade()` and `downgrade()` have `op.execute()`, no warning is raised.

---

## Performance

### Tests are slow

`check_all()` runs `downgrade base → upgrade revision N` for each revision to ensure clean state. For large migration histories (100+ revisions), this can be slow.

**Options:**

1. **Test only recent migrations in CI:**
    ```python
    def test_recent_migration(mrt):
        # Only test the migration added in this PR
        result = mrt.check_revision("abc1234")
        assert result.passed, result.failure_summary()
    ```

2. **Run `check_all()` on a schedule** (nightly) rather than on every PR.

3. **Use SQLite for local development** — SQLite is much faster than PostgreSQL for migration testing.

---

## `--since` not finding any migrations

### `mrt check --since <revision>` returns "No rollback risks detected" immediately

**Cause:** The revision ID was not found in the migration chain, so the filter returned nothing.

**Fix:** Double-check the revision ID. For Alembic it must be the bare hex ID (e.g. `a1b2c3d4`), not the full filename. You can list all known revisions with:

```bash
alembic history --verbose | grep "Rev:"
```

For Django, the format is `app_label.migration_name` exactly as it appears in the filename:

```bash
# file: myapp/migrations/0010_add_email.py  →  --since myapp.0010_add_email
```

If the revision exists but is at the tip of the chain (no descendants), `--since` will return an empty set — which is correct; there is nothing to check.

---

## Seeding failures

### `SeederError: could not generate unique value after N retries`

**Cause:** A column has a `UNIQUE` constraint and the seeder exhausted its retry budget generating a non-colliding value.

**Fix:** Provide a seed factory for the conflicting column:

```python
MRTConfig(
    alembic_ini="alembic.ini",
    db_url="...",
    seed_overrides={"users": {"email": lambda i: f"user_{i}@example.com"}},
)
```

---

### `SeederError: circular foreign key detected`

**Cause:** Two or more tables have FK references to each other (e.g. `users.manager_id → users.id`).

**Fix:** Use `seed_overrides` to break the cycle by seeding the self-referential column as `None`:

```python
MRTConfig(
    seed_overrides={"users": {"manager_id": None}},
)
```

---

## Multiple databases

### Which database is tested when I have multiple `bind` targets in Alembic?

pytest-mrt uses the `db_url` you pass to `MRTConfig`. If your Alembic config uses `bind_names` for multiple databases, you need a separate `MRTConfig` per database and run each in its own test session. There is no multi-bind support in a single `MRTConfig` today.

---

## Getting help

If you've hit something not covered here, [open an issue](https://github.com/croc100/pytest-mrt/issues) with:

- The migration file that's causing the problem
- The full error output
- Your database type and version
- Your pytest-mrt version (`mrt version`)
