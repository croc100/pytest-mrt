# FAQ

---

## General

### What does pytest-mrt actually test?

pytest-mrt verifies that every `downgrade()` function in your Alembic (or Django) migration chain actually works — both structurally and for data. Specifically, it checks:

1. **Schema restoration** — after `upgrade()` + `downgrade()`, does the schema match what it was before?
2. **Data integrity** — rows seeded before the migration still exist after rollback?
3. **Static safety** — does the migration source code contain patterns that are inherently irreversible (e.g. `DROP COLUMN`, no-op `downgrade`)?

### Is pytest-mrt safe to run in CI?

Yes. pytest-mrt is designed to run against a **dedicated test database** — never production. It seeds synthetic rows, runs migrations up and down, and cleans up after itself. The `mrt check` command requires no database at all (pure AST analysis).

### Does pytest-mrt work with async SQLAlchemy?

pytest-mrt uses the **synchronous** SQLAlchemy engine internally. If your app uses async SQLAlchemy, pytest-mrt still works as long as your `alembic.ini` points to a sync database URL for testing. Alembic itself uses sync connections by default.

---

## Alembic vs Django

### When should I use Alembic mode vs Django mode?

pytest-mrt auto-detects which framework you're using based on whether the migration files contain `from django.db import migrations`. You don't need to choose — `mrt check` and `mrt report` will figure it out.

| | Alembic | Django |
|---|---|---|
| **Static analysis** | ✅ Full | ✅ Full |
| **Dynamic rollback** | ✅ Full | ⚠️ Not yet (use Alembic adapter) |
| **`mrt fix`** | ✅ | ❌ (Django doesn't have a `downgrade()`) |

### Django migrations don't have `downgrade()` — how does pytest-mrt help?

For Django, pytest-mrt focuses on **static analysis**: detecting `RemoveField`, `DeleteModel`, `RunPython` without `reverse_code`, `RunSQL` without `reverse_sql`, and unsafe `AddField` patterns. These are the most common sources of irreversible Django migrations.

Dynamic rollback testing for Django (actually running `migrate --backwards`) is on the roadmap.

---

## Configuration

### How do I skip a migration I know is irreversible?

```python
config._mrt_config = MRTConfig(
    skip={
        "abc123def": "One-way data backfill. Reviewed 2025-01-15. See ADR-007.",
    }
)
```

Skipped revisions appear in reports as "skipped" with the documented reason. **Always include a reason** — this creates an audit trail for your team.

### How do I provide custom seed data for a table?

```python
config._mrt_config = MRTConfig(
    custom_seeds={
        "users": lambda: [
            {"id": 1, "name": "Alice", "email": "alice@example.com", "role": "admin"},
            {"id": 2, "name": "Bob",   "email": "bob@example.com",   "role": "user"},
        ],
    }
)
```

Custom seeds replace the auto-generated data for that table. Use this when auto-seeding fails (e.g. complex constraints, ENUM values, or FK relationships).

### How do I write a custom static analysis check?

```python
from pytest_mrt.core.ast_analyzer import MigrationAST
from pytest_mrt.core.detector import RiskWarning

def no_direct_sql(m: MigrationAST) -> list[RiskWarning]:
    """Flag any migration that uses op.execute() directly."""
    if "op.execute" in m.source:
        return [RiskWarning(
            revision=m.revision,
            file=m.filename,
            pattern="op.execute() direct SQL",
            message="Use op.create_table / op.add_column instead of raw SQL for portability.",
            severity="warning",
        )]
    return []

config._mrt_config = MRTConfig(custom_checks=[no_direct_sql])
```

### Can I override the severity of a built-in pattern?

Yes. Use `severity_overrides` with the exact pattern name from `mrt check --format json`:

```python
MRTConfig(
    severity_overrides={
        "INDEX without CONCURRENTLY": "error",  # fail CI on this
        "noop downgrade": "warning",            # downgrade to warn only
    }
)
```

---

## Test failures

### `mrt check` exits 1 — what do I do?

Run with `--format json` to get machine-readable output, then check the `severity` and `pattern` fields:

```bash
mrt check alembic/versions/ --format json | jq '.[] | select(.severity == "error")'
```

Common fixes:

| Pattern | Fix |
|---------|-----|
| `noop downgrade` | Implement `op.drop_table()` or `op.drop_column()` in `downgrade()` |
| `DROP COLUMN` | Accept the data loss and `skip` this revision with a documented reason |
| `NOT NULL without default` | Add `server_default` or seed the column before making it non-nullable |
| `RunSQL without reverse` | Add a `reverse_sql` that undoes the data change |

### `assert_all_reversible()` fails with "Table 'X' still exists after rollback"

Your `downgrade()` function doesn't drop the table that `upgrade()` created. Fix:

```python
def upgrade():
    op.create_table("my_table", ...)

def downgrade():
    op.drop_table("my_table")  # ← this was missing
```

### `assert_all_reversible()` fails with "row lost after rollback"

This is expected for migrations that drop or truncate data. If the data loss is intentional, skip the revision:

```python
skip={"abc123": "Drops the deprecated 'phone' column. Data migrated in ADR-012."}
```

### Tests are slow — migrations take a long time

See the [performance guide](best-practices.md#performance) for strategies including parallel test databases and targeted revision testing.

---

## Database support

### Which databases does pytest-mrt support?

| Database | Static analysis | Dynamic verification |
|----------|----------------|---------------------|
| SQLite | ✅ | ✅ |
| PostgreSQL | ✅ | ✅ (`pip install pytest-mrt[postgres]`) |
| MySQL / MariaDB | ✅ | ✅ (`pip install pytest-mrt[mysql]`) |
| Oracle | ✅ (partial) | ❌ Planned |
| SQL Server | ✅ (partial) | ❌ Planned |

### Can I test against multiple databases in CI?

Yes. Use a matrix strategy in GitHub Actions:

```yaml
strategy:
  matrix:
    db: [postgres, mysql]
```

See [CI integration examples](../examples/ci-integration/).

---

## Security & compliance

### Does pytest-mrt send any data externally?

No — except for the optional `mrt explain` command, which sends migration source code to the Anthropic API. All other operations are local.

### Can I use pytest-mrt in an air-gapped environment?

Yes. After installation, all core features (`mrt check`, dynamic rollback testing) work entirely offline. Disable `mrt explain` and set `ANTHROPIC_API_KEY` to an empty string.

### Is pytest-mrt SOC 2 / ISO 27001 compatible?

pytest-mrt is a development/CI tool, not a SaaS product. It has no telemetry, no analytics, and makes no network requests beyond your configured test database. For vendor security questionnaires, see [SECURITY.md](https://github.com/croc100/pytest-mrt/blob/main/SECURITY.md).
