# pytest-mrt

<p align="center">
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/v/pytest-mrt?color=blue" alt="PyPI"></a>
  <a href="https://github.com/croc100/pytest-mrt/actions"><img src="https://img.shields.io/github/actions/workflow/status/croc100/pytest-mrt/ci.yml?branch=main&label=tests" alt="CI"></a>
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/pyversions/pytest-mrt" alt="Python"></a>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

`alembic downgrade -1` ran clean. No errors. Your monitoring went green.

But the users' phone numbers are gone. The column came back. The data didn't.

This is what pytest-mrt exists to prevent.

---

## What it does

Most tools verify that migrations *run* without errors. pytest-mrt verifies that your data *survives* a rollback — by seeding real rows before each migration, rolling back, and checking nothing was lost.

It also statically scans your migration files for 24 known dangerous patterns before you touch a database at all.

```bash
pip install pytest-mrt
```

---

## Quickstart

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
  ✓  003  reversible
  ✗  004  data loss detected
     └─ Table 'users': 3/3 rows lost after rollback
  ✗  005  data loss detected
     └─ Table 'users' still exists after rollback — downgrade is incomplete

  ╭─────────────────────────────────────────────────────╮
  │  2 migration(s) will cause data loss on rollback.   │
  ╰─────────────────────────────────────────────────────╯
```

You can also check a single revision — useful in CI to only gate new migrations in a PR:

```python
def test_this_pr(mrt):
    result = mrt.check_revision("abc123")
    assert result.passed, result.failure_summary()
```

---

## Static analysis

No database needed. Scan your migration files directly:

```bash
mrt check migrations/versions/
```

```
╭──────────┬──────────────────────────────┬─────────┬──────────────────────────────────────────────────╮
│ Revision │ Pattern                      │ Sev     │ Message                                          │
├──────────┼──────────────────────────────┼─────────┼──────────────────────────────────────────────────┤
│ 004      │ DROP COLUMN in upgrade       │ error   │ Column dropped — data permanently lost on rollback│
│ 005      │ No-op downgrade              │ error   │ downgrade() does nothing — migration irreversible │
│ 006      │ ENUM value added             │ error   │ Cannot roll back if rows use the new value        │
│ 007      │ INDEX without CONCURRENTLY   │ warning │ Locks table during index build                    │
╰──────────┴──────────────────────────────┴─────────┴──────────────────────────────────────────────────╯
3 error(s), 1 warning(s)
```

Add `--strict` to make warnings fail the build too.

---

## What gets caught

**Errors** — these will cause data loss or a broken rollback:

| Pattern | Why |
|---|---|
| `op.drop_column()` in upgrade | Column data is gone even after rollback re-adds the column |
| `op.drop_table()` in upgrade | Every row in the table is permanently lost |
| `TRUNCATE` in migration | Destroys data with no undo |
| `def downgrade(): pass` | Rollback silently does nothing |
| No `downgrade()` function | Migration is completely irreversible |
| `rename_table` without reverse | Table stays under new name after rollback |
| `rename_column` without reverse | App code using old column name breaks |
| `DROP VIEW` without recreating | Application queries fail after rollback |
| `ALTER TYPE ... ADD VALUE` | Can't remove enum values once rows use them |
| Add + migrate data + drop original | The combined operation cannot be undone |

**Warnings** — worth reviewing before deploying:

| Pattern | Why |
|---|---|
| `NOT NULL` without `server_default` | Fails on non-empty tables |
| Column type change | Conversion may be lossy |
| Raw `op.execute()` | Content can't be verified automatically |
| Bulk `UPDATE` without reverse `UPDATE` | One-way data transformation |
| `ON DELETE CASCADE` added | Child rows silently deleted with parent |
| `CREATE INDEX` without `CONCURRENTLY` | Locks table during build (PostgreSQL) |
| `ADD COLUMN` with `DEFAULT` | Full table rewrite on PostgreSQL < 11 |
| `CREATE UNIQUE CONSTRAINT` | Fails if duplicates already exist |
| `DROP INDEX` without recreating | Query performance and uniqueness not restored |
| `DROP CONSTRAINT` without recreating | Data integrity guarantees removed |
| `ALTER SEQUENCE` / `setval` | Sequences don't roll back — gaps appear |
| `NOT NULL` via raw SQL without reverse | Column stays NOT NULL after rollback |
| `NOT NULL` without restoring `nullable` | Downgrade leaves column in wrong state |

---

## How the dynamic check works

For each revision, pytest-mrt:

1. Takes a snapshot of the current schema
2. Seeds real rows into every table (type-aware: generates valid integers, strings, timestamps, UUIDs, etc.)
3. Runs `alembic upgrade` to the revision
4. Runs `alembic downgrade -1`
5. Checks the schema is exactly restored — no missing tables, no leftover tables
6. Checks every seeded row is still there

This catches things static analysis can't: a migration where the schema comes back but the data doesn't, or a `downgrade()` that creates the table empty instead of restoring it.

---

## Databases

| | Static analysis | Dynamic verification |
|---|---|---|
| PostgreSQL | ✅ | ✅ |
| SQLite | ✅ | ✅ |
| MySQL / MariaDB | ✅ | 🔜 planned |

---

## CI

```yaml
- name: Check migrations
  run: |
    mrt check migrations/versions/
    pytest tests/test_migrations.py -v -s
```

For publishing via GitHub Actions with OIDC (no tokens needed), see [the publish workflow](.github/workflows/publish.yml).

---

## Examples

[`examples/blog/`](examples/blog/) has a complete Alembic project with intentionally safe and unsafe migrations. Run it to see what pytest-mrt catches:

```bash
cd examples/blog
pytest test_migrations.py -v -s
```

---

## Contributing

New risk patterns are the most valuable contribution. If you've been burned by a migration pattern that pytest-mrt doesn't catch, open an issue or PR. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT
