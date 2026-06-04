# Roadmap

## Current status: Beta (v0.6.x)

pytest-mrt is actively used in production. The core API (`MRTConfig`, `mrt` fixture, `mrt check`) is stable. Breaking changes will be versioned.

---

## v0.7 — Notifications & integrations

- [ ] Slack notification on detection (`--notify-slack`)
- [ ] JSON output improvements for DataDog / Grafana ingestion
- [ ] `mrt check` exit code breakdown (separate codes for errors vs. warnings)
- [ ] Django: `squashmigrations` detection (squashed migrations with unresolved refs)

## v0.8 — Coverage & confidence

- [ ] `--coverage` flag: show which patterns were tested vs. inferred
- [ ] Per-pattern confidence score in JSON output
- [ ] HTML report: link each finding to the source line
- [ ] Benchmark: publish detection latency vs. migration count

## v1.0 — Production ready

Target criteria:
- ✅ PostgreSQL, SQLite, MySQL/MariaDB dynamic verification
- ✅ Alembic + Django migration support
- ✅ 30+ static analysis patterns
- [ ] Oracle support
- [ ] SQL Server support
- [ ] Zero false-positive guarantee on the pattern test suite
- [ ] Public detection accuracy report
- [ ] Stable plugin API for custom patterns

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
