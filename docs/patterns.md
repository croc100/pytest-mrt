# Risk Patterns

pytest-mrt detects **44 patterns** across two categories.

Run static analysis instantly — no database needed:

```bash
mrt check migrations/versions/
```

---

## How to read this page

Each pattern shows:

- What the dangerous code looks like
- What actually happens in production
- How to fix it (when possible)

**Error** — will cause data loss or a broken rollback. Always fails the check.  
**Warning** — worth reviewing before deploying. Use `--strict` to fail on these too.

---

## Errors

### DROP COLUMN in upgrade

```python
def upgrade():
    op.drop_column("users", "phone")  # ✗

def downgrade():
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
```

**What happens:** The downgrade re-adds the column structure, but all the phone numbers are gone. Users who called support to update their number? Gone. Rows that had `phone IS NOT NULL`? Now null. The column exists again but it's empty.

**Fix:** If you need to remove a column, do it in two separate deployments:

1. First deploy: stop reading/writing the column in application code
2. Second deploy: drop the column in a migration

This way rollback is safe because the app no longer depends on the column.

---

### DROP TABLE in upgrade

```python
def upgrade():
    op.drop_table("sessions")  # ✗
```

**What happens:** Every row is gone. Even if `downgrade()` recreates the table, it will be empty. Active user sessions, audit logs, queued jobs — all lost.

**Fix:** Same two-step approach. Archive the table first (`ALTER TABLE sessions RENAME TO sessions_archived`), verify nothing breaks, then drop.

---

### TRUNCATE in migration

```python
def upgrade():
    op.execute("TRUNCATE TABLE event_log")  # ✗
```

**What happens:** All data is destroyed with no undo. Unlike `DROP TABLE`, `TRUNCATE` cannot even be recreated empty — the data is simply gone.

**Fix:** Don't truncate in migrations. If you need to clear data for a cleanup migration, use `DELETE FROM` with a condition, and add the reverse operation in downgrade.

---

### No-op downgrade

```python
def upgrade():
    op.create_table("invitations", ...)

def downgrade():
    pass  # ✗
```

**What happens:** `alembic downgrade -1` reports success. The alembic version table is decremented. But the `invitations` table still exists. Your next migration may try to create it again — and fail.

**Fix:** Always implement `downgrade()`. For every operation in `upgrade()`, there must be a corresponding reverse in `downgrade()`.

---

### Missing downgrade function

```python
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer))

# no downgrade() at all  # ✗
```

**What happens:** `alembic downgrade` raises an `AttributeError`. The migration is permanently irreversible.

---

### rename_table without reverse

```python
def upgrade():
    op.rename_table("users", "accounts")  # ✗

def downgrade():
    pass
```

**What happens:** After rollback, the table is still called `accounts`. Your application code, ORM models, and any hardcoded SQL that references `users` will immediately start failing.

**Fix:**
```python
def downgrade():
    op.rename_table("accounts", "users")  # reverse it
```

---

### rename_column without reverse

```python
def upgrade():
    op.alter_column("users", "name", new_column_name="full_name")  # ✗

def downgrade():
    pass
```

**What happens:** After rollback, the column is still `full_name`. Any code still using the old name `name` fails immediately.

**Fix:**
```python
def downgrade():
    op.alter_column("users", "full_name", new_column_name="name")
```

---

### DROP VIEW without reverse

```python
def upgrade():
    op.execute("DROP VIEW active_users")  # ✗

def downgrade():
    pass
```

**What happens:** Any query, report, or BI tool that reads from `active_users` fails instantly after rollback.

**Fix:**
```python
def downgrade():
    op.execute("""
        CREATE VIEW active_users AS
        SELECT * FROM users WHERE deleted_at IS NULL
    """)
```

---

### ALTER TYPE ... ADD VALUE (PostgreSQL ENUM)

```python
def upgrade():
    op.execute("ALTER TYPE user_status ADD VALUE 'suspended'")  # ✗
```

**What happens:** PostgreSQL cannot remove enum values. The moment any row is set to `'suspended'`, attempting to roll back will fail with a constraint error. There is no safe rollback path.

**Fix:** Use a `VARCHAR` with a `CHECK` constraint instead of a native ENUM type. Or accept that ENUM additions are permanent and plan accordingly.

---

### Multi-step destructive migration

```python
def upgrade():
    op.add_column("users", sa.Column("full_name", sa.String))
    op.execute("UPDATE users SET full_name = first_name || ' ' || last_name")
    op.drop_column("users", "first_name")  # ✗
    op.drop_column("users", "last_name")   # ✗
```

**What happens:** The `first_name` and `last_name` values are gone. If you need to roll back, `downgrade()` can recreate the columns but cannot reconstruct the original values.

**Fix:** Separate this into three migrations across three deployments:

1. Add `full_name` column (nullable)
2. Migrate data + update app code to write both
3. Drop the old columns (only when confident in rollback window)

---

### DROP COLUMN in batch_alter_table

```python
def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("phone")  # ✗
```

`op.batch_alter_table` is SQLite's mechanism for schema changes (since SQLite doesn't support `ALTER COLUMN` directly). The same data loss rules apply — the column structure comes back in downgrade, but the values are gone.

---

### Multiple heads (directory-level)

```
migrations/versions/
├── 001_create_users.py          down_revision = None
├── 002a_add_email.py            down_revision = '001'   ← branch A
└── 002b_add_phone.py            down_revision = '001'   ← branch B
```

