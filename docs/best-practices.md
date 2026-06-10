# Best Practices

Guidelines for writing safe, rollback-friendly database migrations.

---

## Migration design principles

### 1. Every `upgrade()` must have a matching `downgrade()`

The most common cause of rollback failures is a `downgrade()` that does nothing:

```python
# Bad
def downgrade():
    pass

# Good
def downgrade():
    op.drop_table("users")
```

Use `mrt fix` to auto-generate a `downgrade()` when you're unsure what it should do.

### 2. Test rollback locally before code review

```bash
# Before opening a PR:
mrt check alembic/versions/
pytest tests/test_migrations.py -k "test_latest" -v
```

Catching rollback failures locally is faster than in CI.

### 3. One logical change per migration

Splitting migrations makes rollbacks surgical. A migration that creates a table, backfills data, and adds an index is harder to roll back safely than three separate migrations.

```
001_create_users.py        ← schema only
002_backfill_user_status.py ← data only (mark as skip if irreversible)
003_add_users_email_index.py ← index only
```

### 4. Document intentionally irreversible migrations

Not every migration can or should be reversible. When you skip one, document why:

```python
# conftest.py
MRTConfig(
    skip={
        "1a2b3c4d": (
            "Backfills 'status' from 'is_active'. "
            "Old column dropped in 002. "
            "Rollback handled by ops team via snapshot restore. "
            "Reviewed by: @alice, 2025-01-15. See ADR-023."
        )
    }
)
```

---

## Patterns to avoid

### Adding NOT NULL columns to existing tables

```python
# Dangerous — will fail if any existing rows exist
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer(), nullable=False))

# Safe
def upgrade():
    op.add_column("users", sa.Column("score", sa.Integer(), nullable=True))
    # Backfill in a separate migration or application code
    # Then in a later migration: op.alter_column("users", "score", nullable=False)
```

### Dropping columns before the application stops reading them

Follow the **expand-contract** pattern:

1. **Expand**: add new column (application reads old column)
2. **Migrate**: application reads both columns  
3. **Contract**: drop old column (application only reads new column)

Never drop a column in the same deployment where you remove the code that uses it.

### Using `op.execute()` for data changes without a reverse

```python
# Dangerous
def upgrade():
    op.execute("UPDATE users SET role = 'member' WHERE role IS NULL")

def downgrade():
    pass  # data is lost

# Safe
def upgrade():
    op.execute("UPDATE users SET role = 'member' WHERE role IS NULL")

def downgrade():
    op.execute("UPDATE users SET role = NULL WHERE role = 'member'")
    # Or: mark this as skip if the data change is intentional and irreversible
```

### Creating indexes inside a transaction (PostgreSQL)

```python
# Dangerous — locks the table for the duration on large tables
def upgrade():
    op.create_index("ix_users_email", "users", ["email"])

# Safe on PostgreSQL — use CONCURRENTLY
def upgrade():
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_email ON users (email)")

def downgrade():
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_email")
```

When using `CONCURRENTLY`, the migration must run outside a transaction block. In Alembic, set `migration_context_configure(transaction_per_migration=True)` or use a raw connection.

---

## Performance

### Testing large migration chains

If you have hundreds of migrations, `assert_all_reversible()` can be slow. Options:

**Test only recent migrations:**
```python
def test_recent_migrations(mrt):
    # Only test migrations from the last 30 revisions
    results = mrt.check_all()
    recent = results[-30:]
    failed = [r for r in recent if not r.passed]
    assert not failed
```

**Test only the migration being added in this PR:**
```python
import os

def test_new_migration(mrt):
    revision = os.environ.get("NEW_REVISION")
    if not revision:
        pytest.skip("No NEW_REVISION set — run full suite instead")
    mrt.upgrade(revision.split(":")[0])  # advance to predecessor
    result = mrt.check_revision(revision)
    assert result.passed, result.failure_summary()
```

**Run different scopes in CI:**
```yaml
# On PR: test only new migration
- run: pytest tests/test_migrations.py -k "test_new" -v

# On merge to main: test full chain (weekly)
- run: pytest tests/test_migrations.py -k "test_all" -v
```

### Parallelizing across databases

Use `pytest-xdist` with separate database URLs:

```bash
pytest tests/ -n 2 \
  --db1=postgresql://localhost/test_db_1 \
  --db2=postgresql://localhost/test_db_2
```

---

## Continuous integration

### Block merges on static errors

Add `mrt check --strict` as a required status check. It requires no database and completes in seconds.

```yaml
# .github/workflows/migration-safety.yml
- name: Static analysis
  run: mrt check alembic/versions/ --strict
```

### Separate static and dynamic checks

Static analysis is fast (< 1s) and requires no database. Run it on every commit. Dynamic rollback testing requires a database and takes longer — run it on PRs that touch migrations.

```yaml
on:
  pull_request:
    paths: ["alembic/versions/**"]
```

### Cache test database state

For long migration chains, use a pre-seeded database snapshot:

```yaml
- name: Restore DB snapshot
  run: pg_restore -d $TEST_DB snapshots/migrations_base.dump

- name: Run rollback tests
  run: pytest tests/test_migrations.py -v
```

---

## Django-specific guidance

### Always provide `reverse_code` for `RunPython`

```python
def populate_status(apps, schema_editor):
    User = apps.get_model("myapp", "User")
    User.objects.filter(status=None).update(status="active")

def depopulate_status(apps, schema_editor):
    User = apps.get_model("myapp", "User")
    User.objects.filter(status="active").update(status=None)

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(populate_status, depopulate_status),
    ]
```

### Use `atomic = False` for index operations

```python
class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["email"], name="idx_email"),
        ),
    ]
```

### Mark truly irreversible migrations explicitly

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(
            forward_func,
            migrations.RunPython.noop,  # Explicitly mark as no-op reverse
        ),
    ]
```

Then add this revision to `MRTConfig.skip` with a documented reason.

---

## Writing effective `skip` entries

A good skip entry answers:
- **What** data change happened
- **Why** it can't be reversed
- **How** to recover in a rollback scenario
- **Who** reviewed and approved it
- **When** it was reviewed

```python
skip={
    "f8a2b1c3": (
        "WHAT: Backfills 'uuid' column from 'id' for all users. "
        "WHY: UUID values are randomly generated — cannot be deterministically reversed. "
        "HOW TO RECOVER: Restore from DB snapshot tagged 'pre-uuid-migration-2025-01-15'. "
        "REVIEWED BY: @alice (backend lead), @bob (SRE). "
        "DATE: 2025-01-15. See ADR-031."
    )
}
```

---

## Setting a permanent rollback floor

Once a project has a long migration history, testing every migration from the beginning can be slow and unnecessary. Use `minimum_downgrade_revision` to skip everything at or before a known-safe baseline:

```python
# conftest.py
config._mrt_config = MRTConfig(
    db_url=os.environ["TEST_DATABASE_URL"],
    minimum_downgrade_revision="a1b2c3d4",  # Alembic: revision ID
    # minimum_downgrade_revision="myapp.0050_baseline",  # Django: app_label.migration_name
)
```

Migrations at or before the floor are advanced through (to keep the DB state consistent) but not tested. Migrations after the floor are tested as normal.

This is different from `skip`:
- `skip` exempts specific migrations from testing (use for genuinely irreversible data migrations)
- `minimum_downgrade_revision` sets a floor — everything below it is treated as "already validated, no need to re-test"

The same floor applies to both `mrt check` (static analysis) and `check_all()` (dynamic rollback tests). The CLI equivalent is `mrt check --min-revision <rev>`.
