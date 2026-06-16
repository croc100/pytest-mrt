# pytest-mrt

**Migration Rollback Tester** — A pytest plugin that catches database migration disasters before they reach production.

[![PyPI](https://img.shields.io/pypi/v/pytest-mrt?color=blue)](https://pypi.org/project/pytest-mrt)
[![CI](https://img.shields.io/github/actions/workflow/status/croc100/pytest-mrt/ci.yml?branch=main&label=tests)](https://github.com/croc100/pytest-mrt/actions)
[![Python](https://img.shields.io/pypi/pyversions/pytest-mrt)](https://pypi.org/project/pytest-mrt)
![MIT](https://img.shields.io/badge/license-MIT-green)

---

## The problem

You run `alembic downgrade -1`. It succeeds. No errors.

But your users' data is gone.

The column structure came back. The rows didn't.

---

This is one of the most common sources of production incidents with database migrations. `alembic downgrade` can succeed while silently destroying everything it was supposed to restore — because most tools only check that the migration *runs*, not that your data *survives*.

---

## How pytest-mrt helps

pytest-mrt does two things:

**1. Static analysis** — scans your migration files for 46 known dangerous patterns before you touch a database:

```bash
mrt check migrations/versions/
```

```
┌──────────┬─────────────────────────┬───────┬──────────────────────────────────────┐
│ Revision │ Pattern                 │ Sev   │ Message                              │
├──────────┼─────────────────────────┼───────┼──────────────────────────────────────┤
│ 004      │ DROP COLUMN in upgrade  │ error │ Data permanently lost on rollback    │
│ 005      │ No-op downgrade         │ error │ downgrade() does nothing             │
└──────────┴─────────────────────────┴───────┴──────────────────────────────────────┘
2 error(s)
```

**2. Dynamic verification** — seeds real data, runs your migration, rolls it back, and checks nothing was lost:

```python
# tests/test_migrations.py

def test_migrations_are_safe(mrt):
    mrt.assert_all_reversible()
```

```
  ✓  001  reversible
  ✓  002  reversible
  ✗  003  data loss detected
     └─ Table 'users': 3/3 rows lost after rollback

  FAILED
```

---

## Install

```bash
pip install pytest-mrt
```

Because it's a pytest plugin, the `mrt` fixture is automatically available in all your tests once installed. No imports needed in test files.

---

## 5-minute setup

**1.** Install:
```bash
pip install pytest-mrt
```

**2.** Create `conftest.py`:
```python
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url="postgresql://localhost/myapp_test",
    )
```

**3.** Write a test:
```python
def test_migrations_are_safe(mrt):
    mrt.assert_all_reversible()
```

**4.** Run:
```bash
pytest tests/test_migrations.py -s
```

→ [Full setup guide](quickstart.md)

---

## Supported databases

| Database | Static analysis | Dynamic verification |
|---|---|---|
| PostgreSQL | Yes | Yes |
| SQLite | Yes | Yes |
| MySQL / MariaDB | Yes | Yes |
| Oracle | Yes | Yes |
| SQL Server | Yes | Yes |

---

## Why not just read the migration file manually?

You could — but you'd have to know all 46 patterns, remember to check every PR, and still wouldn't catch the cases that only appear when real data is present. pytest-mrt does it automatically on every test run.

---

[Get started →](quickstart.md){ .md-button .md-button--primary }
[See all patterns →](patterns.md){ .md-button }
