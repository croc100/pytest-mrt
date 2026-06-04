"""
AST-based migration analyzer.

Replaces regex-based detection with proper Python AST parsing.
Understands code structure: if/else, with blocks, nested calls, keyword args.
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class CallInfo:
    method: str          # e.g. "drop_column", "execute"
    node: ast.Call
    in_batch: bool = False   # inside op.batch_alter_table(...) as x


class MigrationAST:
    """
    Parsed Alembic migration file.
    Provides structured access to upgrade()/downgrade() operations.
    """

    def __init__(self, source: str, revision: str, filename: str):
        self.source = source
        self.revision = revision
        self.filename = filename
        try:
            self.tree: ast.Module = ast.parse(source)
            self._parse_error: Exception | None = None
        except SyntaxError as e:
            self.tree = ast.parse("")
            self._parse_error = e

        self.upgrade_fn: ast.FunctionDef | None = self._find_fn("upgrade")
        self.downgrade_fn: ast.FunctionDef | None = self._find_fn("downgrade")

    # ── module-level vars ────────────────────────────────────────────

    def module_var(self, name: str) -> str | None:
        """Return string value of a module-level assignment like: revision = '001'"""
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        if isinstance(node.value, ast.Constant):
                            return str(node.value.value)
                        if isinstance(node.value, ast.Tuple):
                            # down_revision = ('a', 'b')
                            items = []
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant):
                                    items.append(str(elt.value))
                            return ",".join(items) if items else None
        return None

    # ── function helpers ─────────────────────────────────────────────

    def _find_fn(self, name: str) -> ast.FunctionDef | None:
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    def is_noop(self, fn: ast.FunctionDef | None) -> bool:
        """True if function body contains only pass / docstrings / comments."""
        if fn is None:
            return True
        for node in fn.body:
            if isinstance(node, ast.Pass):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue  # docstring or bare string
            return False
        return True

    # ── call extraction ──────────────────────────────────────────────

    def _calls_in(self, fn: ast.FunctionDef | None) -> list[CallInfo]:
        if fn is None:
            return []
        return list(self._walk_calls(fn, in_batch=False))

    def _walk_calls(self, node: ast.AST, in_batch: bool) -> Iterator[CallInfo]:
        """Walk node yielding CallInfo for every method call found."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                method = self._call_method(child)
                if method:
                    # Check if this call is inside a batch_alter_table with-block
                    batch = in_batch or self._is_batch_context(child, node)
                    yield CallInfo(method=method, node=child, in_batch=batch)

    def _is_batch_context(self, call_node: ast.Call, fn_node: ast.AST) -> bool:
        """Check if call_node is inside a batch_alter_table with-block."""
        for node in ast.walk(fn_node):
            if isinstance(node, ast.With):
                for item in node.items:
                    ctx = item.context_expr
                    if (isinstance(ctx, ast.Call) and
                            isinstance(ctx.func, ast.Attribute) and
                            ctx.func.attr == "batch_alter_table"):
                        # Is call_node inside this with block?
                        for child in ast.walk(node):
                            if child is call_node:
                                return True
        return False

    def _call_method(self, call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    def upgrade_calls(self) -> list[CallInfo]:
        return self._calls_in(self.upgrade_fn)

    def downgrade_calls(self) -> list[CallInfo]:
        return self._calls_in(self.downgrade_fn)

    def upgrade_methods(self) -> set[str]:
        return {c.method for c in self.upgrade_calls()}

    def downgrade_methods(self) -> set[str]:
        return {c.method for c in self.downgrade_calls()}

    # ── argument helpers ─────────────────────────────────────────────

    @staticmethod
    def str_arg(call: ast.Call, index: int) -> str | None:
        if len(call.args) > index:
            arg = call.args[index]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
        return None

    @staticmethod
    def has_kwarg(call: ast.Call, name: str) -> bool:
        return any(kw.arg == name for kw in call.keywords)

    @staticmethod
    def kwarg_value(call: ast.Call, name: str) -> ast.expr | None:
        for kw in call.keywords:
            if kw.arg == name:
                return kw.value
        return None

    @staticmethod
    def kwarg_str(call: ast.Call, name: str) -> str | None:
        val = MigrationAST.kwarg_value(call, name)
        if val and isinstance(val, ast.Constant) and isinstance(val.value, str):
            return val.value
        return None

    @staticmethod
    def kwarg_bool(call: ast.Call, name: str) -> bool | None:
        val = MigrationAST.kwarg_value(call, name)
        if val and isinstance(val, ast.Constant) and isinstance(val.value, bool):
            return val.value
        return None

    @staticmethod
    def sql_content(call: ast.Call) -> str:
        """Extract SQL string from op.execute('...')"""
        if call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
        return ""

    # ── Column() inspection ──────────────────────────────────────────

    @staticmethod
    def find_column_calls(call: ast.Call) -> list[ast.Call]:
        """Find all sa.Column(...) or Column(...) inside a call's arguments."""
        cols = []
        for node in ast.walk(call):
            if node is call:
                continue
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr == "Column":
                    cols.append(node)
                elif isinstance(fn, ast.Name) and fn.id == "Column":
                    cols.append(node)
        return cols
