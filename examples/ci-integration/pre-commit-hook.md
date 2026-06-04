# pytest-mrt as a pre-commit hook

Run static migration analysis before every commit — catches unsafe patterns
before they even reach CI.

## Setup

**1.** Install [pre-commit](https://pre-commit.com):

```bash
pip install pre-commit
```

**2.** Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: mrt-check
        name: Migration safety check
        language: system
        entry: mrt check
        args: [alembic/versions/, --strict]
        files: ^alembic/versions/.*\.py$
        pass_filenames: false
```

For Django:

```yaml
repos:
  - repo: local
    hooks:
      - id: mrt-check-django
        name: Django migration safety check
        language: system
        entry: mrt check
        args: [myapp/migrations/, --strict]
        files: ^.*/migrations/.*\.py$
        pass_filenames: false
```

**3.** Install the hook:

```bash
pre-commit install
```

**4.** Test it:

```bash
pre-commit run mrt-check --all-files
```

## What it does

Every `git commit` that touches a migration file will trigger `mrt check`:

```
Check Migration safety check.......................................Failed
- hook id: mrt-check
- exit code: 1

╭──────────┬────────────────────────┬───────┬──────┬──────────────────────────────────────╮
│ Revision │ Pattern                │ Sev   │ Line │ Message                              │
├──────────┼────────────────────────┼───────┼──────┼──────────────────────────────────────┤
│ 0042     │ DROP COLUMN in upgrade │ error │   18 │ Data permanently lost on rollback    │
╰──────────┴────────────────────────┴───────┴──────┴──────────────────────────────────────╯
1 error(s), 0 warning(s)
```

The commit is blocked until the issue is resolved.

## Note

The pre-commit hook only runs static analysis (no database needed).
For full rollback verification, add the `dynamic-check` job to your CI pipeline.
See `github-actions.yml` in this directory.
