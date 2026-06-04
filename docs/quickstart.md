# Getting Started

## Install

```bash
pip install pytest-mrt
```

## Setup

Create a `conftest.py` in your test directory:

```python
import os
from pytest_mrt import MRTConfig

def pytest_configure(config):
    config._mrt_config = MRTConfig(
        alembic_ini="alembic.ini",
        db_url=os.environ["TEST_DATABASE_URL"],
    )
```

!!! tip "Use a dedicated test database"
    Never point pytest-mrt at your production database. Use a separate test DB that gets wiped on each run.

## Write your first test

```python
# test_migrations.py

def test_all_migrations_are_reversible(mrt):
    """Check every migration in sequence."""
    mrt.assert_all_reversible()


def test_this_pr_only(mrt):
    """Check a single revision — useful in CI to gate only what changed."""
    result = mrt.check_revision("abc123")
    assert result.passed, result.failure_summary()
```

## Run it

```bash
pytest tests/test_migrations.py -v -s
```

The `-s` flag lets the rich output render properly.

## Static analysis (no database)

Scan your migration files for known dangerous patterns:

```bash
mrt check migrations/versions/
```

Add to CI as a fast pre-flight check:

```yaml
- name: Static migration analysis
  run: mrt check migrations/versions/ --strict
```

`--strict` makes warnings fail the build too.

## GitHub Actions example

```yaml
name: CI

on: [push, pull_request]

jobs:
  migrations:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install pytest-mrt psycopg2-binary alembic
      - name: Static check
        run: mrt check migrations/versions/
      - name: Dynamic check
        env:
          TEST_DATABASE_URL: postgresql://postgres:test@localhost:5432/testdb
        run: pytest tests/test_migrations.py -v -s
```

## Configuration reference

```python
MRTConfig(
    alembic_ini="alembic.ini",       # path to alembic.ini
    db_url="postgresql://...",        # test database URL
    seed_rows=3,                      # rows seeded per table (default: 3)
)
```
