"""
Django migration static analyzer.

Detects dangerous patterns in Django migrations using AST parsing.
Covers all major risk categories: data loss, irreversibility, locking, schema drift.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.detector import RiskWarning, _is_suppressed


@dataclass
class DjangoMigrationAST:
    source: str
    app_label: str
    migration_name: str
    filename: str
    tree: ast.Module
    operations: list[ast.expr]
    dependencies: list[tuple[str, str]]
    is_atomic: bool | None  # None = not set (defaults to True)
    _parse_error: Exception | None = None

    @classmethod
    def from_file(cls, path: Path, app_label: str) -> "DjangoMigrationAST":
        source = path.read_text()
        try:
            tree = ast.parse(source)
            parse_error = None
        except SyntaxError as e:
            tree = ast.parse("")
            parse_error = e

        return cls(
            source=source,
            app_label=app_label,
            migration_name=path.stem,
            filename=path.name,
            tree=tree,
            operations=cls._extract_ops(tree),
            dependencies=cls._extract_deps(tree),
            is_atomic=cls._extract_atomic(tree),
            _parse_error=parse_error,
        )

    @staticmethod
    def _find_migration_class(tree: ast.Module) -> ast.ClassDef | None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Migration":
                return node
        return None

    @classmethod
    def _extract_ops(cls, tree: ast.Module) -> list[ast.expr]:
        klass = cls._find_migration_class(tree)
        if not klass:
            return []
        for item in klass.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "operations":
                        if isinstance(item.value, ast.List):
                            return item.value.elts
        return []

    @classmethod
    def _extract_deps(cls, tree: ast.Module) -> list[tuple[str, str]]:
        klass = cls._find_migration_class(tree)
        if not klass:
            return []
        for item in klass.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "dependencies":
                        if isinstance(item.value, ast.List):
                            deps = []
                            for elt in item.value.elts:
                                if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                                    a, b = elt.elts
                                    if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
                                        deps.append((str(a.value), str(b.value)))
                            return deps
        return []

    @classmethod
    def _extract_atomic(cls, tree: ast.Module) -> bool | None:
        klass = cls._find_migration_class(tree)
        if not klass:
            return None
        for item in klass.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "atomic":
                        if isinstance(item.value, ast.Constant):
                            return bool(item.value.value)
        return None  # not set → Django default is True

    def op_name(self, op: ast.expr) -> str:
        if isinstance(op, ast.Call):
            func = op.func
            if isinstance(func, ast.Attribute):
                return func.attr
            if isinstance(func, ast.Name):
                return func.id
        return ""

    def kwarg_str(self, op: ast.Call, name: str) -> str | None:
        for kw in op.keywords:
            if kw.arg == name and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
        return None

    def kwarg_bool(self, op: ast.Call, name: str) -> bool | None:
        for kw in op.keywords:
            if kw.arg == name and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, bool):
                    return kw.value.value
        return None

    def kwarg_exists(self, op: ast.Call, name: str) -> bool:
        return any(kw.arg == name for kw in op.keywords)

    def field_kwarg(self, op: ast.Call, name: str) -> ast.expr | None:
        """Get kwarg named 'field' then look inside it for another kwarg."""
        for kw in op.keywords:
            if kw.arg == name:
                return kw.value
        return None

    def sql_text(self, op: ast.Call) -> str:
        """Extract SQL from RunSQL's first arg (handles text() wrapper too)."""
        if not op.args:
            return ""
        arg = op.args[0]
        # Direct string
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value.upper()
        # text("...") wrapper
        if isinstance(arg, ast.Call):
            if arg.args and isinstance(arg.args[0], ast.Constant):
                return str(arg.args[0].value).upper()
        return ""


def _warn(
    m: DjangoMigrationAST,
    pattern: str,
    message: str,
    severity: str,
    line: int | None = None,
    code: str = "",
) -> RiskWarning:
    rev = f"{m.app_label}.{m.migration_name}"
    return RiskWarning(rev, m.filename, pattern, message, severity, line, code)


# ─────────────────────────────────────────────────────────────
# Data loss checks
# ─────────────────────────────────────────────────────────────


