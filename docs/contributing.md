# Contributing

The most valuable contribution is a new risk pattern — something pytest-mrt doesn't currently catch.

If you've been burned by a migration that caused a production incident, there's a good chance it should be in here.

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
pytest tests/ -v
```

## Adding a new risk pattern

1. Write a `_check_*` function in `pytest_mrt/core/detector.py`
2. Add it to the `_CHECKS` list at the bottom of that file
3. Write a positive test (pattern detected) and a negative test (clean migration not flagged) in `tests/test_detector.py`
4. Add the pattern to the table in `docs/patterns.md`

```python
def _check_my_pattern(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _upgrade_body(source)
    if re.search(r"some_pattern", body):
        return [RiskWarning(
            rev, fname,
            "Pattern name",
            "Human-readable explanation of why this is dangerous",
            "error",  # or "warning"
        )]
    return []
```

## Commit style

```
feat: add detection for X pattern
fix: handle edge case in Y check
docs: update patterns page
test: add negative case for Z
```

## Opening a PR

Use the PR template — it has a checklist to make sure nothing is missed.
