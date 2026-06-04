# pytest-mrt

<p align="center">
  <strong>Migration Rollback Tester</strong><br>
  Catch database migration disasters before they reach production.
</p>

<p align="center">
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/v/pytest-mrt?color=blue" alt="PyPI"></a>
  <a href="https://github.com/croc100/pytest-mrt/actions"><img src="https://img.shields.io/github/actions/workflow/status/croc100/pytest-mrt/ci.yml?branch=main" alt="CI"></a>
  <a href="https://pypi.org/project/pytest-mrt"><img src="https://img.shields.io/pypi/pyversions/pytest-mrt" alt="Python"></a>
  <a href="https://github.com/croc100/pytest-mrt/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
</p>

---

## The problem

It's 2am. Your new feature is deployed. Something is wrong. You run `alembic downgrade -1`.

The command succeeds. But the data is gone.

The column came back. The rows didn't.

---

This happens because **most tools only check if your migration runs without errors** — not whether your data survives the round-trip. `alembic downgrade` can succeed while silently destroying everything it was supposed to restore.

**pytest-mrt** tests the full cycle: seed real data → upgrade → downgrade → verify nothing was lost.

---

## Install

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
        db_url="postgresql://localhost/myapp_test",
    )
```

```python
# test_migrations.py
def test_all_migrations_are_reversible(mrt):
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
  │    004                                              │
  │      └─ Table 'users': 3/3 rows lost after rollback │
  │    005                                              │
  │      └─ Table 'users' still exists after rollback   │
  ╰─────────────────────────────────────────────────────╯
```

---

## What it catches

### Static analysis — before you even run

| Pattern | Severity | Why it's dangerous |
|---|---|---|
| `op.drop_column()` in upgrade | 🔴 error | Column data is permanently gone |
| `op.drop_table()` in upgrade | 🔴 error | All table data is permanently gone |
| `TRUNCATE` in migration | 🔴 error | Destroys data with no undo |
| `def downgrade(): pass` | 🔴 error | Rollback silently does nothing |
| No `downgrade()` function | 🔴 error | Migration is completely irreversible |
| `RunPython` without `reverse_func` | 🔴 error | Data transformation cannot be undone |
| `NOT NULL` without `server_default` | 🟡 warning | Will fail on non-empty tables |
| `ALTER COLUMN type_=...` | 🟡 warning | Type conversion may lose data |
| `op.execute()` with raw SQL | 🟡 warning | Cannot verify reversibility |
| Bulk `UPDATE` without reverse | 🟡 warning | One-way data transformation |
| `ON DELETE CASCADE` added | 🟡 warning | Child rows silently deleted |
| `CREATE INDEX` without `CONCURRENTLY` | 🟡 warning | Locks table during index build |
| `ADD COLUMN` with `DEFAULT` | 🟡 warning | Full table rewrite on PostgreSQL < 11 |
| `CREATE UNIQUE CONSTRAINT` | 🟡 warning | Will fail if duplicates exist |
| `NOT NULL` without restoring `nullable` | 🟡 warning | Downgrade leaves column in wrong state |

Run static analysis without a database:

```bash
mrt check migrations/versions/
```

```
╭──────────────────────────────────────────────────────────────────────────────╮
│                          Rollback Risk Analysis                              │
├──────────┬──────────────────────┬─────────────┬───────────────────────────  │
│ Revision │ Pattern              │ Sev         │ Message                       │
├──────────┼──────────────────────┼─────────────┼───────────────────────────  │
│ 004      │ DROP COLUMN          │ error       │ Data loss on rollback         │
│ 005      │ No-op downgrade      │ error       │ downgrade() does nothing      │
│ 006      │ INDEX without CONC.  │ warning     │ Locks table during build      │
╰──────────────────────────────────────────────────────────────────────────────╯
2 error(s), 1 warning(s)
```

### Dynamic verification — with real data

pytest-mrt seeds actual rows before each migration, then checks they survive the downgrade:

```python
def test_specific_revision(mrt):
    result = mrt.check_revision("abc123")
    assert result.passed, result.failure_summary()
```

Or test everything at once:

```python
def test_all_migrations(mrt):
    mrt.assert_all_reversible()
```

---

## How it works

For each migration revision, pytest-mrt:

```
1. Capture schema at current state
2. Seed real data into all existing tables
3. Run upgrade to this revision
4. Run downgrade (one step back)
5. Verify schema is exactly restored
6. Verify every seeded row survived
```

This catches failures that syntax checks miss:
- Schema comes back, but seeded rows are gone → **data loss**
- Downgrade is a no-op, table still exists → **rollback did nothing**
- Column returns but with wrong type → **schema drift**

---

## Supported databases

| Database | Status |
|---|---|
| PostgreSQL | ✅ Full support |
| SQLite | ✅ Full support (great for CI) |
| MySQL / MariaDB | 🔜 Planned |

---

## CI integration

Add to your GitHub Actions workflow:

```yaml
- name: Test migration rollbacks
  run: pytest tests/test_migrations.py -v -s
```

Or use the static check as a fast pre-flight:

```yaml
- name: Static migration analysis
  run: mrt check migrations/versions/ --strict
```

`--strict` makes warnings fail the build, not just errors.

---

## Configuration

```python
# conftest.py
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",       # path to alembic.ini
        db_url="postgresql://...",        # test database URL
        seed_rows=5,                      # rows to seed per table (default: 3)
    )
```

Use environment variables for CI:

```python
import os
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url=os.environ["TEST_DATABASE_URL"],
    )
```

---

## Examples

See [`examples/blog/`](examples/blog/) for a complete working example with:
- Safe migrations (add nullable column, create table)
- Dangerous migrations (drop column with data, no-op downgrade)
- How pytest-mrt catches each failure

```bash
cd examples/blog
pip install pytest-mrt
pytest test_migrations.py -v -s
```

---

## FAQ

**Does it modify my production database?**
No. pytest-mrt only runs against the database URL you provide in `MRTConfig`. Always use a test database.

**Does it work with Django migrations?**
Django support is on the roadmap. Currently only Alembic is supported.

**How is this different from pytest-alembic?**
`pytest-alembic` checks that migrations run without errors and that your schema matches your models. It does **not** verify that data survives a rollback. pytest-mrt focuses specifically on that gap.

**My migration intentionally drops a column. Will this always fail?**
Yes — dropping a column destroys data. That's exactly what pytest-mrt warns you about. If you want to proceed, you can exclude specific revisions or mark the test as expected-to-fail.

---

## Roadmap

- [x] Alembic support
- [x] Static risk analysis CLI (`mrt check`)
- [x] Dynamic data integrity verification
- [x] GitHub Actions CI
- [ ] Django Migrations support
- [ ] MySQL / MariaDB support
- [ ] HTML report output
- [ ] Per-revision exclusions (`@mrt.skip("004", reason="...")`)
- [ ] PyPI release

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

Apache 2.0