**What happens:** When two developers create migrations independently from the same parent, Alembic doesn't know which order to run them in. `alembic upgrade head` will fail with `Multiple head revisions` until a merge migration is created.

**Fix:**
```bash
alembic merge heads -m "merge branches"
```

This creates a merge migration that resolves the conflict.

---

## Warnings

### NOT NULL without server_default

```python
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer, nullable=False))  # ✗
```

**What happens:** If the table has any existing rows, this migration fails immediately — you can't add a NOT NULL column with no default when rows already exist (they'd violate the constraint).

**Fix:**
```python
# Option 1: give it a default
op.add_column("users", sa.Column("score", sa.Integer, nullable=False, server_default="0"))

# Option 2: add as nullable, backfill, then add the constraint separately
```

---

### Column type change

```python
def upgrade():
    op.alter_column("users", "age", type_=sa.String(10))
```

Type conversions may be lossy. `INTEGER → VARCHAR` is usually safe. `VARCHAR → INTEGER` will fail if any values aren't numeric. Always verify the existing data is compatible before running.

---

### Raw SQL (op.execute) without reverse

```python
def upgrade():
    op.execute("UPDATE users SET tier = 'gold' WHERE spend > 10000")

def downgrade():
    op.drop_column("users", "tier")  # no corresponding UPDATE
```

pytest-mrt can't verify that a raw SQL statement is correctly reversed just by reading the code. This warning means: check manually that your downgrade undoes what the upgrade did.

---

### Bulk UPDATE without reverse UPDATE

```python
def upgrade():
    op.execute("UPDATE users SET name = UPPER(name)")

def downgrade():
    pass  # original casing is permanently gone
```

The data transformation only goes one way. Original values cannot be recovered.

---

### ON DELETE CASCADE added

```python
op.add_column("posts", sa.Column("user_id", sa.Integer,
    sa.ForeignKey("users.id", ondelete="CASCADE")))
```

Child rows are now silently deleted whenever the parent is deleted. This is often added accidentally and can cause unexpected mass deletions.

---

### CREATE INDEX without CONCURRENTLY (PostgreSQL)

```python
def upgrade():
    op.create_index("ix_users_email", "users", ["email"])  # ✗
```

Without `CONCURRENTLY`, PostgreSQL takes an `ACCESS EXCLUSIVE` lock on the table for the duration of the index build. On large tables, this blocks all reads and writes — causing downtime.

**Fix:**
```python
op.create_index("ix_users_email", "users", ["email"], postgresql_concurrently=True)
```

Note: `CONCURRENTLY` cannot run inside a transaction, so Alembic's transaction wrapper needs to be disabled for this migration. See the [Alembic docs](https://alembic.sqlalchemy.org/en/latest/cookbook.html#create-index-concurrently) for how to do this.

---

### ADD COLUMN with DEFAULT (large tables, PostgreSQL < 11)

```python
op.add_column("users", sa.Column("score", sa.Integer, server_default="0"))
```

On PostgreSQL < 11, adding a column with a non-null default rewrites the entire table. On a table with millions of rows, this can take minutes and hold an exclusive lock the entire time.

On PostgreSQL 11+, this is safe (optimized in the engine). Check your PostgreSQL version.

---

### CREATE UNIQUE CONSTRAINT on existing data

```python
def upgrade():
    op.create_unique_constraint("uq_users_email", "users", ["email"])
```

If any two rows already have the same email, this migration fails. Always check for duplicates before adding a unique constraint:

```sql
SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1;
```

---

### DROP INDEX without recreating

```python
def upgrade():
    op.drop_index("ix_users_email", table_name="users")

def downgrade():
    pass  # ✗ index not recreated
```

After rollback, the index is gone. Query performance degrades (full table scans) and any unique guarantee the index provided is also lost.

---

### DROP CONSTRAINT without recreating

```python
def upgrade():
    op.drop_constraint("fk_posts_user", "posts")

def downgrade():
    pass  # ✗ constraint not recreated
```

The data integrity guarantee is permanently removed after rollback. Future inserts may violate the constraint that used to exist.

---

### ALTER SEQUENCE / setval

```python
def upgrade():
    op.execute("ALTER SEQUENCE users_id_seq RESTART WITH 1000")
```

Sequences in PostgreSQL are not transactional — changes to a sequence are not rolled back even when the surrounding transaction is rolled back. After rollback, the sequence counter stays at 1000, causing ID gaps or potential collisions.

---

### NOT NULL via raw SQL without reverse

```python
def upgrade():
    op.execute("ALTER TABLE users ALTER COLUMN score SET NOT NULL")

def downgrade():
    pass  # ✗ NOT NULL not removed
```

After rollback, the column stays NOT NULL. Any application code that inserts with `score=None` starts failing.

---

### NOT NULL without restoring nullable

```python
def upgrade():
    op.alter_column("users", "score", nullable=False)

def downgrade():
    op.alter_column("users", "score")  # ✗ nullable not explicitly restored
```

The downgrade may leave `score` as NOT NULL, depending on database defaults, when it should have been nullable again.

**Fix:**
```python
def downgrade():
    op.alter_column("users", "score", nullable=True)
```

---

### DROP CONSTRAINT in batch_alter_table

```python
def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_email")  # ✗

def downgrade():
    pass
```

Constraint dropped inside SQLite's batch mode — downgrade must recreate it.
