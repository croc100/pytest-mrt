# pytest-mrt

<p align="center">
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/v/pytest-mrt?color=blue" alt="PyPI"></a>
  <a href="https://pepy.tech/project/pytest-mrt"><img src="https://static.pepy.tech/badge/pytest-mrt" alt="Downloads"></a>
  <a href="https://github.com/croc100/pytest-mrt/network/dependents"><img src="https://img.shields.io/badge/used%20by-see%20dependents-informational" alt="Used by"></a>
  <a href="https://github.com/croc100/pytest-mrt/actions"><img src="https://img.shields.io/github/actions/workflow/status/croc100/pytest-mrt/ci.yml?branch=main&label=tests" alt="CI"></a>
  <a href="https://codecov.io/gh/croc100/pytest-mrt"><img src="https://codecov.io/gh/croc100/pytest-mrt/graph/badge.svg?token=CODECOV_TOKEN" alt="Coverage"></a>
  <img src="https://img.shields.io/badge/status-stable-brightgreen" alt="Production/Stable">
  <img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue" alt="Python 3.10-3.14">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <a href="https://gcv-five.vercel.app/croc100/pytest-mrt"><img src="https://img.shields.io/badge/contributors-GCV-6e40c9?logo=github" alt="Contributors"></a>
</p>

<p align="center">
  A pytest plugin that catches database migration rollback failures before they reach production.
</p>

<p align="center">
  <img src="docs/demo.gif" alt="mrt check catching DROP COLUMN data loss" width="100%" />
</p>

---

`alembic downgrade -1` ran clean. No errors. Your monitoring went green.

But the users' phone numbers are gone. The column came back. The data didn't.

pytest-mrt would have caught this before it reached production:

```
$ mrt check migrations/versions/

                         Rollback Risk Analysis
╭──────────┬────────┬───────────────────────────┬───────┬──────┬─────────────────────────────────────╮
│ Revision │ Code   │ Pattern                   │ Sev   │ Line │ Message                             │
├──────────┼────────┼───────────────────────────┼───────┼──────┼─────────────────────────────────────┤
│ 042      │ MRT201 │ DROP COLUMN in upgrade    │ error │   18 │ op.drop_column('users', 'phone') —  │
│          │        │                           │       │      │ column data is permanently lost     │
│          │        │                           │       │      │ even if downgrade re-adds the column│
╰──────────┴────────┴───────────────────────────┴───────┴──────┴─────────────────────────────────────╯
1 error(s), 0 warning(s)
```

Non-invasive — installs in 2 minutes, zero changes to your existing tests.

---

## What it does

Most tools verify that migrations *run* without errors.  
pytest-mrt verifies that your data *survives* a rollback.

It seeds real rows before each migration, rolls back, and checks nothing was lost.
It also statically scans migration files for 44 known dangerous patterns across both Alembic and Django migrations.

## Install

```bash
pip install pytest-mrt
```

## Setup (2 minutes)

Add this to `conftest.py`:

```python
# conftest.py
import os
from pytest_mrt import MRTConfig


def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url=os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db"),
    )
```

That's it. Run `pytest` and 6 safety tests appear automatically — no test files needed:

```
PASSED test_mrt_single_head          - Migration history has exactly one head
PASSED test_mrt_upgrade              - alembic upgrade head completes without error
PASSED test_mrt_downgrade_base       - alembic downgrade base then re-upgrade completes cleanly
PASSED test_mrt_up_down_consistency  - Every migration is safely reversible
PASSED test_mrt_static_no_errors     - Zero static analysis errors in all migration files
PASSED test_mrt_schema_matches_models- Database schema matches ORM models after upgrade
```

> Want to write custom rollback tests? Use the `mrt` fixture — just add it as a parameter to any test function, no import needed:
>
> ```python
> def test_migration_003(mrt):
>     mrt.assert_reversible("abc1234")
> ```

## Static analysis (no database needed)

```bash
mrt check migrations/versions/
```

```
╭──────────┬──────────────────────────┬─────────┬──────┬─────────┬────────────────────────────────────╮
│ Revision │ Pattern                  │ Sev     │ Line │ Code    │ Message                            │
├──────────┼──────────────────────────┼─────────┼──────┼─────────┼────────────────────────────────────┤
│ 004      │ DROP COLUMN in upgrade   │ error   │   12 │ MRT103  │ Data permanently lost on rollback  │
│ 005      │ No-op downgrade          │ error   │    8 │ MRT102  │ downgrade() does nothing           │
│ 006      │ INDEX without CONCURR.   │ warning │   19 │ MRT207  │ Locks table during index build     │
╰──────────┴──────────────────────────┴─────────┴──────┴─────────┴────────────────────────────────────╯
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
| PostgreSQL | Yes | Yes |
| SQLite | Yes | Yes |
| MySQL / MariaDB | Yes | Yes |
| Oracle | Yes | Yes |
| SQL Server | Yes | Yes |

```bash
pip install pytest-mrt[mysql]    # PyMySQL
pip install pytest-mrt[oracle]   # python-oracledb
pip install pytest-mrt[mssql]    # pymssql
```

## pre-commit integration

Add to `.pre-commit-config.yaml` to run `mrt check` automatically before every push:

```yaml
# Alembic
- repo: https://github.com/croc100/pytest-mrt
  rev: v1.5.0
  hooks:
    - id: mrt-check
      args: [alembic/versions/]

