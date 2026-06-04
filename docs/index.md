# pytest-mrt

**Migration Rollback Tester** — Catch database migration disasters before they reach production.

[![PyPI](https://img.shields.io/pypi/v/pytest-mrt?color=blue)](https://pypi.org/project/pytest-mrt)
[![CI](https://img.shields.io/github/actions/workflow/status/croc100/pytest-mrt/ci.yml?branch=main&label=tests)](https://github.com/croc100/pytest-mrt/actions)
[![Python](https://img.shields.io/pypi/pyversions/pytest-mrt)](https://pypi.org/project/pytest-mrt)
![MIT](https://img.shields.io/badge/license-MIT-green)

---

`alembic downgrade -1` ran clean. No errors. Your monitoring went green.

But the users' phone numbers are gone. The column came back. The data didn't.

This is what pytest-mrt exists to prevent.

## Install

```bash
pip install pytest-mrt
```

## One test to catch them all

```python
# conftest.py
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url=os.environ["TEST_DATABASE_URL"],
    )
```

```python
# test_migrations.py
def test_migrations_are_safe(mrt):
    mrt.assert_all_reversible()
```

```
$ pytest test_migrations.py -s

  ──────────── MRT — Migration Rollback Test ────────────

  ✓  001  reversible
  ✓  002  reversible
  ✗  003  data loss detected
     └─ Table 'users': 3/3 rows lost after rollback

  ╭──────────────────────────────────────────╮
  │  1 migration will cause data loss.       │
  ╰──────────────────────────────────────────╯
```

## Static analysis — no database needed

```bash
mrt check migrations/versions/
```

Catches 24 known dangerous patterns before you run anything.

→ [See all patterns](patterns.md)

→ [Getting started guide](quickstart.md)
