# CLI Reference

## mrt check

Statically analyze migration files for rollback risk patterns. No database required.

```bash
mrt check <versions_dir> [--strict]
```

**Arguments:**

| Argument | Description |
|---|---|
| `versions_dir` | Path to Alembic versions directory |
| `--strict` | Exit with code 1 on warnings too (default: only errors) |

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | No issues found (or only warnings without `--strict`) |
| `1` | One or more errors found |

**Example:**

```bash
# Basic check
mrt check migrations/versions/

# Fail on warnings too (recommended for CI)
mrt check migrations/versions/ --strict
```

**Example output:**

```
╭──────────┬──────────────────────────┬─────────┬──────────────────────────────────╮
│ Revision │ Pattern                  │ Sev     │ Message                          │
├──────────┼──────────────────────────┼─────────┼──────────────────────────────────┤
│ 004      │ DROP COLUMN in upgrade   │ error   │ Column dropped — data lost        │
│ 005      │ No-op downgrade          │ error   │ downgrade() does nothing          │
│ 006      │ INDEX without CONCURR.   │ warning │ Locks table during index build    │
╰──────────┴──────────────────────────┴─────────┴──────────────────────────────────╯

2 error(s), 1 warning(s)
```

## mrt version

```bash
mrt version
```

Prints the installed version of pytest-mrt.

---

## pytest fixture: `mrt`

The `mrt` fixture is available in any test once `pytest-mrt` is installed and configured.

### mrt.assert_all_reversible()

Tests every migration in sequence. Fails if any migration causes data loss or leaves the schema in a different state after rollback.

```python
def test_all(mrt):
    mrt.assert_all_reversible()
```

### mrt.check_revision(revision)

Tests a single revision. Returns a `RevisionResult` object.

```python
def test_one(mrt):
    result = mrt.check_revision("abc123")
    assert result.passed, result.failure_summary()
```

### mrt.assert_reversible(revision)

Like `check_revision` but raises a pytest failure directly.

```python
def test_new_migration(mrt):
    mrt.assert_reversible("abc123")
```

### mrt.upgrade(revision) / mrt.downgrade()

Manual control for custom test scenarios.

```python
def test_custom(mrt):
    mrt.upgrade("abc123")
    # ... seed your own data ...
    mrt.downgrade()
    mrt.assert_data_intact()
```
