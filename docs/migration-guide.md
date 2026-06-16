# Upgrade Guide

This document covers breaking changes and required actions when upgrading pytest-mrt across major versions.

---

## v1.5.x → v1.6

No breaking changes. Drop-in upgrade.

**New in v1.6:**

- `upgrade_to(revision)`, `upgrade_one()`, `downgrade_one()`, `downgrade_to(revision)`, `current_revision()` — fine-grained step control in the `mrt` fixture.

**Action required:** None.

---

## v1.4.x → v1.5

**Breaking changes:**

| Area | Change |
|------|--------|
| `mrt fix` command | Removed entirely |
| `mrt clean-backups` command | Removed entirely |
| `mrt check --format json` | `fixable` field removed from each finding |

**Migration steps:**

1. Remove any `mrt fix` or `mrt clean-backups` calls from your scripts and CI pipelines.
2. If downstream tooling reads the `fixable` field from `mrt check --format json`, update it to ignore or omit that field.
3. If you have `_mrt_backups` tables left over from a previous `mrt fix` run, drop them manually.

Pin to `pytest-mrt<1.5.0` if you need to keep using `mrt fix`.

---

## v1.3.x → v1.4

No breaking changes. Drop-in upgrade.

**New in v1.4:**

- `mrt check --format json/html` — structured output and self-contained HTML reports.
- `mrt check --watch` — re-run on file change during development.
- `mrt check --min-revision` / `MRTConfig.minimum_downgrade_revision` — rollback testing floor.
- `mrt check --check-compat` — rolling-deploy compatibility checks (MRT701–MRT705).
- Django squashmigrations detection (MRT601/MRT602).

**Action required:** None.

---

## v1.x → v1.3

No breaking changes. Drop-in upgrade.

**New in v1.3:**

- `mrt check --since <revision>` — incremental analysis for CI.
- pre-commit hook support via `.pre-commit-hooks.yaml`.

**Action required:** None.

---

## v1.x → v1.2

No breaking changes. Drop-in upgrade.

**New in v1.2:**

- Every pattern now has a unique rule code (`MRT101`–`MRT902`).
- `# noqa: MRTxxx` suppression syntax (ruff/flake8-compatible).
- Legacy `# mrt: ignore` syntax is retained and still works.

**Action required:** None. Existing suppression comments continue to work.

---

## v0.x → v1.0

**Breaking changes:**

| Area | Change |
|------|--------|
| `MRTConfig` | `engine_url` renamed to `db_url` |
| Default tests | 6 built-in tests are now auto-injected when `mrt` fixture is configured. Opt out per test with `skip_default_tests={...}`. |
| Exit codes | `mrt check` now exits `0` (clean) / `1` (warnings) / `2` (errors). Previously always `0` or `1`. |

**Migration steps:**

1. Replace `engine_url=` with `db_url=` in every `MRTConfig(...)` call.
2. If your CI checks `mrt check` exit code, update scripts to handle exit code `2` for errors.
3. If you don't want the built-in default tests, add `skip_default_tests={...}` to `MRTConfig`.

---

## Checking your installed version

```bash
mrt version
# or
pip show pytest-mrt | grep Version
```

---

## Reporting upgrade issues

Open an issue tagged `upgrade` at [github.com/croc100/pytest-mrt/issues](https://github.com/croc100/pytest-mrt/issues).
