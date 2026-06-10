"""
Rolling-deploy compatibility checks (MRT7xx).

These checks answer a different question from rollback-safety checks:
  "Can the OLD app version survive while the new migration is live?"

During a rolling deploy, the old app and new schema coexist briefly.
Operations that break that window are flagged here.
"""

from __future__ import annotations

import ast

from .ast_analyzer import MigrationAST
from .detector import RiskWarning, _is_suppressed, _warn


def _line_content(m: MigrationAST, lineno: int | None) -> str:
    if lineno is None:
        return ""
    lines = m.source.splitlines()
    return lines[lineno - 1] if 0 < lineno <= len(lines) else ""


def _check_compat_drop_column(m: MigrationAST) -> list[RiskWarning]:
    """MRT701 — DROP COLUMN in upgrade breaks the old app immediately."""
    warnings = []
    for call in m.upgrade_calls():
        if call.method in ("drop_column", "drop_columns"):
            col = m.str_arg(call.node, 1) or m.str_arg(call.node, 0) or "?"
            line = call.node.lineno if call.node else None
            if not _is_suppressed(_line_content(m, line), "MRT701"):
                warnings.append(
                    _warn(
                        m,
                        "DROP COLUMN during rolling deploy",
                        f"Dropping column '{col}' will break old app instances still reading it. "
                        "Two-step fix: (1) remove all code references and deploy, then "
                        "(2) drop the column in a follow-up migration.",
                        "error",
                        line=line,
                        code="MRT701",
                    )
                )
    return warnings


def _check_compat_rename_column(m: MigrationAST) -> list[RiskWarning]:
    """MRT702 — RENAME COLUMN breaks old app immediately."""
    warnings = []
    for call in m.upgrade_calls():
        if call.method == "alter_column" and m.has_kwarg(call.node, "new_column_name"):
            old_name = m.str_arg(call.node, 1) or "?"
            new_name = m.kwarg_str(call.node, "new_column_name") or "?"
            line = call.node.lineno if call.node else None
            if not _is_suppressed(_line_content(m, line), "MRT702"):
                warnings.append(
                    _warn(
                        m,
                        "RENAME COLUMN during rolling deploy",
                        f"Renaming '{old_name}' to '{new_name}' breaks old app instances "
                        "referencing the old name. Use expand-contract: add new column, "
                        "backfill, update code, then drop the old column.",
                        "error",
                        line=line,
                        code="MRT702",
                    )
                )
    return warnings


def _check_compat_drop_table(m: MigrationAST) -> list[RiskWarning]:
    """MRT703 — DROP TABLE in upgrade breaks old app immediately."""
    warnings = []
    for call in m.upgrade_calls():
        if call.method == "drop_table":
            table = m.str_arg(call.node, 0) or "?"
            line = call.node.lineno if call.node else None
            if not _is_suppressed(_line_content(m, line), "MRT703"):
                warnings.append(
                    _warn(
                        m,
                        "DROP TABLE during rolling deploy",
                        f"Dropping table '{table}' will crash old app instances still querying it. "
                        "Remove all ORM references and deploy first, then drop the table.",
                        "error",
                        line=line,
                        code="MRT703",
                    )
                )
    return warnings


def _check_compat_not_null_no_server_default(m: MigrationAST) -> list[RiskWarning]:
    """MRT704 — ADD NOT NULL column without server_default breaks old app INSERTs."""
    warnings = []
    for call in m.upgrade_calls():
        if call.method in ("add_column", "add_columns"):
            # Column spec is the second positional arg (sa.Column(...))
            col_call_raw = call.node.args[1] if len(call.node.args) > 1 else None
            if not isinstance(col_call_raw, ast.Call):
                continue
            col_call: ast.Call = col_call_raw
            nullable = m.kwarg_bool(col_call, "nullable")
            has_server_default = m.has_kwarg(col_call, "server_default")
            if nullable is False and not has_server_default:
                col = m.str_arg(col_call, 0) or "?"
                line = call.node.lineno if call.node else None
                if not _is_suppressed(_line_content(m, line), "MRT704"):
                    warnings.append(
                        _warn(
                            m,
                            "ADD NOT NULL column without server_default",
                            f"Adding NOT NULL column '{col}' without a server_default causes "
                            "INSERT failures from old app instances that don't supply the value. "
                            "Add server_default=... or make it nullable first.",
                            "error",
                            line=line,
                            code="MRT704",
                        )
                    )
    return warnings


def _check_compat_column_type_change(m: MigrationAST) -> list[RiskWarning]:
    """MRT705 — Column type change may break old app reads/writes."""
    warnings = []
    for call in m.upgrade_calls():
        if call.method == "alter_column":
            has_type = m.has_kwarg(call.node, "type_") or m.has_kwarg(call.node, "type")
            has_rename = m.has_kwarg(call.node, "new_column_name")
            if has_type and not has_rename:
                col = m.str_arg(call.node, 1) or "?"
                line = call.node.lineno if call.node else None
                if not _is_suppressed(_line_content(m, line), "MRT705"):
                    warnings.append(
                        _warn(
                            m,
                            "Column type change during rolling deploy",
                            f"Changing the type of '{col}' may cause type errors in old app "
                            "instances. VARCHAR widening is safe; narrowing or changing kind is not.",
                            "warning",
                            line=line,
                            code="MRT705",
                        )
                    )
    return warnings


_COMPAT_CHECKS = [
    _check_compat_drop_column,
    _check_compat_rename_column,
    _check_compat_drop_table,
    _check_compat_not_null_no_server_default,
    _check_compat_column_type_change,
]


def analyze_compat(m: MigrationAST) -> list[RiskWarning]:
    """Run all rolling-deploy compatibility checks on a single migration."""
    results: list[RiskWarning] = []
    for check in _COMPAT_CHECKS:
        results.extend(check(m))
    return results
