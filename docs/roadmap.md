# Roadmap

Items are tracked as GitHub issues. This page is a high-level overview.

---

## Near-term

### Single-head revision check ([#72](https://github.com/croc100/pytest-mrt/issues/72))

Add a built-in default test that fails when the migration chain has more than one head. A diverged head is almost always an unresolved merge conflict and will break deployments silently. pytest-alembic has this; pytest-mrt should too.

### GitHub Actions action ([#74](https://github.com/croc100/pytest-mrt/issues/74))

A dedicated action (`croc100/pytest-mrt-action`) that wraps `mrt check`, posts findings as a job summary, and optionally annotates changed migration files inline. The `--format json` output already exists — this is the CI integration layer on top.

```yaml
- uses: croc100/pytest-mrt-action@v1
  with:
    migrations-dir: alembic/versions/
```

### r/Python showcase post ([#75](https://github.com/croc100/pytest-mrt/issues/75))

After rolling deploy compat checks ship, write a showcase covering what pytest-mrt does, how it differs from pytest-alembic and django-migration-linter, and a concrete example. Goal: grow star count toward 50+ for awesome-django eligibility.

---

## Medium-term

### Rolling deploy compatibility checks ([#73](https://github.com/croc100/pytest-mrt/issues/73))

Static analysis pass that checks whether a migration is safe during a rolling deploy — i.e., whether the old app version can still run against the new schema while the deploy is in progress.

This is a different axis from rollback safety:

- **Rollback safety** (what pytest-mrt tests today): can the migration be undone?
- **Rolling deploy safety** (new): can the old app survive the new schema long enough to be replaced?

Patterns to detect: DROP COLUMN, RENAME COLUMN, ADD NOT NULL without default, DROP TABLE, incompatible type changes.

New flag: `mrt check --check-compat`. Alembic and Django both.

### pytest-dev contribution ([#76](https://github.com/croc100/pytest-mrt/issues/76))

PR [#14576](https://github.com/pytest-dev/pytest/pull/14576) to pytest-dev: show which items are missing in `dict.items()` / `dict.keys()` set comparisons (`>=`, `<=`, `>`, `<`), the same way set comparisons already work. Waiting for maintainer review.

---

## Why this order

The single-head check and GitHub Action are both small, self-contained, and directly address gaps vs. competing tools. Rolling deploy compat is bigger and becomes the centerpiece of the showcase post — do it second so the post has something new to announce.
