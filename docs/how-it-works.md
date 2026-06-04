# How It Works

pytest-mrt has two independent layers. You can use either or both.

---

## Layer 1 — Static analysis

```bash
mrt check migrations/versions/
```

This reads your migration `.py` files and runs 26 regex-based checks against them. No database. No imports. Just file parsing.

**What it checks:**

- Presence of `downgrade()` function
- Whether `downgrade()` body is just `pass`
- Dangerous operations in the `upgrade()` body (DROP COLUMN, TRUNCATE, etc.)
- Whether reversals exist in `downgrade()` (rename reversed, index recreated, etc.)
- Directory-level: whether multiple migrations branch from the same parent

**Why regex and not AST?**

Migration files follow predictable patterns. Regex is fast, has zero dependencies, and doesn't require importing your application code. An AST-based approach would be slower and would need to handle arbitrary Python, including dynamic migration generation — which is out of scope.

**Limitations of static analysis:**

Static analysis cannot catch everything. These require a real database:

- A `downgrade()` that runs without errors but leaves data in the wrong state
- A NOT NULL column that works with the current data but breaks after rollback
- A migration that runs fine in isolation but conflicts with data from another migration

That's what Layer 2 is for.

---

## Layer 2 — Dynamic verification

```python
def test_migrations(mrt):
    mrt.assert_all_reversible()
```

This runs real migrations against a real database and checks the result.

### What happens for each revision

```
Current state: revision N-1

Step 1: Snapshot schema
        Record every table, column, type, and constraint

Step 2: Seed data
        Insert rows into every existing table
        Values are generated per (column_name, row_index)
        to avoid UNIQUE constraint collisions
        Tables are seeded in FK dependency order

Step 3: Upgrade
        alembic upgrade <revision>

Step 4: Downgrade
        alembic downgrade -1

Step 5: Snapshot schema again
        Compare with Step 1:
        - Are all tables from before still here? (none missing)
        - Are there tables that shouldn't be here? (noop downgrade)
        - Are all columns from before still here?

Step 6: Verify data
        For each seeded row:
        - Does the row still exist?
        - Does every column value match what was seeded?
          (only for columns that existed before the migration)
```

### State management

After each revision check, pytest-mrt performs a hard reset:

```
downgrade to base → upgrade to revision N
```

This ensures a clean starting state for the next revision, even if the previous downgrade was a no-op that left the schema out of sync with the Alembic version table.

### What it catches that static analysis misses

**Scenario:** A migration adds a column, migrates data, and drops the original. The downgrade recreates the column but can't restore the data.

- Static analysis: **catches this** (multi-step destructive pattern)
- Dynamic: **also catches this** (seeded values in original column are gone after rollback)

**Scenario:** A downgrade that runs without errors but leaves a row with a different value.

```python
def downgrade():
    op.execute("UPDATE users SET status = 'inactive'")  # wrong — should restore 'active'
```

- Static analysis: **misses this** (can't know what value 'active' was)
- Dynamic: **catches this** (stored 'active' at seed time, finds 'inactive' after rollback)

**Scenario:** A no-op `downgrade()` on a CREATE TABLE migration.

```python
def upgrade():
    op.create_table("invitations", ...)

def downgrade():
    pass
```

- Static analysis: **catches this** (no-op downgrade pattern)
- Dynamic: **also catches this** (table still exists after rollback → schema not restored)

---

## How the seeder generates data

For each column, pytest-mrt generates a type-appropriate value using a deterministic seed:

```python
seed = hash(f"mrt_{column_name}_{row_index}") % 10^8
```

This ensures:

- **Uniqueness across rows** — different `row_index` → different values → no UNIQUE violations
- **Uniqueness across columns** — column name is part of the seed → two VARCHAR columns in the same row get different values
- **Stability** — same input always produces the same value (useful for debugging)

Column types handled:

| Type | Generated value |
|---|---|
| INTEGER, BIGINT, SERIAL | Large unique integer |
| FLOAT, NUMERIC, DECIMAL | Large unique float |
| VARCHAR, TEXT, CHAR | `mrt_{col_name}_{row_index:04d}` (truncated to length limit) |
| BOOLEAN | Alternates True/False |
| UUID | Deterministic UUID from seed |
| DATE | 2024-01-{row_index+1} |
| TIMESTAMP, DATETIME | 2024-01-{row_index+1} 00:00:00 |
| JSON, JSONB | `{"mrt": row_index}` |
| BYTEA, BLOB | `b"mrt_{row_index}"` |

Nullable columns are left as `NULL` intentionally — this tests that the migration correctly handles null values.

---

## FK ordering

Before seeding, pytest-mrt builds a dependency graph of all tables and their foreign keys. Tables are seeded in topological order — parents before children.

If the graph has a cycle (circular FK), the cycle is broken and seeding continues. Some rows in the cycle may fail to insert (due to FK constraints), which is expected and handled silently.

---

## Schema snapshot

After each migration, pytest-mrt captures:

- Table names
- Column names, types, nullable status, defaults
- Primary key columns
- Foreign key relationships (for seeding order)

The `alembic_version` table is excluded from all checks.

---

## What pytest-mrt does NOT do

- It does not test that your migration is idempotent (running it twice)
- It does not test parallel migration safety
- It does not check migration performance (lock time, row count)
- It does not verify that your ORM models match your schema (use `pytest-alembic` for that)
- It does not test application code — only the migration files themselves
