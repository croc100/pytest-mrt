# Contributing to pytest-mrt

Thank you for taking the time to contribute. This guide covers everything from setting up a local dev environment to submitting a production-ready pull request.

**New to open source?** Start with issues labeled [`good first issue`](https://github.com/croc100/pytest-mrt/labels/good%20first%20issue).

**Questions before contributing?** Use [GitHub Discussions](https://github.com/croc100/pytest-mrt/discussions) — not Issues.

---

## Table of contents

- [Development setup](#development-setup)
- [Running tests](#running-tests)
- [Project structure](#project-structure)
- [What to work on](#what-to-work-on)
- [Adding a new risk pattern](#adding-a-new-risk-pattern)
- [Code style](#code-style)
- [Commit conventions](#commit-conventions)
- [Pull request process](#pull-request-process)
- [Release process](#release-process)

---

## Development setup

### Prerequisites

- Python 3.10+
- Git
- (Optional) Docker — for PostgreSQL/MySQL integration tests

### Local setup

```bash
git clone https://github.com/croc100/pytest-mrt
cd pytest-mrt

# Create virtual environment (always use .venv)
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pip install pre-commit
pre-commit install
```

### Editor setup

The repo ships an `.editorconfig`. Most editors support it natively (VS Code, PyCharm, Vim, Neovim). If yours doesn't, install the EditorConfig plugin.

**Recommended VS Code extensions:**
- `ms-python.python`
- `charliermarsh.ruff`
- `editorconfig.editorconfig`

---

## Running tests

```bash
# All tests — SQLite only, no external dependencies required
coverage run -m pytest tests/ -v
coverage report

# Single file
pytest tests/test_detector.py -v

# Pattern match
pytest tests/ -k "test_drop_column" -v

# With PostgreSQL
TEST_DATABASE_URL=postgresql://localhost/mrt_test pytest tests/ -v

# With MySQL
TEST_DATABASE_URL=mysql+pymysql://root:pass@localhost/mrt_test pytest tests/ -v
```

### Using Docker (no local DB install needed)

```bash
# Start test databases
docker compose up -d postgres mysql

# Run against PostgreSQL
TEST_DATABASE_URL=postgresql://test:test@localhost:5432/mrt_test pytest tests/ -v

# Run against MySQL
TEST_DATABASE_URL=mysql+pymysql://test:test@localhost:3306/mrt_test pytest tests/ -v

# Teardown
docker compose down
```

### Coverage target

We aim for ≥ 85% coverage. New code must be accompanied by tests. Check your contribution's coverage with:

```bash
coverage run -m pytest tests/ -v
coverage report --include="pytest_mrt/*"
```

---

## Project structure

```
pytest_mrt/
├── __init__.py             # Public API: MRTConfig, __version__
├── plugin.py               # pytest plugin entry point + MRTFixture
├── config.py               # MRTConfig dataclass
├── cli.py                  # mrt CLI (typer)
├── reporter.py             # Rich console output
├── core/
│   ├── ast_analyzer.py     # MigrationAST — Alembic AST parsing
│   ├── detector.py         # Built-in Alembic risk checks
│   ├── fixer.py            # mrt fix — auto-generate downgrade()
│   ├── graph.py            # Migration dependency graph
│   ├── html_report.py      # mrt report — HTML output
│   ├── runner.py           # MigrationRunner — wraps alembic commands
│   ├── schema.py           # SchemaSnapshot + SchemaDiff
│   ├── seeder.py           # SmartSeeder — synthetic data generation
│   └── verifier.py         # RollbackVerifier — check_revision/check_all
└── adapters/
    ├── django_detector.py  # Django migration risk checks
    └── __init__.py

tests/
├── conftest.py             # pytester activation
├── test_config.py
├── test_cli.py
├── test_detector.py
├── test_django_detector.py
├── test_fixer.py
├── test_graph.py
├── test_html_report.py
├── test_integration.py     # SQLite end-to-end tests
├── test_plugin.py          # MRTFixture integration tests
├── test_reporter.py
├── test_schema.py
└── test_seeder.py

examples/
├── blog/                   # Alembic example with edge-case migrations
└── django-app/             # Django migration example
```

---

## What to work on

Check [open issues](https://github.com/croc100/pytest-mrt/issues) and the [ROADMAP](ROADMAP.md). Here's a guide by effort level:

### Good first issue (~1–2 hours)

- Add a static analysis pattern that isn't detected yet
- Improve an existing error message to be more actionable
- Add a test case for an edge condition
- Fix a typo or improve documentation clarity

### Medium effort (~half a day)

- Add an example to `examples/` for a common use case
- Add a new CI integration guide to `examples/ci-integration/`
- Improve HTML report output
- Add a new `mrt fix` heuristic

### Higher effort (discuss in an issue first)

- New database adapter (Oracle, SQL Server)
- Dynamic rollback testing for Django
- Async SQLAlchemy support
- Plugin marketplace / registry for custom checks

---

## Adding a new risk pattern

### Alembic pattern

Patterns live in `pytest_mrt/core/detector.py`. All checks receive a `MigrationAST` object — never parse raw source strings, which would produce false positives on commented-out code.

**Step 1: Write the check function**

```python
def _check_drop_not_null(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.method == "alter_column" and c.kw.get("nullable") is False:
            table = c.arg(0) or "?"
            col   = c.arg(1) or "?"
            warnings.append(_warn(
                m, "ALTER COLUMN to NOT NULL",
                f"op.alter_column('{table}', '{col}', nullable=False) will fail "
                "on tables with existing NULL values. Backfill NULLs first.",
                "error", line=c.node.lineno,
            ))
    return warnings
```

**Step 2: Register it**

Add it to `_PER_FILE_CHECKS` at the bottom of `detector.py`:

```python
_PER_FILE_CHECKS: list[Callable[[MigrationAST], list[RiskWarning]]] = [
    ...
    _check_drop_not_null,   # ← add here
]
```

**Step 3: Write tests**

In `tests/test_detector.py`, add both a positive case and a negative case:

```python
def test_alter_column_not_null_detected(versions_dir):
    (versions_dir / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.alter_column('users', 'email', nullable=False)
        def downgrade():
            op.alter_column('users', 'email', nullable=True)
    """))
    warnings = analyze_migrations(str(versions_dir))
    assert any(w.pattern == "ALTER COLUMN to NOT NULL" for w in warnings)


def test_alter_column_nullable_ok(versions_dir):
    (versions_dir / "001.py").write_text(textwrap.dedent("""
        revision = '001'
        down_revision = None
        branch_labels = None
        depends_on = None
        from alembic import op
        def upgrade():
            op.alter_column('users', 'email', nullable=True)
        def downgrade():
            op.alter_column('users', 'email', nullable=False)
    """))
    warnings = analyze_migrations(str(versions_dir))
    assert not any(w.pattern == "ALTER COLUMN to NOT NULL" for w in warnings)
```

**Step 4: Document it**

Add the pattern to the table in `docs/patterns.md`.

### Django pattern

Same process, but in `pytest_mrt/adapters/django_detector.py` using `DjangoMigrationAST`, and tests in `tests/test_django_detector.py`.

---

## Code style

We use **ruff** for linting and formatting (configured in `pyproject.toml`).

```bash
# Check
ruff check pytest_mrt/ tests/

# Fix and format
ruff check --fix pytest_mrt/ tests/
ruff format pytest_mrt/ tests/
```

Pre-commit hooks run these automatically on `git commit`. To run manually:

```bash
pre-commit run --all-files
```

### Key style rules

- **Type annotations**: all public functions and methods must have full type hints
- **Docstrings**: only for non-obvious functions. Describe *why*, not *what* the code does.
- **Comments**: only when the reason for the code is not obvious from the code itself
- **Line length**: 99 characters max
- **No `print()`**: use `rich.console.Console` for output in CLI code, or `logging` in library code

---

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short description>

<optional body>
```

**Types:**

| Type | When to use |
|------|-------------|
| `feat` | New feature or risk pattern |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Tests only (no production code change) |
| `refactor` | Code restructuring without behavior change |
| `perf` | Performance improvement |
| `ci` | CI/CD workflow changes |
| `chore` | Maintenance (deps, config, tooling) |

**Examples:**

```
feat: detect ALTER COLUMN to NOT NULL without backfill
fix: handle empty downgrade body when using Python 3.10 match statement
docs: add Jenkins integration example to ci-integration/
test: cover bulk_insert false positive in downgrade analysis
ci: switch coverage measurement from pytest-cov to coverage run
```

**Rules:**
- Use the imperative mood: "add support" not "added support"
- No period at the end of the subject line
- Keep the subject line ≤ 72 characters
- All commit messages must be in **English**

---

## Pull request process

1. **Open an issue first** for any non-trivial change. This prevents duplicate work and ensures the direction is aligned.

2. **Fork and create a branch:**
   ```bash
   git checkout -b feat/detect-alter-column-not-null
   ```

3. **Make your changes** with tests.

4. **Verify locally:**
   ```bash
   pre-commit run --all-files
   coverage run -m pytest tests/ -v
   coverage report
   mrt check examples/blog/alembic/versions/
   ```

5. **Open the PR** against `main`. Fill out the PR template fully — especially the "Why" and test evidence sections.

6. **Address review feedback** within 5 business days of the first review. If you need more time, leave a comment.

### PR checklist

- [ ] Tests added for new behavior (positive **and** negative case for patterns)
- [ ] All existing tests pass: `coverage run -m pytest tests/ -v`
- [ ] Coverage not reduced: `coverage report --include="pytest_mrt/*"`
- [ ] `mrt check examples/blog/alembic/versions/` exits 0
- [ ] New patterns documented in `docs/patterns.md`
- [ ] Commit messages follow conventional commits format
- [ ] No `Co-Authored-By` or merge commits in the branch

### Review SLA

| | Timeline |
|---|---|
| First review | Within 5 business days |
| Follow-up reviews | Within 2 business days |
| Merge after approval | Within 1 business day |

---

## Release process

Releases are fully automated. Maintainers only:

### Steps to release

```bash
# 1. Bump version in pyproject.toml
#    Edit: version = "0.8.0"

# 2. Update CHANGELOG.md

# 3. Commit the version bump
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.8.0"
git push origin main

# 4. Tag the release (triggers release.yml → publish.yml)
git tag v0.8.0 -m "v0.8.0"
git push origin v0.8.0
```

**What happens automatically:**
1. `release.yml` validates the tag matches `pyproject.toml`
2. `release.yml` generates release notes from commit history
3. `release.yml` creates the GitHub Release (draft: false)
4. `publish.yml` triggers on the "published" release event
5. `publish.yml` checks if the version is already on PyPI, then publishes

### Pre-releases

```bash
git tag v0.8.0-rc1 -m "v0.8.0-rc1"
git push origin v0.8.0-rc1
```

Pre-release tags (`-alpha`, `-beta`, `-rc*`) are automatically marked as pre-releases on GitHub.

---

## Getting help

- **Questions about usage:** [GitHub Discussions](https://github.com/croc100/pytest-mrt/discussions)
- **Bug reports:** [GitHub Issues](https://github.com/croc100/pytest-mrt/issues/new/choose)
- **Security issues:** [Private advisory](https://github.com/croc100/pytest-mrt/security/advisories/new)
