# Contributing to pytest-mrt

Thank you for considering a contribution. Here's how to get started.

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
# All tests (SQLite, no external dependencies)
pytest tests/ -v

# With PostgreSQL
MRT_TEST_DB_URL=postgresql://localhost/mrt_test pytest tests/ -v -m postgres
```

## What to work on

Good first issues:
- Add a new static analysis pattern to `pytest_mrt/core/detector.py`
- Add a new integration test case to `tests/test_integration.py`
- Improve error messages in `pytest_mrt/reporter.py`

Higher effort:
- Django Migrations adapter (`pytest_mrt/adapters/django.py`)
- MySQL support
- HTML report output

## Adding a new risk pattern

1. Write a `_check_*` function in `pytest_mrt/core/detector.py`
2. Add it to the `_CHECKS` list at the bottom
3. Write a test in `tests/test_detector.py` (both a positive and a negative case)

```python
def _check_my_new_pattern(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _upgrade_body(source)
    if re.search(r"some_pattern", body):
        return [RiskWarning(rev, fname, "Pattern name",
                            "Human-readable explanation of the risk", "error")]
    return []
```

## Commit style

```
feat: add MySQL support
fix: handle empty downgrade body correctly
docs: add Django example
test: cover NOT NULL without default on existing table
```

## Pull request checklist

- [ ] Tests added for new behavior
- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] `mrt check examples/blog/alembic/versions/` still works
