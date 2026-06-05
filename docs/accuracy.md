# Detection Accuracy Report

This document describes what each static analysis pattern in pytest-mrt detects, what it misses,
and the false-positive risk for each check. The false-positive suite (`tests/test_false_positives.py`)
enforces the "will NOT trigger" column automatically on every CI run.

Last updated: 2026-06-06 · pytest-mrt v0.8.0 · 30 Alembic patterns + 10 Django patterns

---

## How to read this table

| Column | Meaning |
|--------|---------|
| **Severity** | `error` — blocks rollback; `warning` — may block or degrade |
| **Will catch** | Cases the pattern reliably detects |
| **Will NOT catch** | Known blind spots (not false negatives from bugs — architectural limits) |
| **False-positive risk** | How often the pattern fires on safe code |

---

## Alembic patterns (30)

### Per-file checks

#### 1. Missing downgrade
| | |
|---|---|
| **Severity** | error |
| **Will catch** | Migration file with no `downgrade()` function at all |
| **Will NOT catch** | `downgrade()` that exists but does nothing useful (covered by #2) |
| **False-positive risk** | None — a missing function is unambiguous |

---

#### 2. No-op downgrade
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `downgrade()` whose body is `pass` or a bare docstring/comment |
| **Will NOT catch** | Downgrade that calls a helper which is itself a no-op |
| **False-positive risk** | None — AST check confirms the body is effectively empty |

---

#### 3. DROP COLUMN in upgrade
| | |
|---|---|
| **Severity** | error |
| **Will catch** | Any `op.drop_column()` in `upgrade()` |
| **Will NOT catch** | Column dropped via raw `ALTER TABLE ... DROP COLUMN` SQL |
| **False-positive risk** | Low — intentional destructive drops should be in dedicated migrations with documented rationale |

---

#### 4. DROP TABLE in upgrade
| | |
|---|---|
| **Severity** | error |
| **Will catch** | Any `op.drop_table()` in `upgrade()` |
| **Will NOT catch** | `DROP TABLE` via `op.execute()` raw SQL |
| **False-positive risk** | Low — same rationale as #3 |

---

#### 5. TRUNCATE
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `op.execute("TRUNCATE ...")` or `op.execute(sa.text("TRUNCATE ..."))` in `upgrade()` |
| **Will NOT catch** | `DELETE FROM` without a WHERE clause (functionally equivalent but different SQL) |
| **False-positive risk** | None — TRUNCATE is always destructive |

---

#### 6. NOT NULL without default
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.add_column` / `op.alter_column` with `nullable=False` and no `server_default` or `default` |
| **Will NOT catch** | NOT NULL added via raw SQL `ALTER TABLE ... SET NOT NULL` (covered by #25) |
| **False-positive risk** | Low — fires on new tables too; intentional for new tables can be suppressed with `skip` |

---

#### 7. Column type change
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.alter_column(..., type_=...)` in `upgrade()` |
| **Will NOT catch** | Type change via raw `ALTER TABLE ... ALTER COLUMN ... TYPE` SQL |
| **False-positive risk** | Medium — safe casts (e.g. `VARCHAR(50)` → `VARCHAR(100)`) also trigger; validate manually |

---

#### 8. Raw SQL (op.execute)
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.execute()` in `upgrade()` with no corresponding `execute` in `downgrade()` |
| **Will NOT catch** | Safe read-only `SELECT` in execute (SELECT never needs reversal — but this check fires regardless) |
| **False-positive risk** | Medium — DDL-only migrations that also SELECT will trigger; a matching `execute` in downgrade suppresses it |

---

#### 9. Data transform without reverse
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | Bulk `UPDATE` in `upgrade()` with no `UPDATE` in `downgrade()` |
| **Will NOT catch** | `INSERT` or `DELETE` data transforms without reversal (partial coverage) |
| **False-positive risk** | Low — one-way data transforms are rarely intentional without documentation |

---

#### 10. CASCADE DELETE
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `ondelete="CASCADE"` on any FK definition in `upgrade()` |
| **Will NOT catch** | Cascade behavior defined in database triggers outside migration files |
| **False-positive risk** | Medium — some schemas intentionally use cascade; audit each finding |

---

#### 11. INDEX without CONCURRENTLY
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.create_index()` without `postgresql_concurrently=True` |
| **Will NOT catch** | Index creation via raw SQL without `CONCURRENTLY` keyword |
| **False-positive risk** | Medium — non-PostgreSQL databases don't support `CONCURRENTLY`; safe to ignore for SQLite/MySQL |

---

#### 12. ADD COLUMN with volatile DEFAULT
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.add_column(..., Column(..., default=...))` — Python-side default rewrites the table on all PG versions |
| **Will NOT catch** | Default expressed as a callable or ORM-level event |
| **False-positive risk** | Low — Python-side defaults in migrations almost always cause table rewrites |

---

#### 13. ADD COLUMN with server_default
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.add_column(..., Column(..., server_default=...))` — rewrites table on PostgreSQL < 11 |
| **Will NOT catch** | Server defaults set via `op.execute("ALTER TABLE ... SET DEFAULT ...")` |
| **False-positive risk** | Medium — safe on PostgreSQL 11+; verify your database version |

---

#### 14. UNIQUE constraint on existing data
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | Any `op.create_unique_constraint()` in `upgrade()` |
| **Will NOT catch** | UNIQUE added via raw SQL or as part of a new table creation |
| **False-positive risk** | Medium — safe on empty tables or freshly populated ones; check for duplicates before deploying |

---

#### 15. DROP INDEX without reverse
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.drop_index()` in `upgrade()` with no `op.create_index()` in `downgrade()` |
| **Will NOT catch** | Index drop via raw SQL |
| **False-positive risk** | Low — intentional permanent index removal is uncommon without documentation |

---

#### 16. DROP CONSTRAINT without reverse
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.drop_constraint()` in `upgrade()` without a matching `create_foreign_key` / `create_unique_constraint` / `create_check_constraint` / `create_primary_key` in `downgrade()` |
| **Will NOT catch** | Constraint drop via raw SQL |
| **False-positive risk** | Low |

---

#### 17. rename_table without reverse
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `op.rename_table(old, new)` without `op.rename_table(new, old)` in `downgrade()` |
| **Will NOT catch** | Rename via raw SQL `ALTER TABLE ... RENAME TO` |
| **False-positive risk** | None — verifies both argument positions exactly |

---

#### 18. rename_column without reverse
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `op.alter_column(..., new_column_name=...)` in `upgrade()` without corresponding rename in `downgrade()` |
| **Will NOT catch** | Column rename via raw SQL |
| **False-positive risk** | None — checks for the presence of `new_column_name` kwarg |

---

#### 19. DROP VIEW without reverse
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `op.execute("DROP VIEW ...")` in `upgrade()` without `CREATE VIEW` in `downgrade()` |
| **Will NOT catch** | View dropped via dialect-specific API |
| **False-positive risk** | Low |

---

#### 20. SEQUENCE modification
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `CREATE SEQUENCE`, `ALTER SEQUENCE`, or `setval(...)` in `upgrade()` |
| **Will NOT catch** | Sequence manipulation via ORM-level events |
| **False-positive risk** | Low — sequences are not transactional; the warning is almost always relevant |

---

#### 21. ENUM value added
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `ALTER TYPE ... ADD VALUE` in `upgrade()` (PostgreSQL-specific) |
| **Will NOT catch** | ENUM changes on MySQL (different syntax), ENUM type replacement |
| **False-positive risk** | None — `ADD VALUE` is irreversible once any row uses the new value |

---

#### 22. Multi-step destructive migration
| | |
|---|---|
| **Severity** | error |
| **Will catch** | Migration that adds a column, bulk-updates data into it, and drops the original column — all in one step |
| **Will NOT catch** | Same pattern spread across multiple migrations |
| **False-positive risk** | Low — the combination of add + UPDATE + drop in one migration is inherently unsafe |

---

#### 23. NOT NULL without reverting nullable
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.alter_column(..., nullable=False)` in `upgrade()` without `nullable=True` in `downgrade()` |
| **Will NOT catch** | NOT NULL set via raw SQL |
| **False-positive risk** | Low |

---

#### 24. NOT NULL via raw SQL without reverse
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `ALTER TABLE ... SET NOT NULL` in `upgrade()` without `DROP NOT NULL` in `downgrade()` |
| **Will NOT catch** | NOT NULL enforced by a CHECK constraint |
| **False-positive risk** | Low |

---

#### 25. bulk_insert without reverse
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.bulk_insert()` in `upgrade()` without `op.delete()` or `DELETE` SQL in `downgrade()` |
| **Will NOT catch** | Data inserted via `op.execute("INSERT ...")` — covered by #8 |
| **False-positive risk** | Low |

---

#### 26. context.execute without reverse
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `context.execute()` / `ctx.execute()` / `conn.execute()` / `connection.execute()` in `upgrade()` without a matching execute in `downgrade()` |
| **Will NOT catch** | Execute called through an arbitrary variable name |
| **False-positive risk** | Medium — same caveats as #8; a matching execute in downgrade suppresses it |

---

#### 27. DROP COLUMN in batch_alter_table
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `op.drop_column()` inside `op.batch_alter_table()` context manager in `upgrade()` |
| **Will NOT catch** | Drop occurring outside a batch context (covered by #3) |
| **False-positive risk** | None |

---

#### 28. DROP CONSTRAINT in batch_alter_table
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `op.drop_constraint()` inside `op.batch_alter_table()` without recreating it in `downgrade()` |
| **Will NOT catch** | Constraint dropped outside batch context (covered by #16) |
| **False-positive risk** | Low |

---

#### 29. DROP FOREIGN KEY without restore
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `op.drop_constraint(type_='foreignkey')` in `upgrade()` without `op.create_foreign_key()` in `downgrade()` |
| **Will NOT catch** | FK dropped via raw `ALTER TABLE ... DROP FOREIGN KEY` SQL |
| **False-positive risk** | Low — referential integrity should always be restored on rollback |

---

#### 30. CREATE TRIGGER without DROP TRIGGER
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `CREATE TRIGGER` SQL in `upgrade()` without `DROP TRIGGER` SQL in `downgrade()` |
| **Will NOT catch** | Trigger created via a stored procedure or database-specific API |
| **False-positive risk** | Low |

---

#### 31. CREATE TYPE without DROP TYPE
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `CREATE TYPE` SQL in `upgrade()` without `DROP TYPE` SQL in `downgrade()` |
| **Will NOT catch** | Custom type created via SQLAlchemy TypeDecorator at ORM level |
| **False-positive risk** | Low — custom types left behind block re-running the migration |

---

### Cross-migration graph checks

#### G1. Multiple migration heads
| | |
|---|---|
| **Severity** | error |
| **Will catch** | Two migration files that both reference the same `down_revision` (branched history) |
| **Will NOT catch** | Merge migrations already using a tuple `down_revision` |
| **False-positive risk** | None — detects unresolved branches that will cause `alembic upgrade head` to fail |

---

#### G2. Data hole chain
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | Migration A drops column X; migration B adds column X back — schema is restored on rollback but original data is permanently gone |
| **Will NOT catch** | The same pattern across non-adjacent migrations in a long chain |
| **False-positive risk** | Low — the structural pattern (drop then re-add same column name) is rarely coincidental |

---

#### G3. Orphaned migration
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | Migration files unreachable from any current head in the dependency graph |
| **Will NOT catch** | Orphans in branches that were intentionally kept separate |
| **False-positive risk** | Medium — feature branches and squashed migrations may appear as orphans; use `--skip` to suppress |

---

## Django patterns (10)

#### D1. RemoveField
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `migrations.RemoveField(...)` — permanent column data loss on rollback |
| **Will NOT catch** | Field removed via `RunSQL` |
| **False-positive risk** | None |

---

#### D2. DeleteModel
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `migrations.DeleteModel(...)` — all table data lost on rollback |
| **Will NOT catch** | Table dropped via `RunSQL` |
| **False-positive risk** | None |

---

#### D3. AddField NOT NULL (no default)
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `AddField` with `null=False` and no `default=` — will fail on non-empty tables |
| **Will NOT catch** | NOT NULL field added via `RunSQL` |
| **False-positive risk** | Low |

---

#### D4. AlterField NOT NULL (no default)
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `AlterField` changing an existing field to `null=False` without a `default=` |
| **Will NOT catch** | NULL constraint change via `RunSQL` |
| **False-positive risk** | Low |

---

#### D5. RunSQL without reverse_sql
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `RunSQL(forward_sql)` without a `reverse_sql` argument |
| **Will NOT catch** | Reverse SQL that is present but logically incorrect |
| **False-positive risk** | Low — read-only SQL in `RunSQL` is uncommon; add `reverse_sql=""` to document intentional one-way operations |

---

#### D6. RunSQL with TRUNCATE/DROP
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `RunSQL` containing `TRUNCATE` or `DROP TABLE` |
| **Will NOT catch** | Destructive SQL in a helper called from `RunSQL` |
| **False-positive risk** | None |

---

#### D7. RunPython without reverse_code
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `RunPython(forwards_func)` without `reverse_code=` argument |
| **Will NOT catch** | Reverse function that exists but does nothing (not checked for no-op) |
| **False-positive risk** | Low |

---

#### D8. RenameModel without reverse
| | |
|---|---|
| **Severity** | error |
| **Will catch** | `migrations.RenameModel(old_name, new_name)` — checks that downgrade performs the inverse rename |
| **Will NOT catch** | Rename via `RunSQL` |
| **False-positive risk** | None |

---

#### D9. AddIndex without atomic=False
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `AddIndex` on a migration without `atomic = False` — `CREATE INDEX CONCURRENTLY` requires a non-atomic migration on PostgreSQL |
| **Will NOT catch** | Index added via `RunSQL` with `CONCURRENTLY` |
| **False-positive risk** | Medium — only relevant for PostgreSQL with CONCURRENTLY; MySQL does not have this requirement |

---

#### D10. Dangerous DDL without atomic=False
| | |
|---|---|
| **Severity** | warning |
| **Will catch** | `RemoveField` or `DeleteModel` inside an atomic migration — on some databases these cannot be rolled back even within a transaction |
| **Will NOT catch** | Multi-database setups where only one database requires non-atomic |
| **False-positive risk** | Low |

---

## Summary

| Scope | Total patterns | Error | Warning |
|-------|---------------|-------|---------|
| Alembic per-file | 29 | 13 | 16 |
| Alembic graph | 3 | 1 | 2 |
| Django | 10 | 5 | 5 |
| **Total** | **42** | **19** | **23** |

False-positive risk distribution across all 42 patterns:

| Risk level | Count |
|-----------|-------|
| None | 17 |
| Low | 17 |
| Medium | 8 |

The false-positive test suite (`tests/test_false_positives.py`) enforces 30+ cases that must
produce zero warnings, covering the most common medium-risk patterns.

---

## Reporting accuracy issues

If you find a false positive or false negative, open an issue tagged `accuracy` at
[github.com/croc100/pytest-mrt/issues](https://github.com/croc100/pytest-mrt/issues).
Include the migration file and the unexpected finding.
