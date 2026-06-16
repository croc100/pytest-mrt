# Roadmap

Items are tracked as GitHub issues. This page is a high-level overview.

---

## Shipped

### v1.6.0 — Fine-grained step control (main, pending release)

- `upgrade_to()`, `upgrade_one()`, `downgrade_one()`, `downgrade_to()`, `current_revision()` — test data migration logic at any intermediate point in the migration chain

### v1.5.0 — Scope reduction

- Removed `mrt fix` and `mrt clean-backups` — out of scope for a *testing* tool
- Fixed `RollbackVerifier` false positive on failed custom seeds

### v1.4.0 — CI integration + rolling deploy safety

- `mrt check --format json/html` — structured output for CI pipelines and HTML safety reports
- `mrt check --watch` — re-run on file change during development
- `mrt check --min-revision` — skip revisions older than a configured floor
- `mrt check --check-compat` — rolling-deploy compatibility checks (MRT701–MRT705)
- Django squashmigrations detection — MRT601/MRT602
- `croc100/pytest-mrt-action` v1.0.0 — GitHub Actions integration

### v1.3.0 — Incremental CI + pre-commit

- `mrt check --since` — scan only new migrations in PRs
- pre-commit hook (`.pre-commit-hooks.yaml`)

### v1.1.0–v1.2.0 — Default tests + rule codes

- Six built-in default tests auto-injected on fixture configuration
- Schema drift detection (`mrt drift`, `assert_schema_matches()`)
- MRT rule codes (MRT101–MRT902) and `# noqa: MRTxxx` suppression

### v1.0.0 — Production/Stable

- Full database coverage: PostgreSQL, SQLite, MySQL/MariaDB, Oracle, SQL Server
- Full migration framework coverage: Alembic (static + dynamic) and Django (static + dynamic)
- 44+ static analysis patterns, public accuracy report

---

## Under consideration

### Django squashmigrations: dynamic rollback testing

Static detection of squashmigrations is already in v1.4.0 (MRT601/MRT602). The next step is dynamic verification: run the rollback plan through the squashed migration graph and verify it succeeds. Currently skipped in `check_all()`.

### `--check-compat` Django support

Rolling-deploy compatibility checks (`--check-compat`, MRT7xx) are currently Alembic-only. Extending to Django migrations requires mapping Django operation types to the same compat patterns.

### Per-pattern confidence scores

Add a `confidence` field to `mrt check --format json` output. Lets downstream tooling suppress known false-positive-prone patterns without using `# noqa`.

### HTML report: source line links

Click a finding in the HTML report to jump to the exact line in the migration file. Requires either embedding file contents or linking to the file on disk/GitHub.

### Sentry integration

Report dynamic rollback failures as Sentry events, enabling production-side alerting when a migration that was not tested fails in the field.

---

## What won't be in scope

- Executing migrations in production (this is a *testing* tool only)
- Migration code generation / auto-fix (removed in v1.5.0 — out of scope)
- Schema diff tools (use `alembic check` or `django-migration-linter`)
- ORM-agnostic support (focused on Alembic and Django)

---

## How to influence the roadmap

Open an issue tagged `roadmap` with your use case.
Sponsorship fast-tracks specific items — see [GitHub Sponsors](https://github.com/sponsors/croc100).