def _check_remove_field(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        if m.op_name(op) == "RemoveField":
            model = m.kwarg_str(op, "model_name") or "?"
            field = m.kwarg_str(op, "name") or "?"
            warnings.append(
                _warn(
                    m,
                    "RemoveField",
                    f"migrations.RemoveField('{model}', '{field}') — "
                    "field data is permanently lost even if migration is reversed",
                    "error",
                    line=op.lineno,
                    code="MRT209",
                )
            )
    return warnings


def _check_delete_model(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        if m.op_name(op) == "DeleteModel":
            model = m.kwarg_str(op, "name") or "?"
            warnings.append(
                _warn(
                    m,
                    "DeleteModel",
                    f"migrations.DeleteModel('{model}') — all rows permanently lost on rollback",
                    "error",
                    line=op.lineno,
                    code="MRT210",
                )
            )
    return warnings


def _check_add_field_not_null(m: DjangoMigrationAST) -> list[RiskWarning]:
    """AddField(null=False) without a default → will fail on existing data."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "AddField":
            continue
        model = m.kwarg_str(op, "model_name") or "?"
        name = m.kwarg_str(op, "name") or "?"
        field_node = m.field_kwarg(op, "field")
        if field_node is None:
            continue

        # Inspect the field constructor
        if not isinstance(field_node, ast.Call):
            continue

        # Check null= kwarg on the field
        null_val: bool | None = None
        has_default = False
        for kw in field_node.keywords:
            if kw.arg == "null" and isinstance(kw.value, ast.Constant):
                null_val = bool(kw.value.value)
            if kw.arg in ("default", "server_default"):
                has_default = True

        # Default for most fields: null=False
        if null_val is False and not has_default:
            warnings.append(
                _warn(
                    m,
                    "AddField NOT NULL without default",
                    f"AddField('{model}', '{name}') is NOT NULL with no default — "
                    "will fail on non-empty tables. Use null=True or provide a default.",
                    "error",
                    line=op.lineno,
                    code="MRT411",
                )
            )
        elif null_val is None and not has_default:
            # null not specified → defaults to False for most field types
            # Be conservative: only warn for fields that are likely NOT NULL
            field_type = ""
            if isinstance(field_node.func, ast.Attribute):
                field_type = field_node.func.attr
            elif isinstance(field_node.func, ast.Name):
                field_type = field_node.func.id

            nullable_by_default = {
                "TextField",
                "CharField",
                "EmailField",
                "URLField",
                "SlugField",
                "FileField",
                "ImageField",
                "GenericIPAddressField",
            }
            if field_type and field_type not in nullable_by_default:
                warnings.append(
                    _warn(
                        m,
                        "AddField NOT NULL without default",
                        f"AddField('{model}', '{name}', {field_type}) may be NOT NULL without a default — "
                        "will fail on non-empty tables if null is not set to True",
                        "warning",
                        line=op.lineno,
                        code="MRT411",
                    )
                )
    return warnings


def _check_alter_field_not_null(m: DjangoMigrationAST) -> list[RiskWarning]:
    """AlterField making a field non-nullable without a default."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "AlterField":
            continue
        model = m.kwarg_str(op, "model_name") or "?"
        name = m.kwarg_str(op, "name") or "?"
        field_node = m.field_kwarg(op, "field")
        if not isinstance(field_node, ast.Call):
            continue

        null_val = None
        has_default = False
        for kw in field_node.keywords:
            if kw.arg == "null" and isinstance(kw.value, ast.Constant):
                null_val = bool(kw.value.value)
            if kw.arg in ("default", "server_default"):
                has_default = True

        if null_val is False and not has_default:
            warnings.append(
                _warn(
                    m,
                    "AlterField to NOT NULL without default",
                    f"AlterField('{model}', '{name}') sets null=False without a default — "
                    "will fail if any existing rows have NULL in this field",
                    "error",
                    line=op.lineno,
                    code="MRT412",
                )
            )
    return warnings


# ─────────────────────────────────────────────────────────────
# Irreversibility checks
# ─────────────────────────────────────────────────────────────


def _check_run_sql_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "RunSQL":
            continue
        has_reverse = m.kwarg_exists(op, "reverse_sql") or len(op.args) >= 2
        if not has_reverse:
            warnings.append(
                _warn(
                    m,
                    "RunSQL without reverse_sql",
                    "migrations.RunSQL() has no reverse_sql — "
                    "migration cannot be reversed automatically",
                    "error",
                    line=op.lineno,
                    code="MRT108",
                )
            )
    return warnings


def _check_run_sql_dangerous(m: DjangoMigrationAST) -> list[RiskWarning]:
    """RunSQL containing TRUNCATE or DROP TABLE."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "RunSQL":
            continue
        sql = m.sql_text(op)
        if re.search(r"\bTRUNCATE\b", sql):
            warnings.append(
                _warn(
                    m,
                    "RunSQL TRUNCATE",
                    "RunSQL contains TRUNCATE — destroys all data with no undo",
                    "error",
                    line=op.lineno,
                    code="MRT212",
                )
            )
        elif re.search(r"\bDROP\s+TABLE\b", sql):
            warnings.append(
                _warn(
                    m,
                    "RunSQL DROP TABLE",
                    "RunSQL contains DROP TABLE — all rows permanently lost",
                    "error",
                    line=op.lineno,
                    code="MRT211",
                )
            )
    return warnings


def _check_run_python_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "RunPython":
            continue
        has_reverse = m.kwarg_exists(op, "reverse_code") or len(op.args) >= 2
        if not has_reverse:
            warnings.append(
                _warn(
                    m,
                    "RunPython without reverse_code",
                    "migrations.RunPython() has no reverse_code — "
                    "data transformation cannot be undone on rollback",
                    "error",
                    line=op.lineno,
                    code="MRT107",
                )
            )
    return warnings


def _check_rename_model_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    """RenameModel is reversible by Django, but old_name must be correct."""
    warnings = []
    rename_ops = [
        op for op in m.operations if isinstance(op, ast.Call) and m.op_name(op) == "RenameModel"
    ]
    if not rename_ops:
        return []
    for op in rename_ops:
        old = m.kwarg_str(op, "old_name") or "?"
        new = m.kwarg_str(op, "new_name") or "?"
        # RenameModel is inherently reversible, but warn if mixed with data-loss ops
        dangerous = [
            o
            for o in m.operations
            if isinstance(o, ast.Call) and m.op_name(o) in ("RemoveField", "DeleteModel", "RunSQL")
        ]
        if dangerous:
            warnings.append(
                _warn(
                    m,
                    "RenameModel with data-loss operations",
                    f"RenameModel('{old}' → '{new}') combined with data-loss operations — "
                    "verify rollback order is safe",
                    "warning",
                    line=op.lineno,
                    code="MRT305",
                )
            )
    return warnings


# ─────────────────────────────────────────────────────────────
# PostgreSQL / performance checks
# ─────────────────────────────────────────────────────────────


def _check_add_index_no_concurrently(m: DjangoMigrationAST) -> list[RiskWarning]:
    """AddIndex without concurrently causes table lock on PostgreSQL."""
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call) or m.op_name(op) != "AddIndex":
            continue
        # Check if atomic=False is set on the migration (required for CONCURRENTLY)
        if m.is_atomic is None or m.is_atomic:
            model = m.kwarg_str(op, "model_name") or "?"
            warnings.append(
                _warn(
                    m,
                    "AddIndex without atomic=False",
                    f"AddIndex on '{model}' runs inside a transaction — "
                    "for large tables, set atomic = False on the Migration class "
                    "and use Meta.indexes or a CONCURRENTLY migration",
                    "warning",
                    line=op.lineno,
                    code="MRT413",
                )
            )
    return warnings


def _check_missing_atomic_false(m: DjangoMigrationAST) -> list[RiskWarning]:
    """Certain operations cannot run inside a transaction and require atomic=False."""
    needs_atomic_false = {"AddIndex", "RemoveIndex"}
    has_requiring_ops = any(
        isinstance(op, ast.Call) and m.op_name(op) in needs_atomic_false for op in m.operations
    )
    if has_requiring_ops and (m.is_atomic is None or m.is_atomic is True):
        return [
            _warn(
                m,
                "Missing atomic=False",
                "This migration contains operations that should run with atomic=False "
                "to allow CONCURRENTLY index operations without locking the table",
                "warning",
                code="MRT414",
            )
        ]
    return []


# ─────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────

def _check_squash_run_python_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    """Squashed migrations with RunPython lacking reverse_code are unrecoverable on rollback."""
    # Detect squashed migration: has a `replaces` class attribute
    klass = DjangoMigrationAST._find_migration_class(m.tree)
    if not klass:
        return []

    has_replaces = any(
        isinstance(item, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "replaces" for t in item.targets)
        for item in klass.body
    )
    if not has_replaces:
        return []

    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        func = op.func
        name = (
            func.attr if isinstance(func, ast.Attribute) else
            func.id if isinstance(func, ast.Name) else None
        )
        if name != "RunPython":
            continue
        kw_names = {kw.arg for kw in op.keywords}
        if "reverse_code" in kw_names:
            continue
        warnings.append(
            RiskWarning(
                f"{m.app_label}.{m.migration_name}",
                m.filename,
                "Squashed migration: RunPython without reverse_code",
                "Squashed migration contains RunPython with no reverse_code — rollback will silently do nothing",
                "error",
                line=op.lineno,
                code="MRT601",
            )
        )
    return warnings


def _check_squash_missing_replaces(m: DjangoMigrationAST) -> list[RiskWarning]:
    """Squashed migrations must declare replaces to avoid double-apply risk."""
    # A migration with a name containing 'squash' but no replaces attribute is suspicious.
    if "squash" not in m.migration_name.lower():
        return []

    klass = DjangoMigrationAST._find_migration_class(m.tree)
    if not klass:
        return []

    has_replaces = any(
        isinstance(item, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "replaces" for t in item.targets)
        for item in klass.body
    )
    if has_replaces:
        return []

    return [
        RiskWarning(
            f"{m.app_label}.{m.migration_name}",
            m.filename,
            "Squashed migration: missing replaces list",
            "Migration name contains 'squash' but has no replaces attribute — Django may apply it on top of the original migrations",
            "warning",
            code="MRT602",
        )
    ]


_DJANGO_CHECKS = [
    _check_remove_field,
    _check_delete_model,
    _check_add_field_not_null,
    _check_alter_field_not_null,
    _check_run_sql_no_reverse,
    _check_run_sql_dangerous,
    _check_run_python_no_reverse,
    _check_rename_model_no_reverse,
    _check_add_index_no_concurrently,
    _check_missing_atomic_false,
    _check_squash_run_python_no_reverse,
    _check_squash_missing_replaces,
]


# ─────────────────────────────────────────────────────────────
# public API
# ─────────────────────────────────────────────────────────────


def is_django_migration(path: Path) -> bool:
    try:
        source = path.read_text()
        return "class Migration" in source and "django.db" in source
    except Exception:
        return False


def _django_migrations_since(migrations_dir: str, since: str) -> set[str]:
    """Return ``app_label.migration_name`` keys for migrations added *after* ``since``.

    ``since`` must be in ``"app_label.migration_name"`` format, e.g.
    ``"myapp.0010_add_email"``.  The function parses ``dependencies`` lists to
    build a reverse-dependency graph and returns all transitive dependents of
    the given migration (excluding ``since`` itself).
    """
    import ast as _ast
    import re as _re

    root = Path(migrations_dir)

    # key → list[parent_keys]
    dep_map: dict[str, list[str]] = {}

    for path in sorted(root.rglob("*.py")):
        source = path.read_text()
        if "class Migration" not in source or "django.db" not in source:
            continue
        app_label = path.parent.parent.name
        key = f"{app_label}.{path.stem}"

        parents: list[str] = []
        # Extract dependencies list via regex on the raw source
        m = _re.search(r"dependencies\s*=\s*(\[.*?\])", source, _re.DOTALL)
        if m:
            try:
                raw_list = _ast.literal_eval(m.group(1))
                for dep_app, dep_name in raw_list:
                    parents.append(f"{dep_app}.{dep_name}")
            except Exception:
                pass
        dep_map[key] = parents

    # Build children map
    children: dict[str, list[str]] = {k: [] for k in dep_map}
    for key, parents in dep_map.items():
        for p in parents:
            if p in children:
                children[p].append(key)

    if since not in children:
        return set()

    result: set[str] = set()
    queue = list(children[since])
    while queue:
        node = queue.pop()
        if node in result:
            continue
        result.add(node)
        queue.extend(children.get(node, []))
    return result


def analyze_django_migrations(
    migrations_dir: str,
    since: str | None = None,
    min_revision: str | None = None,
) -> list[RiskWarning]:
    """Analyze Django migration files for rollback risk patterns.

    Args:
        migrations_dir: Path to the directory containing Django migration packages.
        since: If given (format ``"app_label.migration_name"``), only analyse
               migrations that transitively depend on this migration.  Use this
               in CI to limit analysis to the migrations added in a branch.
        min_revision: If given, skip migrations at or older than this point.
               The two sets are intersected when both are provided.
    """
    since_set: set[str] | None = None
    if since is not None:
        since_set = _django_migrations_since(migrations_dir, since)

    if min_revision is not None:
        min_set = _django_migrations_since(migrations_dir, min_revision)
        since_set = min_set if since_set is None else since_set & min_set

    warnings: list[RiskWarning] = []
    root = Path(migrations_dir)

    for path in sorted(root.rglob("*.py")):
        if not is_django_migration(path):
            continue
        app_label = path.parent.parent.name
        key = f"{app_label}.{path.stem}"

        if since_set is not None and key not in since_set:
            continue

        m = DjangoMigrationAST.from_file(path, app_label)
        if m._parse_error:
            warnings.append(
                RiskWarning(
                    f"{app_label}.{path.stem}",
                    path.name,
                    "Syntax error",
                    f"Could not parse: {m._parse_error}",
                    "error",
                    code="MRT902",
                )
            )
            continue
        source_lines = path.read_text().splitlines()
        for check in _DJANGO_CHECKS:
            for w in check(m):
                if (
                    w.line is not None
                    and w.line <= len(source_lines)
                    and _is_suppressed(source_lines[w.line - 1], w.code)
                ):
                    continue
                warnings.append(w)

    return warnings
