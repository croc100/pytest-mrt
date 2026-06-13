"""
Migration risk detector — AST-based.

All checks operate on MigrationAST objects, not raw source strings.
This eliminates false positives from regex-on-comments and gives us
line numbers, keyword argument inspection, and context awareness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .ast_analyzer import MigrationAST


@dataclass
class RiskWarning:
    revision: str
    file: str
    pattern: str
    message: str
    severity: str  # "error" | "warning"
    line: int | None = None
    code: str = ""  # e.g. "MRT201"


def _is_suppressed(line_content: str, code: str) -> bool:
    """Return True if the source line carries a suppression comment for *code*.

    Recognised forms (ruff/flake8 convention):
      # noqa             — suppress all MRT codes on this line
      # noqa: MRT201     — suppress one specific code
      # noqa: MRT201, MRT202  — suppress multiple codes
      # mrt: ignore      — legacy alias (kept for backwards compatibility)
    """
    if "# mrt: ignore" in line_content:
        return True
    m = re.search(r"#\s*noqa(?::\s*([A-Z0-9,\s]+))?", line_content)
    if m is None:
        return False
    raw = m.group(1)
    if raw is None:
        return True  # bare # noqa — suppress everything
    return code in {c.strip() for c in raw.split(",")}


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────


def _warn(
    m: MigrationAST,
    pattern: str,
    message: str,
    severity: str,
    line: int | None = None,
    code: str = "",
) -> RiskWarning:
    return RiskWarning(m.revision, m.filename, pattern, message, severity, line, code)


def _sql(call) -> str:
    return MigrationAST.sql_content(call).upper()


# ─────────────────────────────────────────────────────────────
# per-file checks
# ─────────────────────────────────────────────────────────────


def _check_downgrade_exists(m: MigrationAST) -> list[RiskWarning]:
    if m.downgrade_fn is None:
        return [
            _warn(
                m,
                "Missing downgrade",
                "No downgrade() function — migration is permanently irreversible",
                "error",
                code="MRT101",
            )
        ]
    return []


def _check_noop_downgrade(m: MigrationAST) -> list[RiskWarning]:
    if m.downgrade_fn and m.is_noop(m.downgrade_fn):
        return [
            _warn(
                m,
                "No-op downgrade",
                "downgrade() body is empty or pass — rollback silently does nothing",
                "error",
                line=m.downgrade_fn.lineno,
                code="MRT102",
            )
        ]
    return []


def _check_drop_column_in_upgrade(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.method == "drop_column":
            table = m.str_arg(c.node, 0) or "?"
            col = m.str_arg(c.node, 1) or "?"
            warnings.append(
                _warn(
                    m,
                    "DROP COLUMN in upgrade",
                    f"op.drop_column('{table}', '{col}') — "
                    "column data is permanently lost even if downgrade re-adds the column",
                    "error",
                    line=c.node.lineno,
                    code="MRT201",
                )
            )
    return warnings


def _check_drop_table_in_upgrade(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.method == "drop_table":
            table = m.str_arg(c.node, 0) or "?"
            warnings.append(
                _warn(
                    m,
                    "DROP TABLE in upgrade",
                    f"op.drop_table('{table}') — all rows permanently lost on rollback",
                    "error",
                    line=c.node.lineno,
                    code="MRT202",
                )
            )
    return warnings


def _check_truncate(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "execute" and re.search(r"\bTRUNCATE\b", _sql(c.node)):
            return [
                _warn(
                    m,
                    "TRUNCATE",
                    "TRUNCATE in upgrade destroys all data — cannot be rolled back",
                    "error",
                    line=c.node.lineno,
                    code="MRT203",
                )
            ]
    return []


def _check_not_null_no_default(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.method in ("add_column", "alter_column"):
            table = m.str_arg(c.node, 0) or "?"
            for col_call in m.find_column_calls(c.node):
                nullable = m.kwarg_bool(col_call, "nullable")
                has_default = m.has_kwarg(col_call, "server_default") or m.has_kwarg(
                    col_call, "default"
                )
                if nullable is False and not has_default:
                    warnings.append(
                        _warn(
                            m,
                            "NOT NULL without default",
                            f"Table '{table}': adding NOT NULL column without server_default "
                            "will fail on non-empty tables and leave column in invalid state on rollback",
                            "warning",
                            line=c.node.lineno,
                            code="MRT401",
                        )
                    )
    return warnings


def _check_raw_execute(m: MigrationAST) -> list[RiskWarning]:
    up_exec = [c for c in m.upgrade_calls() if c.method == "execute"]
    down_exec = [c for c in m.downgrade_calls() if c.method == "execute"]
    if up_exec and not down_exec:
        return [
            _warn(
                m,
                "Raw SQL (op.execute)",
                "op.execute() in upgrade without corresponding execute in downgrade — "
                "manually verify the downgrade correctly reverses this",
                "warning",
                line=up_exec[0].node.lineno,
                code="MRT104",
            )
        ]
    return []


def _check_data_migration_no_reverse(m: MigrationAST) -> list[RiskWarning]:
    def has_update_sql(calls) -> bool:
        return any(c.method == "execute" and re.search(r"\bUPDATE\b", _sql(c.node)) for c in calls)

    if has_update_sql(m.upgrade_calls()) and not has_update_sql(m.downgrade_calls()):
        return [
            _warn(
                m,
                "Data transform without reverse",
                "Bulk UPDATE in upgrade but downgrade has no corresponding UPDATE — "
                "data transformation is one-way",
                "warning",
                code="MRT103",
            )
        ]
    return []


def _check_rename_table_without_reverse(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    down_renames = {
        (m.str_arg(c.node, 0), m.str_arg(c.node, 1))
        for c in m.downgrade_calls()
        if c.method == "rename_table"
    }
    for c in m.upgrade_calls():
        if c.method == "rename_table":
            old = m.str_arg(c.node, 0)
            new = m.str_arg(c.node, 1)
            if (new, old) not in down_renames:
                warnings.append(
                    _warn(
                        m,
                        "rename_table without reverse",
                        f"Table renamed '{old}' → '{new}' but downgrade does not rename it back",
                        "error",
                        line=c.node.lineno,
                        code="MRT301",
                    )
                )
    return warnings


def _check_rename_column_without_reverse(m: MigrationAST) -> list[RiskWarning]:
    up_renames = [
        c
        for c in m.upgrade_calls()
        if c.method == "alter_column" and m.has_kwarg(c.node, "new_column_name")
    ]
    down_renames = [
        c
        for c in m.downgrade_calls()
        if c.method == "alter_column" and m.has_kwarg(c.node, "new_column_name")
    ]
    if up_renames and not down_renames:
        c = up_renames[0]
        table = m.str_arg(c.node, 0) or "?"
        old_col = m.str_arg(c.node, 1) or "?"
        new_col = m.kwarg_str(c.node, "new_column_name") or "?"
        return [
            _warn(
                m,
                "rename_column without reverse",
                f"Column '{table}.{old_col}' renamed to '{new_col}' "
                "but downgrade does not rename it back",
                "error",
                line=c.node.lineno,
                code="MRT302",
            )
        ]
    return []


def _check_drop_view(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "execute" and re.search(r"\bDROP\s+VIEW\b", _sql(c.node)):
            down_creates = any(
                c2.method == "execute" and re.search(r"\bCREATE\b.*\bVIEW\b", _sql(c2.node))
                for c2 in m.downgrade_calls()
            )
            if not down_creates:
                return [
                    _warn(
                        m,
                        "DROP VIEW without reverse",
                        "View dropped in upgrade but not recreated in downgrade — "
                        "queries against this view will fail after rollback",
                        "error",
                        line=c.node.lineno,
                        code="MRT207",
                    )
                ]
    return []


def _check_sequence_reset(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "execute":
            sql = _sql(c.node)
            if re.search(r"\b(CREATE|ALTER)\s+SEQUENCE\b|setval\s*\(", sql):
                return [
                    _warn(
                        m,
                        "SEQUENCE modification",
                        "Sequences are not transactional in PostgreSQL — "
                        "counter will not revert on rollback, causing ID gaps or duplicates",
                        "warning",
                        line=c.node.lineno,
                        code="MRT501",
                    )
                ]
    return []


def _check_enum_type_change(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "execute" and re.search(r"\bALTER\s+TYPE\b.*\bADD\s+VALUE\b", _sql(c.node)):
            return [
                _warn(
                    m,
                    "ENUM value added",
                    "ALTER TYPE ... ADD VALUE cannot be rolled back in PostgreSQL "
                    "if any row already uses the new value",
                    "error",
                    line=c.node.lineno,
                    code="MRT304",
                )
            ]
    return []


def _check_multi_step_destructive(m: MigrationAST) -> list[RiskWarning]:
    up = m.upgrade_calls()
    has_add = any(c.method == "add_column" for c in up)
    has_drop = any(c.method == "drop_column" for c in up)
    has_data = any(c.method == "execute" and re.search(r"\bUPDATE\b", _sql(c.node)) for c in up)
    if has_add and has_drop and has_data:
        return [
            _warn(
                m,
                "Multi-step destructive migration",
                "Migration adds a column, migrates data, then drops the original in one step — "
                "the combined operation is irreversible",
                "error",
                code="MRT208",
            )
        ]
    return []


def _check_cascade_delete(m: MigrationAST) -> list[RiskWarning]:
    import ast as ast_mod

    for c in m.upgrade_calls():
        for node in ast_mod.walk(c.node):
            if isinstance(node, ast_mod.Call):
                ondelete = MigrationAST.kwarg_str(node, "ondelete")
                if ondelete and ondelete.upper() == "CASCADE":
                    return [
                        _warn(
                            m,
                            "CASCADE DELETE",
                            "FK with ON DELETE CASCADE — child rows silently deleted with parent",
                            "warning",
                            line=c.node.lineno,
                            code="MRT204",
                        )
                    ]
    return []


def _check_index_without_concurrently(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.method == "create_index":
            concurrently = m.kwarg_bool(c.node, "postgresql_concurrently")
            if not concurrently:
                index = m.str_arg(c.node, 0) or "?"
                warnings.append(
                    _warn(
                        m,
                        "INDEX without CONCURRENTLY",
                        f"CREATE INDEX '{index}' without postgresql_concurrently=True — "
                        "locks table for the entire build duration",
                        "warning",
                        line=c.node.lineno,
                        code="MRT407",
                    )
                )
    return warnings


def _check_add_column_with_default(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "add_column":
            table = m.str_arg(c.node, 0) or "?"
            for col_call in m.find_column_calls(c.node):
                has_volatile_default = m.has_kwarg(col_call, "default")
                has_server_default = m.has_kwarg(col_call, "server_default")
                if has_volatile_default and not has_server_default:
                    # Python-side default (not server_default) always rewrites the table
                    return [
                        _warn(
                            m,
                            "ADD COLUMN with volatile DEFAULT",
                            f"Adding column to '{table}' with a Python-side default rewrites "
                            "the entire table on all PostgreSQL versions — use server_default "
                            "with a literal value instead for a zero-lock migration",
                            "warning",
                            line=c.node.lineno,
                            code="MRT404",
                        )
                    ]
                if has_server_default:
                    return [
                        _warn(
                            m,
                            "ADD COLUMN with server_default",
                            f"Adding column to '{table}' with server_default rewrites the table "
                            "on PostgreSQL < 11 — safe on PostgreSQL 11+ (instant metadata change). "
                            "Verify your PostgreSQL version before deploying.",
                            "warning",
                            line=c.node.lineno,
                            code="MRT405",
                        )
                    ]
    return []


def _check_unique_constraint_existing(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "create_unique_constraint":
            name = m.str_arg(c.node, 0) or "?"
            return [
                _warn(
                    m,
                    "UNIQUE constraint on existing data",
                    f"Adding UNIQUE constraint '{name}' — will fail if duplicates already exist",
                    "warning",
                    line=c.node.lineno,
                    code="MRT406",
                )
            ]
    return []


def _check_drop_index_without_reverse(m: MigrationAST) -> list[RiskWarning]:
    up_drops = [c for c in m.upgrade_calls() if c.method == "drop_index"]
    if not up_drops:
        return []
    down_creates = [c for c in m.downgrade_calls() if c.method == "create_index"]
    if not down_creates:
        idx = m.str_arg(up_drops[0].node, 0) or "?"
        return [
            _warn(
                m,
                "DROP INDEX without reverse",
                f"Index '{idx}' dropped but not recreated in downgrade — "
                "query performance and unique guarantees are not restored",
                "warning",
                line=up_drops[0].node.lineno,
                code="MRT408",
            )
        ]
    return []


def _check_drop_constraint_without_reverse(m: MigrationAST) -> list[RiskWarning]:
    up_drops = [c for c in m.upgrade_calls() if c.method == "drop_constraint"]
    if not up_drops:
        return []
    restore_methods = {
        "create_foreign_key",
        "create_unique_constraint",
        "create_check_constraint",
        "create_primary_key",
    }
    if not any(c.method in restore_methods for c in m.downgrade_calls()):
        name = m.str_arg(up_drops[0].node, 0) or "?"
        return [
            _warn(
                m,
                "DROP CONSTRAINT without reverse",
                f"Constraint '{name}' dropped but not recreated in downgrade — "
                "data integrity guarantees are permanently removed after rollback",
                "warning",
                line=up_drops[0].node.lineno,
                code="MRT409",
            )
        ]
    return []


def _check_not_null_nullable_restore(m: MigrationAST) -> list[RiskWarning]:
    """upgrade sets nullable=False; downgrade should restore nullable=True"""
    up_sets_nonnull = any(
        c.method == "alter_column" and m.kwarg_bool(c.node, "nullable") is False
        for c in m.upgrade_calls()
    )
    if not up_sets_nonnull:
        return []
    down_restores = any(
        c.method == "alter_column" and m.kwarg_bool(c.node, "nullable") is True
        for c in m.downgrade_calls()
    )
    if not down_restores:
        return [
            _warn(
                m,
                "NOT NULL without reverting nullable",
                "Column set NOT NULL in upgrade but downgrade does not restore nullable=True",
                "warning",
                code="MRT402",
            )
        ]
    return []


def _check_column_type_change(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "alter_column" and m.has_kwarg(c.node, "type_"):
            table = m.str_arg(c.node, 0) or "?"
            col = m.str_arg(c.node, 1) or "?"
            return [
                _warn(
                    m,
                    "Column type change",
                    f"Column '{table}.{col}' type changed — conversion may be lossy "
                    "and downgrade must restore the original type",
                    "warning",
                    line=c.node.lineno,
                    code="MRT303",
                )
            ]
    return []


def _check_batch_alter_drop(m: MigrationAST) -> list[RiskWarning]:
    warnings = []
    for c in m.upgrade_calls():
        if c.in_batch:
            if c.method == "drop_column":
                col = m.str_arg(c.node, 0) or "?"
                warnings.append(
                    _warn(
                        m,
                        "DROP COLUMN in batch_alter_table",
                        f"Column '{col}' dropped inside op.batch_alter_table — "
                        "data permanently lost even if downgrade re-adds the column",
                        "error",
                        line=c.node.lineno,
                        code="MRT206",
                    )
                )
            elif c.method == "drop_constraint":
                name = m.str_arg(c.node, 0) or "?"
                warnings.append(
                    _warn(
                        m,
                        "DROP CONSTRAINT in batch_alter_table",
                        f"Constraint '{name}' dropped inside op.batch_alter_table — "
                        "downgrade must recreate it",
                        "warning",
                        line=c.node.lineno,
                        code="MRT410",
                    )
                )
    return warnings


def _check_not_null_raw_sql(m: MigrationAST) -> list[RiskWarning]:
    for c in m.upgrade_calls():
        if c.method == "execute":
            sql = _sql(c.node)
            if re.search(r"\bSET\s+NOT\s+NULL\b", sql):
                down_drops = any(
                    c2.method == "execute"
                    and re.search(r"\bDROP\s+NOT\s+NULL\b|\bNULL\b", _sql(c2.node))
                    for c2 in m.downgrade_calls()
                )
                if not down_drops:
                    return [
                        _warn(
                            m,
                            "NOT NULL via raw SQL without reverse",
                            "NOT NULL added via raw SQL but downgrade does not remove it — "
                            "column stays NOT NULL after rollback",
                            "warning",
                            line=c.node.lineno,
                            code="MRT403",
                        )
                    ]
    return []


def _check_bulk_insert_no_reverse(m: MigrationAST) -> list[RiskWarning]:
    """op.bulk_insert() adds rows that should be removed in downgrade."""
    up_bulk = [c for c in m.upgrade_calls() if c.method == "bulk_insert"]
    if not up_bulk:
        return []
    down_delete = [
        c
        for c in m.downgrade_calls()
        if c.method == "delete"
        or (c.method == "execute" and re.search(r"\bDELETE\b", _sql(c.node)))
    ]
    if not down_delete:
        return [
            _warn(
                m,
                "bulk_insert without reverse",
                "op.bulk_insert() adds rows that are not removed in downgrade — "
                "rollback leaves the inserted data in the database",
                "warning",
                line=up_bulk[0].node.lineno,
                code="MRT106",
            )
        ]
    return []


def _check_context_execute(m: MigrationAST) -> list[RiskWarning]:
    """context.execute() is an alternative to op.execute() with same risks."""
    import ast as ast_mod

    if m.upgrade_fn is None:
        return []

    ctx_calls = []
    for node in ast_mod.walk(m.upgrade_fn):
        if isinstance(node, ast_mod.Call):
            func = node.func
            # context.execute(...) or ctx.execute(...)
            if (
                isinstance(func, ast_mod.Attribute)
                and func.attr == "execute"
                and isinstance(func.value, ast_mod.Name)
                and func.value.id in ("context", "ctx", "conn", "connection")
            ):
                ctx_calls.append(node)

    if not ctx_calls:
        return []

    # Check if downgrade has corresponding execute
    if m.downgrade_fn:
        down_has_execute = any(
            isinstance(node, ast_mod.Call)
            and isinstance(node.func, ast_mod.Attribute)
            and node.func.attr == "execute"
            for node in ast_mod.walk(m.downgrade_fn)
        )
        if down_has_execute:
            return []

    return [
        _warn(
            m,
            "context.execute without reverse",
            "context.execute() in upgrade without corresponding execute in downgrade — "
            "verify the downgrade correctly reverses this SQL",
            "warning",
            line=ctx_calls[0].lineno,
            code="MRT105",
        )
    ]


def _check_drop_foreign_key(m: MigrationAST) -> list[RiskWarning]:
    """
    op.drop_constraint(type_='foreignkey') in upgrade without op.create_foreign_key in downgrade.

    Dropping a FK constraint loses referential integrity. If the downgrade does not recreate the
    constraint, rolling back leaves the database without FK protection on that column pair.
    """
    warnings = []
    fk_drops = [
        c
        for c in m.upgrade_calls()
        if c.method == "drop_constraint"
        and (m.kwarg_str(c.node, "type_") or "").lower() == "foreignkey"
    ]
    if not fk_drops:
        return []

    down_creates_fk = any(c.method == "create_foreign_key" for c in m.downgrade_calls())
    if down_creates_fk:
        return []

    for c in fk_drops:
        table = m.str_arg(c.node, 1) or "?"
        warnings.append(
            _warn(
                m,
                "DROP FOREIGN KEY without restore",
                f"op.drop_constraint(type_='foreignkey') on '{table}' — "
                "referential integrity is lost unless op.create_foreign_key(...) is called in downgrade(). "
                "Fix: add op.create_foreign_key(...) to downgrade() to restore the constraint.",
                "error",
                line=c.node.lineno,
                code="MRT205",
            )
        )
    return warnings


def _check_create_trigger_without_drop(m: MigrationAST) -> list[RiskWarning]:
    """
    op.execute('CREATE TRIGGER ...') in upgrade without DROP TRIGGER in downgrade.

    Triggers created via raw SQL are invisible to schema diffing. If downgrade does not drop
    the trigger, rolling back leaves a dangling trigger that references potentially removed tables
    or columns, causing unexpected errors on future DML.
    """
    import re as _re

    # Extract string literals from upgrade execute calls
    upgrade_sql = " ".join(
        m.str_arg(c.node, 0) or "" for c in m.upgrade_calls() if c.method == "execute"
    )
    if not _re.search(r"CREATE\s+TRIGGER", upgrade_sql, _re.IGNORECASE):
        return []

    downgrade_sql = " ".join(
        m.str_arg(c.node, 0) or "" for c in m.downgrade_calls() if c.method == "execute"
    )
    if _re.search(r"DROP\s+TRIGGER", downgrade_sql, _re.IGNORECASE):
        return []

    return [
        _warn(
            m,
            "CREATE TRIGGER without DROP TRIGGER",
            "upgrade() creates a trigger via SQL but downgrade() does not DROP it. "
            "Fix: add op.execute('DROP TRIGGER IF EXISTS <name> ON <table>') to downgrade().",
            "error",
            code="MRT502",
        )
    ]


def _check_create_type_without_drop(m: MigrationAST) -> list[RiskWarning]:
    """
    op.execute('CREATE TYPE ...') in upgrade without DROP TYPE in downgrade.

    PostgreSQL custom types (including ENUMs created via op.execute) cannot be dropped
    while any column references them. If downgrade does not drop the type, re-running
    the upgrade later will fail with 'type already exists'.
    """
    import re as _re

    upgrade_sql = " ".join(
        m.str_arg(c.node, 0) or "" for c in m.upgrade_calls() if c.method == "execute"
    )
    if not _re.search(r"CREATE\s+TYPE", upgrade_sql, _re.IGNORECASE):
        return []

    downgrade_sql = " ".join(
        m.str_arg(c.node, 0) or "" for c in m.downgrade_calls() if c.method == "execute"
    )
    if _re.search(r"DROP\s+TYPE", downgrade_sql, _re.IGNORECASE):
        return []

    return [
        _warn(
            m,
            "CREATE TYPE without DROP TYPE",
            "upgrade() creates a custom type via SQL but downgrade() does not DROP it. "
            "Fix: add op.execute('DROP TYPE IF EXISTS <typename>') to downgrade(). "
            "Ensure all columns using the type are dropped first.",
            "error",
            code="MRT503",
        )
    ]


def _check_set_not_null_alter_column(m: MigrationAST) -> list[RiskWarning]:
    """
    alter_column(nullable=False) issues SET NOT NULL which does a full table
    scan on PostgreSQL to verify no NULLs exist. Holds AccessExclusiveLock
    for the scan duration.

    Safe path (PostgreSQL 12+): add a NOT NULL check constraint with NOT VALID,
    validate it, then ALTER COLUMN SET NOT NULL (PostgreSQL skips the scan when
    a validated constraint already covers it).
    """
    warnings = []
    for c in m.upgrade_calls():
        if c.method == "alter_column":
            nullable = m.kwarg_bool(c.node, "nullable")
            if nullable is False:
                table = m.str_arg(c.node, 0) or "?"
                col = m.str_arg(c.node, 1) or "?"
                warnings.append(
                    _warn(
                        m,
                        "SET NOT NULL on existing column",
                        f"alter_column('{table}', '{col}', nullable=False) runs SET NOT NULL — "
                        "full table scan with AccessExclusiveLock on PostgreSQL. "
                        "Safe path on PG 12+: add a NOT NULL check constraint (NOT VALID), "
                        "validate it, then SET NOT NULL.",
                        "warning",
                        line=c.node.lineno,
                        code="MRT213",
                    )
                )
    return warnings


_PER_FILE_CHECKS = [
    _check_batch_alter_drop,  # first: batch context needs special handling
    _check_downgrade_exists,
    _check_noop_downgrade,
    _check_drop_column_in_upgrade,
    _check_drop_table_in_upgrade,
    _check_truncate,
    _check_not_null_no_default,
    _check_column_type_change,
    _check_raw_execute,
    _check_data_migration_no_reverse,
    _check_cascade_delete,
    _check_index_without_concurrently,
    _check_add_column_with_default,
    _check_unique_constraint_existing,
    _check_drop_index_without_reverse,
    _check_drop_constraint_without_reverse,
    _check_rename_table_without_reverse,
    _check_rename_column_without_reverse,
    _check_drop_view,
    _check_sequence_reset,
    _check_enum_type_change,
    _check_multi_step_destructive,
    _check_not_null_nullable_restore,
    _check_not_null_raw_sql,
    _check_bulk_insert_no_reverse,
    _check_context_execute,
    _check_drop_foreign_key,
    _check_create_trigger_without_drop,
    _check_create_type_without_drop,
    _check_set_not_null_alter_column,
]


# ─────────────────────────────────────────────────────────────
# directory-level checks
# ─────────────────────────────────────────────────────────────


def _check_multiple_heads(migrations: list[MigrationAST]) -> list[RiskWarning]:
    parent_to_children: dict[str, list[str]] = {}
    for m in migrations:
        down = m.module_var("down_revision")
        if down and "," not in down:  # skip merge migrations
            parent_to_children.setdefault(down, []).append(m.revision)
    warnings = []
    for parent, children in parent_to_children.items():
        if len(children) > 1:
            revs = ", ".join(children)
            warnings.append(
                RiskWarning(
                    revs,
                    children[0],
                    "Multiple heads",
                    f"Revisions {revs} both branch from '{parent}' — "
                    "run `alembic merge heads` to resolve",
                    "error",
                    code="MRT901",
                )
            )
    return warnings


# ─────────────────────────────────────────────────────────────
# public API
# ─────────────────────────────────────────────────────────────


def _revisions_since(versions_dir: str, since: str) -> set[str]:
    """Return the set of Alembic revision IDs that come *after* ``since``.

    "After" means the revision has ``since`` somewhere in its down_revision
    ancestry chain — i.e. it was created on top of ``since``.  The ``since``
    revision itself is excluded so that ``--since <rev>`` means "only the
    migrations added after this point".

    If ``since`` is not found in the chain the function returns an empty set
    and the caller should warn the user rather than silently analysing nothing.
    """
    import re as _re

    # Build two mappings from raw source:
    #   rev_id  → down_revision (str | tuple[str] | None)
    #   rev_id  → path
    rev_to_down: dict[str, list[str]] = {}
    rev_to_path: dict[str, Path] = {}

    for path in sorted(Path(versions_dir).glob("*.py")):
        source = path.read_text()
        m_rev = _re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        if not m_rev:
            continue
        rev_id = m_rev.group(1)
        rev_to_path[rev_id] = path

        # down_revision may be a string, a tuple, or None
        m_down = _re.search(r"down_revision\s*=\s*(.+)", source)
        parents: list[str] = []
        if m_down:
            raw = m_down.group(1).strip().rstrip(",")
            # collect all quoted revision ids in that expression
            parents = _re.findall(r'["\']([0-9a-f]+)["\']', raw)
        rev_to_down[rev_id] = parents

    # Build children map: parent → [children]
    children: dict[str, list[str]] = {r: [] for r in rev_to_down}
    for rev_id, parents in rev_to_down.items():
        for p in parents:
            if p in children:
                children[p].append(rev_id)

    if since not in children:
        return set()

    # BFS from since → collect all descendants
    result: set[str] = set()
    queue = list(children[since])
    while queue:
        node = queue.pop()
        if node in result:
            continue
        result.add(node)
        queue.extend(children.get(node, []))
    return result


def analyze_migrations(
    versions_dir: str,
    since: str | None = None,
    min_revision: str | None = None,
) -> list[RiskWarning]:
    """
    Analyze all Alembic migration files in a directory.

    Runs two passes:
    1. Per-file checks — patterns detectable within a single migration file.
    2. Graph checks — cross-migration chain analysis (data holes, orphans, etc.).

    Args:
        versions_dir: Path to the Alembic versions directory.
        since: If given, only analyse migrations that come *after* this
               revision ID in the migration chain.  Useful in CI to limit
               analysis to the migrations introduced in a feature branch.
        min_revision: If given, skip revisions at or older than this point.
               The two sets are intersected when both are provided.
    """
    from .graph import analyze_migration_graph

    since_set: set[str] | None = None
    if since is not None:
        since_set = _revisions_since(versions_dir, since)

    if min_revision is not None:
        min_set = _revisions_since(versions_dir, min_revision)
        since_set = min_set if since_set is None else since_set & min_set

    warnings: list[RiskWarning] = []
    migrations: list[MigrationAST] = []

    for path in sorted(Path(versions_dir).glob("*.py")):
        source = path.read_text()
        import re as _re

        m_rev = _re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        revision = m_rev.group(1) if m_rev else path.stem

        if since_set is not None and revision not in since_set:
            continue

        m = MigrationAST(source, revision, path.name)
        if m._parse_error:
            warnings.append(
                RiskWarning(
                    revision,
                    path.name,
                    "Syntax error",
                    f"Could not parse migration file: {m._parse_error}",
                    "error",
                    code="MRT902",
                )
            )
            continue
        migrations.append(m)
        source_lines = source.splitlines()
        for check in _PER_FILE_CHECKS:
            for w in check(m):
                if (
                    w.line is not None
                    and w.line <= len(source_lines)
                    and _is_suppressed(source_lines[w.line - 1], w.code)
                ):
                    continue
                warnings.append(w)

    warnings.extend(_check_multiple_heads(migrations))
    if since is None:
        # Graph checks require the full chain; skip when --since is active
        # because orphan/data-hole checks would fire on incomplete history.
        warnings.extend(analyze_migration_graph(versions_dir))
    return warnings
