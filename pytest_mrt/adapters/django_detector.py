"""
Django migration static analyzer.

Django migrations use class-based operations (migrations.RemoveField, etc.)
instead of Alembic's op.* calls. This analyzer understands that format.
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.detector import RiskWarning


@dataclass
class DjangoMigrationAST:
    source: str
    app_label: str
    migration_name: str
    filename: str
    tree: ast.Module
    operations: list[ast.expr]
    dependencies: list[tuple[str, str]]
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

        name = path.stem
        ops = cls._extract_ops(tree)
        deps = cls._extract_deps(tree)
        return cls(
            source=source,
            app_label=app_label,
            migration_name=name,
            filename=path.name,
            tree=tree,
            operations=ops,
            dependencies=deps,
            _parse_error=parse_error,
        )

    @staticmethod
    def _extract_ops(tree: ast.Module) -> list[ast.expr]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Migration":
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id == "operations":
                                if isinstance(item.value, ast.List):
                                    return item.value.elts
        return []

    @staticmethod
    def _extract_deps(tree: ast.Module) -> list[tuple[str, str]]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Migration":
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id == "dependencies":
                                if isinstance(item.value, ast.List):
                                    deps = []
                                    for elt in item.value.elts:
                                        if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                                            a = elt.elts[0]
                                            b = elt.elts[1]
                                            if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
                                                deps.append((str(a.value), str(b.value)))
                                    return deps
        return []

    def op_names(self) -> list[str]:
        names = []
        for op in self.operations:
            if isinstance(op, ast.Call):
                func = op.func
                if isinstance(func, ast.Attribute):
                    names.append(func.attr)
                elif isinstance(func, ast.Name):
                    names.append(func.id)
        return names

    def get_op_kwarg_str(self, op: ast.Call, kwarg: str) -> str | None:
        for kw in op.keywords:
            if kw.arg == kwarg and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
        return None

    def get_op_kwarg_bool(self, op: ast.Call, kwarg: str) -> bool | None:
        for kw in op.keywords:
            if kw.arg == kwarg and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, bool):
                    return kw.value.value
        return None


def _warn(m: DjangoMigrationAST, pattern: str, message: str,
          severity: str, line: int | None = None) -> RiskWarning:
    rev = f"{m.app_label}.{m.migration_name}"
    return RiskWarning(rev, m.filename, pattern, message, severity, line)


def _check_remove_field(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        name = op.func.attr if isinstance(op.func, ast.Attribute) else ""
        if name == "RemoveField":
            model = m.get_op_kwarg_str(op, "model_name") or "?"
            field = m.get_op_kwarg_str(op, "name") or "?"
            warnings.append(_warn(
                m, "RemoveField",
                f"migrations.RemoveField('{model}', '{field}') — "
                "field data is permanently lost even if migration is reversed",
                "error", line=op.lineno,
            ))
    return warnings


def _check_delete_model(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        name = op.func.attr if isinstance(op.func, ast.Attribute) else ""
        if name == "DeleteModel":
            model = m.get_op_kwarg_str(op, "name") or "?"
            warnings.append(_warn(
                m, "DeleteModel",
                f"migrations.DeleteModel('{model}') — all rows permanently lost on rollback",
                "error", line=op.lineno,
            ))
    return warnings


def _check_run_sql_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        name = op.func.attr if isinstance(op.func, ast.Attribute) else ""
        if name == "RunSQL":
            has_reverse = any(kw.arg == "reverse_sql" for kw in op.keywords)
            if not has_reverse:
                warnings.append(_warn(
                    m, "RunSQL without reverse_sql",
                    "migrations.RunSQL() has no reverse_sql — "
                    "migration cannot be reversed automatically",
                    "error", line=op.lineno,
                ))
    return warnings


def _check_run_python_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        name = op.func.attr if isinstance(op.func, ast.Attribute) else ""
        if name == "RunPython":
            has_reverse = any(kw.arg == "reverse_code" for kw in op.keywords)
            # Check if second positional arg is provided (reverse_code can be positional)
            has_pos_reverse = len(op.args) >= 2
            if not has_reverse and not has_pos_reverse:
                warnings.append(_warn(
                    m, "RunPython without reverse_code",
                    "migrations.RunPython() has no reverse_code — "
                    "data transformation cannot be undone on rollback",
                    "error", line=op.lineno,
                ))
    return warnings


def _check_alter_field_type(m: DjangoMigrationAST) -> list[RiskWarning]:
    warnings = []
    for op in m.operations:
        if not isinstance(op, ast.Call):
            continue
        name = op.func.attr if isinstance(op.func, ast.Attribute) else ""
        if name == "AlterField":
            model = m.get_op_kwarg_str(op, "model_name") or "?"
            field = m.get_op_kwarg_str(op, "name") or "?"
            warnings.append(_warn(
                m, "AlterField type change",
                f"migrations.AlterField('{model}', '{field}') — "
                "verify the type change is safe and reversible for existing data",
                "warning", line=op.lineno,
            ))
    return warnings


def _check_rename_field_no_reverse(m: DjangoMigrationAST) -> list[RiskWarning]:
    """RenameField is reversible by design, but warn if mixed with data ops."""
    renames = [op for op in m.operations
               if isinstance(op, ast.Call) and
               (op.func.attr if isinstance(op.func, ast.Attribute) else "") == "RenameField"]
    if renames and len(m.operations) > len(renames):
        for op in renames:
            model = m.get_op_kwarg_str(op, "model_name") or "?"
            warnings = [_warn(
                m, "RenameField with other operations",
                f"RenameField on '{model}' mixed with other operations — "
                "verify the rollback order is correct",
                "warning", line=op.lineno,
            )]
        return warnings
    return []


_DJANGO_CHECKS = [
    _check_remove_field,
    _check_delete_model,
    _check_run_sql_no_reverse,
    _check_run_python_no_reverse,
    _check_alter_field_type,
    _check_rename_field_no_reverse,
]


def is_django_migration(path: Path) -> bool:
    """Detect if a file is a Django migration (not Alembic)."""
    try:
        source = path.read_text()
        return "class Migration" in source and "django.db" in source
    except Exception:
        return False


def analyze_django_migrations(migrations_dir: str) -> list[RiskWarning]:
    """
    Analyze Django migrations in a directory.
    Supports both single-app directories (app/migrations/)
    and multi-app project structures.
    """
    warnings: list[RiskWarning] = []
    root = Path(migrations_dir)

    # Find migration files
    migration_files = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        if is_django_migration(path):
            # Infer app label from directory structure
            app_label = path.parent.parent.name  # app/migrations/0001_...
            migration_files.append((path, app_label))

    migs: list[DjangoMigrationAST] = []
    for path, app_label in migration_files:
        m = DjangoMigrationAST.from_file(path, app_label)
        if m._parse_error:
            warnings.append(RiskWarning(
                f"{app_label}.{path.stem}", path.name, "Syntax error",
                f"Could not parse: {m._parse_error}", "error",
            ))
            continue
        migs.append(m)
        for check in _DJANGO_CHECKS:
            warnings.extend(check(m))

    return warnings
