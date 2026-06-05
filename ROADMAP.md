# Roadmap

## Current status: Production/Stable (v0.8.x)

pytest-mrt is production-ready. The core API (`MRTConfig`, `mrt` fixture, `mrt check`) is stable and
breaking changes will be versioned. See [`docs/api.md`](docs/api.md) for the stability guarantee.

---

## v0.7 — Notifications & integrations ✅ (partially shipped in v0.8)

- [ ] Slack notification on detection (`--notify-slack`)
- [ ] JSON output improvements for DataDog / Grafana ingestion
- ✅ `mrt check` exit code breakdown (0 = clean / 1 = warnings / 2 = errors)
- [ ] Django: `squashmigrations` detection (squashed migrations with unresolved refs)

## v0.8 — Coverage & confidence ✅

- ✅ 30 static analysis patterns (3 new: DROP FK, CREATE TRIGGER, CREATE TYPE)
- ✅ Actionable error messages with concrete fix suggestions
- ✅ False-positive test suite (`tests/test_false_positives.py`)
- ✅ Public detection accuracy report (`docs/accuracy.md`)
- ✅ PostgreSQL CI
- ✅ MySQL CI
- ✅ Python 3.13 support + ruff/mypy CI enforcement
- ✅ Test coverage 88%
- [ ] `--coverage` flag: show which patterns were exercised vs. inferred
- [ ] Per-pattern confidence score in JSON output
- [ ] HTML report: link each finding to the source line

## v0.9 — Django dynamic verification

- [ ] **Django dynamic rollback**: run `manage.py migrate <app> <prev>` and verify schema/data
      restoration (currently Django support is static analysis only — v1.0 hard requirement)
- [ ] Django: `squashmigrations` detection
- [ ] `mrt check --watch`: re-run on file change during development

## v1.0 — Production ready

Target criteria:
- ✅ PostgreSQL, SQLite, MySQL/MariaDB dynamic verification
- ✅ Alembic + Django migration support (static; dynamic in v0.9)
- ✅ 30+ static analysis patterns
- ✅ Zero false-positive guarantee on the pattern test suite
- ✅ Public detection accuracy report
- ✅ Stable plugin API for custom patterns
- [ ] Django dynamic rollback verification
- [ ] Oracle support
- [ ] SQL Server support

## Long-term / community-driven

These are planned but depend on interest or sponsorship:

- **Sentry integration** — report migration failures as Sentry events
- **GitHub App** — automated PR comments with migration risk summary
- **VS Code extension** — inline warnings in migration files
- **Oracle / SQL Server** — dynamic verification

---

## What won't be in scope

- Executing migrations in production (this is a *testing* tool only)
- Schema diff tools (use `alembic check` or `django-migration-linter`)
- ORM-agnostic support (focused on Alembic and Django)

---

## How to influence the roadmap

Open an issue tagged `roadmap` with your use case.  
Sponsorship fast-tracks specific items — see [GitHub Sponsors](https://github.com/sponsors/croc100).