# Django
- repo: https://github.com/croc100/pytest-mrt
  rev: v1.5.0
  hooks:
    - id: mrt-check
      args: [myapp/migrations/]
```

Update `rev` to the latest release tag. Run `pre-commit autoupdate` to keep it current.

## Incremental CI — `--since`

Check only migrations added since a given revision. Keeps CI fast on large codebases:

```bash
# Alembic — pass a revision ID
mrt check migrations/versions/ --since a1b2c3d4

# Django — pass app_label.migration_name (filename without .py)
mrt check myapp/migrations/ --since myapp.0010_add_email
```

Pass the last migration on the base branch; only PR-new migrations are scanned.

> When `--since` is active, graph-level checks (orphan detection, data-hole analysis) are skipped. Run without `--since` periodically for full coverage. See the [CLI reference](docs/cli.md#--since--incremental-scanning) for the full format specification.

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


## Suppress known risks (v1.2.0)

Use `# noqa: MRTxxx` on any line to suppress a specific warning — the same convention as ruff and flake8:

```python
def upgrade():
    op.drop_column("users", "phone")  # noqa: MRT103
```

To suppress all MRT warnings on a line:

```python
    op.drop_column("users", "legacy_col")  # noqa
```

Legacy syntax `# mrt: ignore` is still supported for backward compatibility.

## How it compares

| | pytest-mrt | [pytest-alembic](https://github.com/schireson/pytest-alembic) | [alembic check](https://alembic.sqlalchemy.org/en/latest/ops.html#alembic.operations.Operations.check) | [django-test-migrations](https://github.com/wemake-services/django-test-migrations) |
|---|:---:|:---:|:---:|:---:|
| Static analysis (no DB required) | ✅ 44 patterns | ❌ | ❌ | ❌ |
| Dynamic rollback testing | ✅ | ✅ | ❌ | ✅ |
| **Data survival check** (seeds rows, verifies after rollback) | ✅ | ❌ schema only | ❌ | ❌ |
| Django support | ✅ | ❌ | ❌ | ✅ |
| Pre-commit hook | ✅ | ❌ | ❌ | ❌ |
| Inline suppression (`# noqa: MRTxxx`) | ✅ | ❌ | ❌ | ❌ |

The key difference from pytest-alembic: pytest-mrt seeds actual rows before each rollback and verifies they survive. A migration that reverses the schema cleanly but silently destroys data will pass pytest-alembic and fail pytest-mrt.

## What's new in v1.6.0

- **Fine-grained migration step control** — `upgrade_to()`, `upgrade_one()`, `downgrade_one()`, `downgrade_to()`, `current_revision()` let you test data migration logic at any point in the chain:

```python
def test_data_migration(mrt):
    mrt.upgrade_to("abc123")          # upgrade to a specific revision
    mrt.seed("users", [...])          # seed data at that checkpoint
    mrt.upgrade_one()                 # apply exactly one more step
    assert mrt.current_revision() == "def456"
    mrt.downgrade_one()               # roll back one step
    mrt.downgrade_to("base")          # roll all the way back
```

## Migrating from v1.4.x

**v1.5.0 removed `mrt fix` and `mrt clean-backups`** — migration code generation is a *transform* operation, not a *verify* operation, and was out of scope. Projects relying on these commands should pin `pytest-mrt<1.5.0`.

The `fixable` field in `mrt check --format json` output was also removed in v1.5.0.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Documentation

Full docs at **[croc100.github.io/pytest-mrt](https://croc100.github.io/pytest-mrt)**

- [Getting started (step-by-step)](https://croc100.github.io/pytest-mrt/quickstart/)
- [All 44 patterns explained](https://croc100.github.io/pytest-mrt/patterns/)
- [CLI & fixture reference](https://croc100.github.io/pytest-mrt/cli/)
- [Detection accuracy report](docs/accuracy.md) — what each pattern catches and doesn't catch
- [API reference](docs/api.md) — stable public API
- [FAQ](docs/faq.md) — timeouts, large codebases, Django, error handling

## Production SQLite monitoring

pytest-mrt catches rollback failures at test time. For production SQLite monitoring — schema drift detection, backup integrity, and continuous alerting — see **[Litescope](https://github.com/croc100/Litescope)**.

```bash
# Catch drift in production after deploy
litescope monitor check production.db --baseline baseline.json
```

---

## Sponsorship

pytest-mrt is MIT-licensed and free to use. If it saves you from a production incident, consider sponsoring development:

**[github.com/sponsors/croc100](https://github.com/sponsors/croc100)**

Sponsorship directly funds:
- New pattern development (Oracle, SQL Server, more Django patterns)
- Maintained compatibility with new Alembic and SQLAlchemy releases

## License

MIT
