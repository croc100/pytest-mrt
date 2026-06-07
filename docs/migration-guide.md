# Upgrade Guide

This document covers breaking changes and required actions when upgrading pytest-mrt across major versions.

---

## v1.x → v1.2

No breaking changes.  Drop-in upgrade.

**New in v1.2:**

- Every pattern now has a unique rule code (`MRT101`–`MRT902`).
- `# noqa: MRTxxx` suppression syntax (ruff/flake8-compatible).
- Legacy `# mrt: ignore` syntax is retained and still works.

**Action required:** None.  Existing suppression comments continue to work.

---

## v1.x → v1.3 (upcoming)

No breaking changes planned.

**New in v1.3:**

- `mrt check --since <revision>` — incremental analysis for CI.
- pre-commit hook support via `.pre-commit-hooks.yaml`.

---

## v0.x → v1.0

**Breaking changes:**

| Area | Change |
|------|--------|
| `MRTConfig` | `engine_url` renamed to `db_url` |
| Default tests | 6 built-in tests are now auto-injected when `mrt` fixture is configured.  Opt out per test with `skip_default_tests={"test_mrt_upgrade"}`. |
| Exit codes | `mrt check` now exits `0` (clean) / `1` (warnings) / `2` (errors).  Previously always `0` or `1`. |

**Migration steps:**

1. Replace `engine_url=` with `db_url=` in every `MRTConfig(...)` call.
2. If your CI checks `mrt check` exit code, update scripts to handle exit code `2` for errors.
3. If you don't want the built-in default tests, add `skip_default_tests={...}` to `MRTConfig`.

---

## v0.8 → v0.9

No breaking changes.

**New:** Django dynamic rollback support via `DjangoMigrationRunner` and `DjangoRollbackVerifier`.  No action needed for Alembic-only projects.

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
