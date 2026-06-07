# Roadmap

## Current status: Production/Stable (v1.2.0)

pytest-mrt is production-ready. The core API (`MRTConfig`, `mrt` fixture, `mrt check`) is stable and
breaking changes will be versioned. See [`docs/api.md`](docs/api.md) for the stability guarantee.

---

## v0.7 — Notifications & integrations (partially shipped in v0.8)

- [ ] Slack notification on detection (`--notify-slack`)
- [ ] JSON output improvements for DataDog / Grafana ingestion
- `mrt check` exit code breakdown (0 = clean / 1 = warnings / 2 = errors)
- [ ] Django: `squashmigrations` detection (squashed migrations with unresolved refs)

## v0.8 — Coverage & confidence

- 30 static analysis patterns (3 new: DROP FK, CREATE TRIGGER, CREATE TYPE)
- Actionable error messages with concrete fix suggestions
- False-positive test suite (`tests/test_false_positives.py`)
- Public detection accuracy report (`docs/accuracy.md`)
- PostgreSQL CI
- MySQL CI
- Python 3.13 support + ruff/mypy CI enforcement
- Test coverage 88%

## v0.9 — Django dynamic verification

- **Django dynamic rollback**: `DjangoMigrationRunner` + `DjangoRollbackVerifier` — full upgrade/downgrade/verify cycle
- Oracle support (`pytest-mrt[oracle]`, CI against Oracle Free 23c)
- SQL Server support (`pytest-mrt[mssql]`, CI against SQL Server 2022)
- GitHub Discussions enabled

## v1.0 — Production ready (shipped)

- PostgreSQL, SQLite, MySQL/MariaDB dynamic verification
- Oracle, SQL Server dynamic verification
- Alembic + Django migration support (static + dynamic)
- 44 static analysis patterns
- Zero false-positive guarantee on the pattern test suite
- Public detection accuracy report
- Stable plugin API for custom patterns
- Django dynamic rollback verification

## v1.1.0 — Built-in default tests + schema drift (shipped)

- **6 built-in default tests** auto-injected when `mrt` fixture is configured (no test files needed):
  - `test_mrt_single_head` — migration history has exactly one head
  - `test_mrt_upgrade` — `alembic upgrade head` completes cleanly
  - `test_mrt_downgrade_base` — full up/down/up cycle completes cleanly
  - `test_mrt_up_down_consistency` — every migration is safely reversible
  - `test_mrt_static_no_errors` — zero static analysis errors
  - `test_mrt_schema_matches_models` — DB schema matches ORM models after upgrade
- **Schema drift detection** (`mrt drift`) — compare live DB schema against SQLAlchemy models
- Opt-out per test via `MRTConfig(skip_default_tests={...})`

## v1.2.0 — Rule codes + suppression syntax (shipped)

- **MRT rule codes** (MRT101–MRT902) — every pattern now has a unique code
- **`# noqa: MRTxxx` suppression** — ruff/flake8-compatible per-line suppression syntax
- Backward-compatible `# mrt: ignore` legacy syntax retained
- CLI refactored into `commands/` subpackage (cleaner codebase)
- Test coverage: `default_tests.py` and `drift.py` at 100%
- Documentation fully updated (pattern counts, version refs, suppression docs)

---

## Next / Under consideration

These are not committed to a specific version yet:

- **`mrt check --watch`** — re-run on file change during development
- **Django: `squashmigrations` detection** — squashed migrations with unresolved refs
- **Per-pattern confidence scores** in JSON output
- **HTML report: source line links** — click a finding to jump to the migration file
- **Sentry integration** — report migration failures as Sentry events
- **GitHub App** — automated PR comments with migration risk summary
- **VS Code extension** — inline warnings in migration files

---

## What won't be in scope

- Executing migrations in production (this is a *testing* tool only)
- Schema diff tools (use `alembic check` or `django-migration-linter`)
- ORM-agnostic support (focused on Alembic and Django)

---

## How to influence the roadmap

Open an issue tagged `roadmap` with your use case.  
Sponsorship fast-tracks specific items — see [GitHub Sponsors](https://github.com/sponsors/croc100).
