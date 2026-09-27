"""
Rolling-deploy compatibility checks for Django migrations (MRT7xx).

Mirrors ``core/compat.py`` (Alembic) but operates on Django migration
operations. These answer a different question from rollback-safety checks:
  "Can the OLD app version survive while the new migration is live?"

During a rolling deploy the old app and new schema coexist briefly. Operations
that break that window are flagged here.

Coverage note: MRT705 (column type change) is Alembic-only. Django's
``AlterField`` always carries the full field definition with no reference to the
previous type, so a type change cannot be detected statically without comparing
against model state — out of scope for a file scanner.
"""

from __future__ import annotations

import ast

from ..core.detector import RiskWarning, _warn
from .django_detector import DjangoMigrationAST


def _check_compat_remove_field(m: DjangoMigrationAST) -> list[RiskWarning]:
    """MRT701 — RemoveField (DROP COLUMN) breaks old app instances immediately."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "RemoveField":
            continue
        model = m.kwarg_str(op, "model_name") or "?"
        field = m.kwarg_str(op, "name") or "?"
        warnings.append(
            _warn(
                m,
                "RemoveField during rolling deploy",
                f"Removing '{model}.{field}' will break old app instances still reading it. "
                "Two-step fix: (1) remove all code references and deploy, then "
                "(2) drop the field in a follow-up migration.",
                "error",
                line=op.lineno,
                code="MRT701",
            )
        )
    return warnings


def _check_compat_rename_field(m: DjangoMigrationAST) -> list[RiskWarning]:
    """MRT702 — RenameField (RENAME COLUMN) breaks old app instances immediately."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "RenameField":
            continue
        model = m.kwarg_str(op, "model_name") or "?"
        old_name = m.kwarg_str(op, "old_name") or "?"
        new_name = m.kwarg_str(op, "new_name") or "?"
        warnings.append(
            _warn(
                m,
                "RenameField during rolling deploy",
                f"Renaming '{model}.{old_name}' to '{new_name}' breaks old app instances "
                "referencing the old name. Use expand-contract: add new field, backfill, "
                "update code, then drop the old field.",
                "error",
                line=op.lineno,
                code="MRT702",
            )
        )
    return warnings


def _check_compat_drop_table(m: DjangoMigrationAST) -> list[RiskWarning]:
    """MRT703 — DeleteModel/RenameModel/AlterModelTable breaks old app immediately."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        name = m.op_name(op)
        if name == "DeleteModel":
            model = m.kwarg_str(op, "name") or "?"
            warnings.append(
                _warn(
                    m,
                    "DeleteModel during rolling deploy",
                    f"Deleting model '{model}' drops its table and crashes old app instances "
                    "still querying it. Remove all ORM references and deploy first, then "
                    "delete the model.",
                    "error",
                    line=op.lineno,
                    code="MRT703",
                )
            )
        elif name == "RenameModel":
            old_name = m.kwarg_str(op, "old_name") or "?"
            new_name = m.kwarg_str(op, "new_name") or "?"
            warnings.append(
                _warn(
                    m,
                    "RenameModel during rolling deploy",
                    f"Renaming model '{old_name}' to '{new_name}' renames its table and breaks "
                    "old app instances querying the old table. Use expand-contract with an "
                    "intermediate compatibility layer.",
                    "error",
                    line=op.lineno,
                    code="MRT703",
                )
            )
        elif name == "AlterModelTable":
            model = m.kwarg_str(op, "name") or "?"
            warnings.append(
                _warn(
                    m,
                    "AlterModelTable during rolling deploy",
                    f"Changing the db_table of '{model}' breaks old app instances querying the "
                    "old table name. Use expand-contract with an intermediate view or copy.",
                    "error",
                    line=op.lineno,
                    code="MRT703",
                )
            )
    return warnings


def _check_compat_add_field_not_null(m: DjangoMigrationAST) -> list[RiskWarning]:
    """MRT704 — AddField NOT NULL without a default breaks old app INSERTs."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "AddField":
            continue
        model = m.kwarg_str(op, "model_name") or "?"
        name = m.kwarg_str(op, "name") or "?"
        field_node = m.field_kwarg(op, "field")
        if not isinstance(field_node, ast.Call):
            continue

        null_val: bool | None = None
        has_default = False
        for kw in field_node.keywords:
            if kw.arg == "null" and isinstance(kw.value, ast.Constant):
                null_val = bool(kw.value.value)
            if kw.arg in ("default", "server_default"):
                has_default = True

        # Django defaults to null=False. Flag when explicitly or implicitly NOT NULL
        # and no default is supplied.
        if null_val is not True and not has_default:
            warnings.append(
                _warn(
                    m,
                    "AddField NOT NULL without default during rolling deploy",
                    f"Adding NOT NULL field '{model}.{name}' without a default causes INSERT "
                    "failures from old app instances that don't supply the value. "
                    "Add a default or make it nullable first.",
                    "error",
                    line=op.lineno,
                    code="MRT704",
                )
            )
    return warnings


_DJANGO_COMPAT_CHECKS = [
    _check_compat_remove_field,
    _check_compat_rename_field,
    _check_compat_drop_table,
    _check_compat_add_field_not_null,
]


def analyze_django_compat(m: DjangoMigrationAST) -> list[RiskWarning]:
    """Run all rolling-deploy compatibility checks on a single Django migration."""
    results: list[RiskWarning] = []
    for check in _DJANGO_COMPAT_CHECKS:
        results.extend(check(m))
    return results
