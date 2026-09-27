# Roadmap

## Current status: Production/Stable (v1.9.1 on PyPI and main)

pytest-mrt is production-ready. The core API (`MRTConfig`, `mrt` fixture, `mrt check`) is stable and
breaking changes will be versioned. See [`docs/api.md`](docs/api.md) for the stability guarantee.

---

## Scope

pytest-mrt answers one question: **will this migration's rollback actually restore the database, data
included?** Static detection and dynamic up/down/up verification are the two halves of that question,
and every feature should be traceable back to it.

### The feature surface is frozen (2026-09-28)

23 releases shipped in the 40 days after 2026-06-04, and not one of them started from a request made
outside the project. That is how a rollback verifier came to own a file watcher, an AI explainer and six
database backends. So new commands and new flags are on hold: **a new feature needs someone outside the
project to ask for it** — an issue or a discussion, not an idea.

What continues as normal: bug fixes, supported-version updates (Python, Django, Alembic, SQLAlchemy),
accuracy work on the rules that already exist, and documentation.

The precedent is v1.5.0, which removed `mrt fix`: generating migration code was a *transform*, and this
tool *verifies*. Anything that cannot answer the question above is a candidate for the same treatment.

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
- 44 static analysis patterns (45 as of v1.2.0, with MRT213 added)
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

## v1.3.0 — Incremental CI + pre-commit (shipped)

- **`mrt check --since <revision>`** — check only migrations added since a given revision; eliminates re-scanning full history on every PR
- **pre-commit hook** — `.pre-commit-hooks.yaml` ships with the package; two-line setup

---

## v1.4.0 — CI integration + rolling deploy (shipped)

- **`mrt check --format json/html`** — structured JSON output for CI tooling; self-contained HTML safety report (`--output` to write file)
- **`mrt check --watch`** — re-run automatically when migration files change; Ctrl-C to stop
- **`mrt check --min-revision`** — skip revisions at or before a floor; mirrors `MRTConfig.minimum_downgrade_revision`
- **`mrt check --check-compat`** — rolling-deploy compatibility checks (MRT701–MRT705): DROP COLUMN, RENAME COLUMN, DROP TABLE, ADD NOT NULL without default, incompatible type changes
- **Django squashmigrations detection** — MRT601/MRT602: catches `RunPython` without `reverse_code` in squashed migrations and suspicious squash filenames
- **`MRTConfig.minimum_downgrade_revision`** — permanent rollback floor respected by `check_all()` in the `mrt` fixture
- **`croc100/pytest-mrt-action` v1.0.0** — GitHub Actions action that posts findings as a job summary

---

## v1.5.0 — Scope reduction (breaking, shipped)

- **Removed `mrt fix` and `mrt clean-backups`** — migration code generation is a *transform* operation, not a *verify* operation. Out of scope. Projects that rely on these must pin `pytest-mrt<1.5.0`.
- **Removed `fixable` field from `mrt check --format json`** — advertised the removed auto-fix capability. Breaking for downstream tooling that read this field.
- **Fixed** `RollbackVerifier` false positive on failed custom seeds — rows whose `INSERT` fails are no longer tracked, eliminating "lost after rollback" false positives.

---

## v1.6.0 — Fine-grained step control (shipped)

- **`upgrade_to(revision)`**, **`upgrade_one()`**, **`downgrade_one()`**, **`downgrade_to(revision)`**, **`current_revision()`** — call any migration step from a test, enabling mid-chain data seeding and assertion

---

## v1.7.0 — Django rolling-deploy compatibility (shipped)

- **`mrt check --check-compat` for Django** — `RemoveField` (MRT701), `RenameField` (MRT702), `DeleteModel`/`RenameModel`/`AlterModelTable` (MRT703), `AddField` NOT NULL without a default (MRT704). MRT705 (type change) stays Alembic-only, since Django's `AlterField` carries no reference to the previous type
- **Fixed** `--format json` leaking human-readable status lines into stdout, which made the output unparseable

---

## v1.8.0 — Supported versions and toolchain (shipped)

- **Python 3.14** declared and used as the primary CI version; 3.15 runs as a non-blocking prerelease leg
- **Django 5.2 LTS / 6.0 / 6.1** replace the end-of-life 4.2/5.0/5.1 matrix; the `django` extra floor moves to `>=4.2`
- **psycopg 3 alongside psycopg2** in the `postgres` extra, because SQLAlchemy 2.1 resolves a bare `postgresql://` URL to psycopg 3
- Dependency floors raised to versions that are actually tested: `pytest>=8.0`, `alembic>=1.13`, `typer>=0.12`, `anthropic>=1.0`
- CI services on PostgreSQL 18, MySQL 8.4 LTS, SQL Server 2025

---

## v1.9.0 — Correctness hardening (shipped)

- **Fixed** `MRTTestCase.assertDataIntact()` building SQL with unquoted identifiers, which broke on reserved-word and mixed-case table names
- **Fixed** file reads using the locale encoding, which broke non-ASCII migrations off UTF-8 locales
- **Fixed** `--since` silently skipping descendants of migrations using `swappable_dependency`
- **Fixed** `mrt explain` exiting 0 on failure; added `--model` to select the Claude model
- **Deprecated** `MRTConfig.explain_model` — it was never read; `mrt explain --model` replaces it

---

## v1.9.1 — Import hygiene (shipped)

- **`mrt` starts about twice as fast** — `import pytest_mrt` no longer drags SQLAlchemy in through `MRTTestCase`, which now loads on first use (`mrt --help` 0.34s to 0.19s)
- Function-local imports cut from 104 to 36; the ones that remain document why they stay

---

## Under consideration

These are not committed to a version yet:

- **Django squashmigrations: full rollback plan** — detect and test rollback paths through squashed migration graphs dynamically (static detection is already in v1.4.0)
- **Per-pattern confidence scores** in JSON output
- **HTML report: source line links** — click a finding to jump to the migration file
- **Sentry integration** — report migration failures as Sentry events
- **GitHub App** — automated PR comments with migration risk summary
- **VS Code extension** — inline warnings in migration files
- **`mrt check --check-compat` Django support** — currently Alembic only

---

## What won't be in scope

- Executing migrations in production (this is a *testing* tool only)
- **Migration code generation / auto-fix** — removed in v1.5.0 (out of scope: "transform", not "verify")
- Schema diff tools (use `alembic check` or `django-migration-linter`)
- ORM-agnostic support (focused on Alembic and Django)

---

## How to influence the roadmap

Open an issue tagged `roadmap` with your use case.  
Sponsorship fast-tracks specific items — see [GitHub Sponsors](https://github.com/sponsors/croc100).
