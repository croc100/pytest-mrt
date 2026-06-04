# Contributing to pytest-mrt

Thank you for considering a contribution.

## Setup

```bash
git clone https://github.com/croc100/pytest-mrt
cd pytest-mrt
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests

```bash
# All tests (SQLite only, no external dependencies)
pytest tests/ -v

# With PostgreSQL
TEST_DATABASE_URL=postgresql://localhost/mrt_test pytest tests/ -v

# With MySQL
TEST_DATABASE_URL=mysql+pymysql://root:pass@localhost/mrt_test pytest tests/ -v

# With Docker (PostgreSQL + MySQL, no local DB needed)
docker compose run test-postgres
docker compose run test-mysql
```

## What to work on

Check the [ROADMAP](ROADMAP.md) for planned work, and [open issues](https://github.com/croc100/pytest-mrt/issues) for bugs.

**Good first issues:**
- Add a new static analysis pattern (Alembic or Django)
- Improve an existing error message
- Add a missing test case for an edge condition

**Medium effort:**
- Add a new example to `examples/`
- Improve HTML report output
- Add a CI integration example

**Higher effort (discuss first):**
- New database adapter
- New migration framework support
- Plugin API for custom patterns

## Adding a new risk pattern (Alembic)

Alembic detection lives in `pytest_mrt/core/detector.py`. All checks use the `MigrationAST` object, not raw strings — this prevents false positives from commented-out code.

1. Write a `_check_*` function:

```python
def _check_my_pattern(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.method == "some_op":
            warnings.append(_warn(
                m, "Pattern name",
                "Human-readable explanation of the risk",
                "error",  # or "warning"
                line=c.node.lineno,
            ))
    return warnings
```

2. Add it to `_PER_FILE_CHECKS` at the bottom of `detector.py`.

3. Write tests in `tests/test_detector.py` — one positive case and one negative case.

## Adding a new risk pattern (Django)

Same process but in `pytest_mrt/adapters/django_detector.py`, using `DjangoMigrationAST`.

## Commit style

```
feat: add Oracle support
fix: handle empty downgrade body on Python 3.10
docs: add Jenkins integration example
test: cover bulk_insert without reverse in downgrade
```

## Pull request checklist

- [ ] Tests added for new behavior (positive and negative)
- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] `mrt check examples/blog/alembic/versions/` still exits 0
- [ ] New patterns documented in `docs/patterns.md` if user-facing
- [ ] Line numbers populated in `RiskWarning` where possible

## Response time

PRs are reviewed within 5 business days. If you haven't heard back in a week, ping the thread.
