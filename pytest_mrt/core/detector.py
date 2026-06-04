from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RiskWarning:
    revision: str
    file: str
    pattern: str
    message: str
    severity: str  # "error" | "warning"


# ──────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────

def _fn_body(source: str, fn_name: str) -> str:
    """Extract the body of a top-level function."""
    m = re.search(
        rf"def {fn_name}\s*\([^)]*\)\s*(?:->.*?)?\s*:\s*\n((?:[ \t]+[^\n]*\n?)*)",
        source,
    )
    return m.group(1) if m else ""


def _upgrade_body(source: str) -> str:
    return _fn_body(source, "upgrade")


def _downgrade_body(source: str) -> str:
    return _fn_body(source, "downgrade")


def _is_noop(body: str) -> bool:
    stripped = body.strip()
    return stripped in ("", "pass") or stripped.startswith("pass\n")


# ──────────────────────────────────────────────
# individual checks
# ──────────────────────────────────────────────

def _check_downgrade_exists(source: str, rev: str, fname: str) -> list[RiskWarning]:
    if not re.search(r"def downgrade\s*\(", source):
        return [RiskWarning(rev, fname, "Missing downgrade",
                            "No downgrade() function — migration is permanently irreversible", "error")]
    return []


def _check_noop_downgrade(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _downgrade_body(source)
    if body and _is_noop(body):
        return [RiskWarning(rev, fname, "No-op downgrade",
                            "downgrade() body is `pass` — migration is irreversible", "error")]
    return []


def _check_drop_column_in_upgrade(source: str, rev: str, fname: str) -> list[RiskWarning]:
    if re.search(r"op\.drop_column\s*\(", _upgrade_body(source)):
        return [RiskWarning(rev, fname, "DROP COLUMN in upgrade",
                            "Column dropped in upgrade — data is permanently lost on rollback", "error")]
    return []


def _check_drop_table_in_upgrade(source: str, rev: str, fname: str) -> list[RiskWarning]:
    if re.search(r"op\.drop_table\s*\(", _upgrade_body(source)):
        return [RiskWarning(rev, fname, "DROP TABLE in upgrade",
                            "Table dropped in upgrade — all data is permanently lost on rollback", "error")]
    return []


def _check_truncate(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _upgrade_body(source)
    if re.search(r"TRUNCATE\s+", body, re.IGNORECASE):
        return [RiskWarning(rev, fname, "TRUNCATE",
                            "TRUNCATE in upgrade destroys data — cannot be rolled back", "error")]
    return []


def _check_run_python_no_reverse(source: str, rev: str, fname: str) -> list[RiskWarning]:
    warnings = []
    for m in re.finditer(r"op\.execute\s*\(.*?run_module|op\.run_async\s*\([^)]+\)", source, re.DOTALL):
        if "reverse_func" not in m.group(0):
            warnings.append(RiskWarning(rev, fname, "RunPython without reverse",
                                        "Data transformation has no reverse_func — cannot undo", "error"))
            break
    # Also check bulk execute_if patterns
    return warnings


def _check_not_null_no_default(source: str, rev: str, fname: str) -> list[RiskWarning]:
    warnings = []
    body = _upgrade_body(source)
    for m in re.finditer(r"op\.add_column\s*\(([^)]+)\)", body, re.DOTALL):
        col_expr = m.group(1)
        has_nullable_false = re.search(r"nullable\s*=\s*False", col_expr)
        has_server_default = re.search(r"server_default\s*=", col_expr)
        if has_nullable_false and not has_server_default:
            warnings.append(RiskWarning(
                rev, fname, "NOT NULL without default",
                "ADD NOT NULL column without server_default — will fail on non-empty tables "
                "and rollback may leave column in invalid state",
                "warning",
            ))
    return warnings


def _check_column_type_change(source: str, rev: str, fname: str) -> list[RiskWarning]:
    warnings = []
    body = _upgrade_body(source)
    for m in re.finditer(r"op\.alter_column\s*\([^)]+type_\s*=", body, re.DOTALL):
        warnings.append(RiskWarning(
            rev, fname, "Column type change",
            "Type change may be destructive — verify downgrade restores original type "
            "and existing data survives conversion",
            "warning",
        ))
        break
    return warnings


def _check_column_size_shrink(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _upgrade_body(source)
    # Look for VARCHAR/String with smaller length
    for m in re.finditer(
        r"op\.alter_column\s*\([^)]+(?:VARCHAR|String)\s*\(\s*(\d+)\s*\)", body, re.DOTALL | re.IGNORECASE
    ):
        return [RiskWarning(
            rev, fname, "Column size change",
            f"Column resized to {m.group(1)} chars — data exceeding new limit will be truncated on rollback",
            "warning",
        )]
    return []


def _check_raw_execute(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _upgrade_body(source)
    if re.search(r"op\.execute\s*\(", body):
        # If downgrade also has op.execute(), developer likely handled it manually
        down = _downgrade_body(source)
        if re.search(r"op\.execute\s*\(", down):
            return []
        return [RiskWarning(
            rev, fname, "Raw SQL (op.execute)",
            "op.execute() in upgrade has no corresponding op.execute() in downgrade — "
            "manually verify the downgrade correctly reverses this",
            "warning",
        )]
    return []


def _check_data_migration_no_reverse(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Detect bulk data transforms (UPDATE ... SET) in upgrade without reverse."""
    body = _upgrade_body(source)
    dg_body = _downgrade_body(source)
    if re.search(r"UPDATE\s+\w+\s+SET", body, re.IGNORECASE):
        if not re.search(r"UPDATE\s+\w+\s+SET", dg_body, re.IGNORECASE):
            return [RiskWarning(
                rev, fname, "Data transform without reverse",
                "Bulk UPDATE in upgrade but not in downgrade — data transformation is one-way",
                "warning",
            )]
    return []


def _check_cascade_delete(source: str, rev: str, fname: str) -> list[RiskWarning]:
    if re.search(r"ondelete\s*=\s*['\"]CASCADE['\"]|ON DELETE CASCADE", _upgrade_body(source), re.IGNORECASE):
        return [RiskWarning(
            rev, fname, "CASCADE DELETE",
            "FK with ON DELETE CASCADE added — child rows will be silently deleted if parent is deleted",
            "warning",
        )]
    return []


def _check_index_without_concurrently(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """PostgreSQL: CREATE INDEX without CONCURRENTLY locks the table."""
    body = _upgrade_body(source)
    if re.search(r"op\.create_index\s*\(", body):
        if not re.search(r"postgresql_concurrently\s*=\s*True", body):
            return [RiskWarning(
                rev, fname, "INDEX without CONCURRENTLY",
                "CREATE INDEX without postgresql_concurrently=True — locks table during index build",
                "warning",
            )]
    return []


def _check_add_column_with_default_on_large_table(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """PostgreSQL < 11: ADD COLUMN with DEFAULT rewrites entire table."""
    body = _upgrade_body(source)
    for m in re.finditer(r"op\.add_column\s*\([^)]+\)", body, re.DOTALL):
        col_expr = m.group(0)
        if re.search(r"server_default\s*=", col_expr) or re.search(r"default\s*=", col_expr):
            return [RiskWarning(
                rev, fname, "ADD COLUMN with DEFAULT",
                "Adding column with DEFAULT may rewrite the entire table on PostgreSQL < 11 — "
                "causes long lock on large tables",
                "warning",
            )]
    return []


def _check_unique_constraint_on_existing(source: str, rev: str, fname: str) -> list[RiskWarning]:
    body = _upgrade_body(source)
    if re.search(r"op\.create_unique_constraint\s*\(", body):
        return [RiskWarning(
            rev, fname, "UNIQUE constraint on existing data",
            "Adding UNIQUE constraint — will fail if existing rows have duplicate values",
            "warning",
        )]
    return []


def _check_drop_not_null(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Making column NOT NULL when downgrade re-adds NULL values."""
    up = _upgrade_body(source)
    if re.search(r"op\.alter_column\s*\([^)]+nullable\s*=\s*False", up, re.DOTALL):
        down = _downgrade_body(source)
        if not re.search(r"op\.alter_column\s*\([^)]+nullable\s*=\s*True", down, re.DOTALL):
            return [RiskWarning(
                rev, fname, "NOT NULL without reverting nullable",
                "Column set to NOT NULL but downgrade does not restore nullable=True",
                "warning",
            )]
    return []


def _check_batch_alter_drop(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """op.batch_alter_table is SQLite's way of doing ALTER — check for drops inside it."""
    warnings = []
    body = _upgrade_body(source)
    # Find all batch_alter_table context blocks
    for m in re.finditer(
        r"with\s+op\.batch_alter_table\s*\([^)]+\)\s*as\s+\w+\s*:(.*?)(?=\nwith\s|\ndef\s|\Z)",
        body, re.DOTALL
    ):
        block = m.group(1)
        if re.search(r"\.drop_column\s*\(", block):
            warnings.append(RiskWarning(
                rev, fname, "DROP COLUMN in batch_alter_table",
                "Column dropped inside op.batch_alter_table — "
                "data is permanently lost on rollback even if downgrade re-adds the column",
                "error",
            ))
        if re.search(r"\.drop_constraint\s*\(", block):
            warnings.append(RiskWarning(
                rev, fname, "DROP CONSTRAINT in batch_alter_table",
                "Constraint dropped inside op.batch_alter_table — "
                "downgrade must recreate it or data integrity is lost",
                "warning",
            ))
    return warnings


def _check_rename_without_reverse(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """op.rename_table / op.rename_column in upgrade but downgrade doesn't reverse it."""
    warnings = []
    up = _upgrade_body(source)
    down = _downgrade_body(source)

    if re.search(r"op\.rename_table\s*\(", up):
        if not re.search(r"op\.rename_table\s*\(", down):
            warnings.append(RiskWarning(
                rev, fname, "rename_table without reverse",
                "Table renamed in upgrade but downgrade does not rename it back — "
                "rollback leaves the table under the new name",
                "error",
            ))

    if re.search(r"op\.rename_column\s*\(|op\.alter_column\s*\([^)]+new_column_name", up, re.DOTALL):
        if not re.search(r"op\.rename_column\s*\(|op\.alter_column\s*\([^)]+new_column_name", down, re.DOTALL):
            warnings.append(RiskWarning(
                rev, fname, "rename_column without reverse",
                "Column renamed in upgrade but downgrade does not rename it back — "
                "app code referencing the old name will break after rollback",
                "error",
            ))

    return warnings


def _check_drop_view(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Dropping a view that application code may still reference."""
    body = _upgrade_body(source)
    if re.search(r"op\.execute\s*\(\s*['\"].*DROP\s+VIEW", body, re.IGNORECASE):
        down = _downgrade_body(source)
        if not re.search(r"op\.execute\s*\(\s*['\"].*CREATE\s+(OR\s+REPLACE\s+)?VIEW", down, re.IGNORECASE):
            return [RiskWarning(
                rev, fname, "DROP VIEW without reverse",
                "View dropped in upgrade but not recreated in downgrade — "
                "application queries against this view will fail after rollback",
                "error",
            )]
    return []


def _check_sequence_reset(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Sequences don't roll back — auto-increment gaps appear after rollback."""
    body = _upgrade_body(source)
    if re.search(r"op\.execute\s*\(\s*['\"].*(?:CREATE|ALTER)\s+SEQUENCE", body, re.IGNORECASE) or \
       re.search(r"op\.execute\s*\(\s*['\"].*setval\s*\(", body, re.IGNORECASE):
        return [RiskWarning(
            rev, fname, "SEQUENCE modification",
            "Sequence changes are not transactional in PostgreSQL — "
            "sequence counter will not revert after rollback, causing gaps or duplicates",
            "warning",
        )]
    return []


def _check_multi_step_destructive(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Classic zero-downtime anti-pattern: add column + migrate data + drop old column in one migration."""
    up = _upgrade_body(source)
    has_add = bool(re.search(r"op\.add_column\s*\(", up))
    has_drop = bool(re.search(r"op\.drop_column\s*\(", up))
    has_data = bool(re.search(r"op\.execute\s*\(\s*['\"].*UPDATE", up, re.IGNORECASE))
    if has_add and has_drop and has_data:
        return [RiskWarning(
            rev, fname, "Multi-step destructive migration",
            "Migration adds a column, migrates data, then drops the original in one step — "
            "this is irreversible: if rollback is needed, the migrated data cannot be reconstructed",
            "error",
        )]
    return []


def _check_enum_type_change(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Adding values to a PostgreSQL ENUM type — rollback fails if rows use the new value."""
    body = _upgrade_body(source)
    if re.search(r"op\.execute\s*\(\s*['\"].*ALTER\s+TYPE\s+\w+\s+ADD\s+VALUE", body, re.IGNORECASE):
        return [RiskWarning(
            rev, fname, "ENUM value added",
            "ALTER TYPE ... ADD VALUE cannot be rolled back in PostgreSQL if any row "
            "already uses the new enum value — downgrade will fail with a constraint error",
            "error",
        )]
    return []


def _check_drop_index_in_upgrade(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Dropping an index that app code or DB constraints depend on."""
    up = _upgrade_body(source)
    if re.search(r"op\.drop_index\s*\(", up):
        down = _downgrade_body(source)
        if not re.search(r"op\.create_index\s*\(", down):
            return [RiskWarning(
                rev, fname, "DROP INDEX without reverse",
                "Index dropped in upgrade but not recreated in downgrade — "
                "query performance will degrade after rollback and unique indexes won't be restored",
                "warning",
            )]
    return []


def _check_drop_constraint_in_upgrade(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Dropping a FK or CHECK constraint — downgrade must restore it."""
    up = _upgrade_body(source)
    if re.search(r"op\.drop_constraint\s*\(", up):
        down = _downgrade_body(source)
        if not re.search(r"op\.create_(?:foreign_key|check_constraint|unique_constraint)\s*\(", down):
            return [RiskWarning(
                rev, fname, "DROP CONSTRAINT without reverse",
                "Constraint dropped in upgrade but not restored in downgrade — "
                "data integrity guarantees are permanently removed after rollback",
                "warning",
            )]
    return []


def _check_deferred_not_null(source: str, rev: str, fname: str) -> list[RiskWarning]:
    """Two-step NOT NULL pattern where the constraint step has no reverse."""
    up = _upgrade_body(source)
    # Pattern: adding NOT NULL via batch_alter_table or execute
    if re.search(r"op\.execute\s*\(\s*['\"].*ALTER\s+(?:COLUMN|TABLE).*NOT\s+NULL", up, re.IGNORECASE):
        down = _downgrade_body(source)
        if not re.search(r"op\.execute\s*\(\s*['\"].*ALTER\s+(?:COLUMN|TABLE).*(?:DROP\s+NOT\s+NULL|NULL(?!\s*NOT))", down, re.IGNORECASE):
            return [RiskWarning(
                rev, fname, "NOT NULL via raw SQL without reverse",
                "NOT NULL constraint added via raw SQL but downgrade does not remove it — "
                "rollback leaves column as NOT NULL, breaking inserts with null values",
                "warning",
            )]
    return []


# ──────────────────────────────────────────────
# public API
# ──────────────────────────────────────────────

_CHECKS = [
    _check_batch_alter_drop,
    _check_downgrade_exists,
    _check_noop_downgrade,
    _check_drop_column_in_upgrade,
    _check_drop_table_in_upgrade,
    _check_truncate,
    _check_run_python_no_reverse,
    _check_not_null_no_default,
    _check_column_type_change,
    _check_column_size_shrink,
    _check_raw_execute,
    _check_data_migration_no_reverse,
    _check_cascade_delete,
    _check_index_without_concurrently,
    _check_add_column_with_default_on_large_table,
    _check_unique_constraint_on_existing,
    _check_drop_not_null,
    _check_rename_without_reverse,
    _check_drop_view,
    _check_sequence_reset,
    _check_multi_step_destructive,
    _check_enum_type_change,
    _check_drop_index_in_upgrade,
    _check_drop_constraint_in_upgrade,
    _check_deferred_not_null,
]


def _check_multiple_heads(versions_dir: str) -> list[RiskWarning]:
    """Detect branching migrations — multiple revisions sharing the same parent."""
    parent_to_children: dict[str, list[tuple[str, str]]] = {}

    for path in sorted(Path(versions_dir).glob("*.py")):
        source = path.read_text()
        rev_m = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        down_m = re.search(r'down_revision\s*=\s*["\']([^"\']+)["\']', source)
        if rev_m and down_m:
            rev = rev_m.group(1)
            parent = down_m.group(1)
            parent_to_children.setdefault(parent, []).append((rev, path.name))

    warnings = []
    for parent, children in parent_to_children.items():
        if len(children) > 1:
            revs = ", ".join(r for r, _ in children)
            warnings.append(RiskWarning(
                revs, children[0][1], "Multiple heads",
                f"Revisions {revs} all branch from '{parent}' — "
                "migration graph has multiple heads, which can cause ordering conflicts and "
                "failed deployments. Run `alembic merge heads` to resolve.",
                "error",
            ))
    return warnings


def analyze_migrations(versions_dir: str) -> list[RiskWarning]:
    warnings: list[RiskWarning] = []

    # Directory-level checks (run once across all files)
    warnings.extend(_check_multiple_heads(versions_dir))

    # Per-file checks
    for path in sorted(Path(versions_dir).glob("*.py")):
        source = path.read_text()
        m = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        revision = m.group(1) if m else path.stem
        for check in _CHECKS:
            warnings.extend(check(source, revision, path.name))

    return warnings
