# Risk Patterns

pytest-mrt detects 24 dangerous migration patterns — 10 errors and 14 warnings.

**Errors** will cause data loss or a broken rollback and always fail the test.  
**Warnings** are worth reviewing before deploying; use `--strict` to fail on them too.

---

## Errors

### DROP COLUMN in upgrade

```python
def upgrade():
    op.drop_column("users", "email")  # ✗
```

Column data is permanently gone even when `downgrade()` re-adds the column structure. The column comes back empty.

---

### DROP TABLE in upgrade

```python
def upgrade():
    op.drop_table("sessions")  # ✗
```

Every row is permanently lost. Even if `downgrade()` recreates the table, it will be empty.

---

### TRUNCATE in migration

```python
def upgrade():
    op.execute("TRUNCATE TABLE logs")  # ✗
```

Destroys all data with no undo.

---

### No-op downgrade

```python
def downgrade():
    pass  # ✗
```

Rollback silently succeeds but does nothing. The schema is not restored.

---

### Missing downgrade

```python
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer))

# no downgrade() at all  # ✗
```

Migration is completely irreversible.

---

### rename_table without reverse

```python
def upgrade():
    op.rename_table("users", "accounts")  # ✗

def downgrade():
    pass
```

After rollback, the table stays as `accounts`. Code referencing `users` breaks.

---

### rename_column without reverse

```python
def upgrade():
    op.alter_column("users", "name", new_column_name="full_name")  # ✗

def downgrade():
    pass
```

Column stays renamed after rollback. App code using the old name breaks immediately.

---

### DROP VIEW without reverse

```python
def upgrade():
    op.execute("DROP VIEW active_users")  # ✗

def downgrade():
    pass
```

Any application query against `active_users` fails after rollback.

---

### ALTER TYPE ... ADD VALUE (PostgreSQL ENUM)

```python
def upgrade():
    op.execute("ALTER TYPE user_status ADD VALUE 'suspended'")  # ✗
```

PostgreSQL cannot remove enum values. If any row was set to `'suspended'` before rollback, the downgrade will fail with a constraint error.

---

### Multi-step destructive migration

```python
def upgrade():
    op.add_column("users", sa.Column("full_name", sa.String))
    op.execute("UPDATE users SET full_name = first_name || ' ' || last_name")
    op.drop_column("users", "first_name")  # ✗
    op.drop_column("users", "last_name")   # ✗
```

The original data is gone after the drop. Even if `downgrade()` re-adds the columns, the original values cannot be reconstructed.

---

## Warnings

### NOT NULL without server_default

```python
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer, nullable=False))  # ✗
```

Will fail on non-empty tables. After rollback, the column may be left in an invalid state.

**Fix:**
```python
op.add_column("users", sa.Column("score", sa.Integer, nullable=False, server_default="0"))
```

---

### Column type change

```python
def upgrade():
    op.alter_column("users", "age", type_=sa.String(10))
```

Type conversion may be lossy (e.g. `INTEGER → VARCHAR` loses numeric precision context; `VARCHAR → INTEGER` fails on non-numeric values).

---

### Raw SQL via op.execute()

```python
def upgrade():
    op.execute("UPDATE users SET status = 'active'")
```

pytest-mrt cannot automatically verify that the downgrade correctly reverses this. Review manually.

---

### Bulk UPDATE without reverse

```python
def upgrade():
    op.execute("UPDATE users SET name = UPPER(name)")

def downgrade():
    pass  # no reverse UPDATE
```

One-way data transformation. Original casing is permanently lost.

---

### ON DELETE CASCADE added

```python
op.add_column("posts", sa.Column("user_id", sa.Integer,
    sa.ForeignKey("users.id", ondelete="CASCADE")))
```

Child rows are silently deleted whenever the parent is deleted. This is often unintentional.

---

### CREATE INDEX without CONCURRENTLY (PostgreSQL)

```python
def upgrade():
    op.create_index("ix_users_email", "users", ["email"])
```

Locks the table for the duration of the index build. On large tables this causes downtime.

**Fix:**
```python
op.create_index("ix_users_email", "users", ["email"], postgresql_concurrently=True)
```

---

### ADD COLUMN with DEFAULT (PostgreSQL < 11)

```python
op.add_column("users", sa.Column("score", sa.Integer, server_default="0"))
```

On PostgreSQL < 11, adding a column with a default value rewrites the entire table, causing a long exclusive lock.

---

### CREATE UNIQUE CONSTRAINT on existing data

```python
def upgrade():
    op.create_unique_constraint("uq_users_email", "users", ["email"])
```

Will fail if the table already contains duplicate values in the constrained columns.

---

### DROP INDEX without recreating

```python
def upgrade():
    op.drop_index("ix_users_email", table_name="users")

def downgrade():
    pass  # ✗ index not recreated
```

Query performance degrades and any unique guarantees are not restored after rollback.

---

### DROP CONSTRAINT without recreating

```python
def upgrade():
    op.drop_constraint("fk_posts_user", "posts")

def downgrade():
    pass  # ✗ constraint not recreated
```

Data integrity guarantees are permanently removed after rollback.

---

### SEQUENCE modification

```python
def upgrade():
    op.execute("ALTER SEQUENCE users_id_seq RESTART WITH 1000")
```

Sequences are not transactional in PostgreSQL. The sequence counter does not revert on rollback, causing ID gaps or potential duplicates.

---

### NOT NULL via raw SQL without reverse

```python
def upgrade():
    op.execute("ALTER TABLE users ALTER COLUMN score SET NOT NULL")

def downgrade():
    pass  # ✗ NOT NULL not removed
```

After rollback, the column stays NOT NULL. Any insert with a null value breaks.

---

### NOT NULL without restoring nullable

```python
def upgrade():
    op.alter_column("users", "score", nullable=False)

def downgrade():
    op.alter_column("users", "score")  # ✗ nullable not restored
```

Downgrade leaves the column as NOT NULL when it should have been nullable again.
