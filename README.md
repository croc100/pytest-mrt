# pytest-mrt

<p align="center">
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/v/pytest-mrt?color=blue" alt="PyPI"></a>
  <a href="https://github.com/croc100/pytest-mrt/actions"><img src="https://img.shields.io/github/actions/workflow/status/croc100/pytest-mrt/ci.yml?branch=main&label=tests" alt="CI"></a>
  <a href="https://codecov.io/gh/croc100/pytest-mrt"><img src="https://codecov.io/gh/croc100/pytest-mrt/graph/badge.svg?token=CODECOV_TOKEN" alt="Coverage"></a>
  <img src="https://img.shields.io/badge/coverage-88%25-brightgreen" alt="Coverage 88%">
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/pyversions/pytest-mrt" alt="Python"></a>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

<p align="center">
  A pytest plugin that catches database migration rollback failures before they reach production.
</p>

---

`alembic downgrade -1` ran clean. No errors. Your monitoring went green.

But the users' phone numbers are gone. The column came back. The data didn't.

---

## What it does

Most tools verify that migrations *run* without errors.  
pytest-mrt verifies that your data *survives* a rollback.

It seeds real rows before each migration, rolls back, and checks nothing was lost.
It also statically scans migration files for 30 known dangerous patterns across both Alembic and Django migrations.

> **Django note**: static pattern detection is fully supported. Dynamic rollback verification
> (`manage.py migrate --backwards`) is on the [roadmap](ROADMAP.md) for v0.9 — not yet implemented.

## Install

```bash
pip install pytest-mrt
```

## Setup (2 minutes)

**1.** Create `conftest.py` in your project root:

```python
# conftest.py
import os
from pytest_mrt import MRTConfig


def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",                               # path to your alembic.ini
        db_url=os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db"),  # test database
    )
```

**2.** Write a test:

```python
# tests/test_migrations.py


def test_migrations_are_safe(mrt):
    mrt.assert_all_reversible()
```

**3.** Run:

```bash
pytest tests/test_migrations.py -s
```

> `mrt` is a pytest fixture — just add it as a parameter and it works. No import needed in test files.

## Static analysis (no database needed)

```bash
mrt check migrations/versions/
```

```
╭──────────┬──────────────────────────┬─────────┬──────┬────────────────────────────────────╮
│ Revision │ Pattern                  │ Sev     │ Line │ Message                            │
├──────────┼──────────────────────────┼─────────┼──────┼────────────────────────────────────┤
│ 004      │ DROP COLUMN in upgrade   │ error   │   12 │ Data permanently lost on rollback  │
│ 005      │ No-op downgrade          │ error   │    8 │ downgrade() does nothing           │
│ 006      │ INDEX without CONCURR.   │ warning │   19 │ Locks table during index build     │
╰──────────┴──────────────────────────┴─────────┴──────┴────────────────────────────────────╯
2 error(s), 1 warning(s)
```

## What gets caught

**Errors** (will cause data loss or a broken rollback):

- `op.drop_column()` in upgrade — data is gone even if downgrade re-adds the column
- `op.drop_table()` in upgrade — all rows permanently lost
- `TRUNCATE` in migration
- `def downgrade(): pass` — rollback silently does nothing
- No `downgrade()` function
- `rename_table` / `rename_column` without reverse
- `DROP VIEW` without recreating in downgrade
- `ALTER TYPE ... ADD VALUE` (PostgreSQL ENUM) — can't roll back once rows use the new value
- Add column + migrate data + drop original in one migration

**Warnings** (review before deploying):

- `NOT NULL` without `server_default`
- Column type change
- Raw `op.execute()` / `context.execute()` without reverse
- `op.execute(sa.text(...))` — SQL inside `sa.text()` wrapper now fully analyzed
- `op.bulk_insert()` without corresponding `DELETE` in downgrade
- Bulk `UPDATE` without a reverse `UPDATE` in downgrade
- `ON DELETE CASCADE` added
- `CREATE INDEX` without `CONCURRENTLY` (PostgreSQL)
- `ADD COLUMN` with `DEFAULT` on large tables
- `CREATE UNIQUE CONSTRAINT` on existing data
- `DROP INDEX` without recreating
- `DROP CONSTRAINT` without recreating
- `ALTER SEQUENCE` / `setval`
- `NOT NULL` via raw SQL without reverse
- `NOT NULL` without restoring `nullable` in downgrade

## Databases

| | Static analysis | Dynamic verification |
|---|---|---|
| PostgreSQL | ✅ | ✅ |
| SQLite | ✅ | ✅ |
| MySQL / MariaDB | ✅ | ✅ |

```bash
pip install pytest-mrt[mysql]   # includes PyMySQL
```

Use `mysql+pymysql://user:pass@host/dbname` as your `db_url`.

## CI/CD integration

Drop `mrt check` into any pipeline as a pre-deploy gate:

```yaml
# GitHub Actions — blocks merge if unsafe migrations are detected
- name: Migration safety check
  run: mrt check alembic/versions/ --strict
```

Full examples for GitHub Actions, GitLab CI, Jenkins, and pre-commit hooks are in [`examples/ci-integration/`](examples/ci-integration/).

## Docker

Run tests locally against PostgreSQL or MySQL without installing anything:

```bash
docker compose run test-postgres
docker compose run test-mysql
```

See [`docker-compose.yml`](docker-compose.yml) for the full configuration.

## Performance

| | 10 migrations | 50 migrations | 100 migrations |
|---|---|---|---|
| `mrt check` (static, no DB) | 22 ms | 108 ms | 216 ms |
| `mrt` fixture (SQLite) | 0.33 s | 4.3 s | 15.6 s |

Safe to run `mrt check` on every commit. Dynamic suite fits comfortably for projects up to ~200 migrations.
For larger codebases, use `MRTConfig(skip={...})` to exclude already-reviewed revisions.
See [benchmarks](docs/benchmarks.md) for methodology and PostgreSQL/MySQL numbers.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Documentation

Full docs at **[croc100.github.io/pytest-mrt](https://croc100.github.io/pytest-mrt)**

- [Getting started (step-by-step)](https://croc100.github.io/pytest-mrt/quickstart/)
- [All 30 patterns explained](https://croc100.github.io/pytest-mrt/patterns/)
- [CLI & fixture reference](https://croc100.github.io/pytest-mrt/cli/)
- [Detection accuracy report](docs/accuracy.md) — what each pattern catches and doesn't catch
- [API reference](docs/api.md) — stable public API
- [FAQ](docs/faq.md) — timeouts, large codebases, Django, error handling

## License

MIT
