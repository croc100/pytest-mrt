# pytest-mrt

**Migration Rollback Tester** — Automatically verify your Alembic migrations can be safely rolled back without data loss.

```bash
pip install pytest-mrt
```

---

## The Problem

Your migration runs in CI. Your downgrade syntax is valid. But when you actually need to rollback in production — data is gone.

`pytest-alembic` checks if migrations run without errors. It does **not** check if your data survives a rollback.

## What pytest-mrt does

- Seeds real data before rollback
- Verifies that data still exists after downgrade
- Detects risky patterns statically (`DROP COLUMN`, no-op `downgrade()`, `NOT NULL` without default)

---

## Quickstart

```python
# conftest.py
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url="postgresql://localhost/testdb",
    )
```

```python
# test_migrations.py

def test_add_column_is_reversible(mrt):
    mrt.upgrade()
    mrt.seed("users", [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    mrt.downgrade()
    mrt.assert_data_intact()


def test_all_migrations_reversible(mrt):
    mrt.assert_all_reversible()
```

---

## Static Analysis CLI

Catch risky migrations before you even run them:

```bash
mrt check migrations/versions/
```

```
┌──────────────────────────────────────────────────────────────────┐
│                   Rollback Risk Analysis                         │
├──────────┬────────────────────┬─────────────┬───────────────────┤
│ Revision │ File               │ Pattern     │ Message           │
├──────────┼────────────────────┼─────────────┼───────────────────┤
│ a3f91d2  │ 003_drop_email.py  │ DROP COLUMN │ Data loss on      │
│          │                    │             │ rollback          │
│ bc44e20  │ 005_add_phone.py   │ No downgrade│ downgrade() is    │
│          │                    │             │ a no-op           │
└──────────┴────────────────────┴─────────────┴───────────────────┘
```

---

## Detected Risk Patterns

| Pattern | Severity | Why |
|---|---|---|
| `op.drop_column` | error | Column data is unrecoverable after rollback |
| `op.drop_table` | error | Table data is unrecoverable after rollback |
| `def downgrade(): pass` | error | Migration is irreversible |
| `nullable=False` without `server_default` | warning | May fail on non-empty tables |

---

## Roadmap

- [x] Alembic support
- [x] Seed + verify data integrity
- [x] Static risk analysis CLI
- [ ] Django Migrations support
- [ ] GitHub Action
- [ ] MySQL support

---

## License

Apache 2.0
