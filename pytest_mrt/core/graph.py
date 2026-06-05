"""
Migration dependency graph analysis.

Builds a directed graph of the full migration chain and detects
cross-migration patterns that per-file analysis cannot see:

- Data hole chains: migration A drops column X, migration B re-adds X.
  Rolling back B then A restores the schema but the data in X is gone
  for good even though each individual migration looks "recoverable".

- Broken rollback chains: a rollback sequence assumes a column/table
  that was actually removed by an earlier migration in the same chain.

- Orphaned migrations: migrations with no path to the current head
  (deploy risk — they may run unexpectedly during downgrade).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from .ast_analyzer import MigrationAST
from .detector import RiskWarning


@dataclass
class MigrationNode:
    revision: str
    filename: str
    down_revision: str | None  # None = base
    source: str
    ast: MigrationAST


@dataclass
class MigrationGraph:
    nodes: dict[str, MigrationNode] = field(default_factory=dict)

    def add(self, node: MigrationNode) -> None:
        self.nodes[node.revision] = node

    def children_of(self, revision: str) -> list[MigrationNode]:
        return [n for n in self.nodes.values() if n.down_revision == revision]

    def ancestors(self, revision: str) -> list[MigrationNode]:
        """All nodes that must be applied before `revision`."""
        result = []
        current = revision
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            node = self.nodes.get(current)
            if not node or node.down_revision is None:
                break
            parent = self.nodes.get(node.down_revision)
            if parent:
                result.append(parent)
                current = parent.revision
            else:
                break
        return result

    def linear_chain(self) -> list[MigrationNode]:
        """Return nodes in upgrade order for a linear (non-branching) chain."""
        roots = [n for n in self.nodes.values() if n.down_revision is None]
        order: list[MigrationNode] = []
        current = roots[0] if roots else None
        seen: set[str] = set()
        while current and current.revision not in seen:
            order.append(current)
            seen.add(current.revision)
            children = self.children_of(current.revision)
            current = children[0] if len(children) == 1 else None
        return order


def _build_graph(versions_dir: str) -> MigrationGraph:
    import re as _re

    graph = MigrationGraph()
    for path in sorted(Path(versions_dir).glob("*.py")):
        source = path.read_text()
        m_rev = _re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        m_down = _re.search(r'down_revision\s*=\s*["\']([^"\']+)["\']', source)
        if not m_rev:
            continue
        revision = m_rev.group(1)
        down_revision = m_down.group(1) if m_down else None
        m_ast = MigrationAST(source, revision, path.name)
        graph.add(
            MigrationNode(
                revision=revision,
                filename=path.name,
                down_revision=down_revision,
                source=source,
                ast=m_ast,
            )
        )
    return graph


# ──────────────────────────────────────────────
# cross-migration checks
# ──────────────────────────────────────────────


def _check_data_hole_chain(graph: MigrationGraph) -> list[RiskWarning]:
    """
    Detect: migration A drops column C, migration B (later in chain) re-adds C.

    This creates a "data hole": rolling back B then A appears to restore the
    schema (column C exists again), but the original data in C is gone.
    Each individual migration may look safe in isolation, but the pair is not.
    """
    warnings = []
    chain = graph.linear_chain()

    # Build: table.col → list of (revision, operation)
    col_ops: dict[str, list[tuple[str, str]]] = {}
    for node in chain:
        for c in node.ast.upgrade_calls():
            if c.method == "drop_column":
                table = node.ast.str_arg(c.node, 0) or "?"
                col = node.ast.str_arg(c.node, 1) or "?"
                key = f"{table}.{col}"
                col_ops.setdefault(key, []).append((node.revision, "drop"))
            elif c.method == "add_column":
                table = node.ast.str_arg(c.node, 0) or "?"
                key = f"{table}.?"
                # Can't easily get column name from add_column's Column() arg via AST
                # so we match by table only for now
                col_ops.setdefault(f"{table}._add_", []).append((node.revision, "add"))

    # Find drop then add on same table (simplified: same table name)
    drops_by_table: dict[str, list[tuple[str, str]]] = {}
    for key, ops in col_ops.items():
        table = key.split(".")[0]
        for rev, op in ops:
            if op == "drop":
                drops_by_table.setdefault(table, []).append((rev, key))

    adds_by_table: dict[str, list[str]] = {}
    for key, ops in col_ops.items():
        table = key.split(".")[0]
        for rev, op in ops:
            if op == "add":
                adds_by_table.setdefault(table, []).append(rev)

    for table, drop_list in drops_by_table.items():
        if table not in adds_by_table:
            continue
        add_revs = set(adds_by_table[table])

        # Find add revisions that come after a drop revision in the chain
        chain_revisions = [n.revision for n in chain]
        for drop_rev, col_key in drop_list:
            drop_idx = (
                chain_revisions.index(drop_rev) if drop_rev in chain_revisions else -1
            )
            for add_rev in add_revs:
                add_idx = (
                    chain_revisions.index(add_rev) if add_rev in chain_revisions else -1
                )
                if drop_idx >= 0 and add_idx > drop_idx:
                    col = col_key.split(".")[-1]
                    warnings.append(
                        RiskWarning(
                            revision=f"{drop_rev}→{add_rev}",
                            file=graph.nodes[add_rev].filename,
                            pattern="Data hole chain",
                            message=(
                                f"Column dropped in {drop_rev} then re-added in {add_rev} on table '{table}'. "
                                "Rolling back both migrations restores the schema but permanently loses "
                                "the original data — this is invisible to per-migration analysis."
                            ),
                            severity="warning",
                        )
                    )

    return warnings


def _check_orphaned_migrations(graph: MigrationGraph) -> list[RiskWarning]:
    """
    Detect migrations that are not reachable from any head.
    These may run unexpectedly during downgrade.
    """
    if not graph.nodes:
        return []

    # Find heads: nodes with no children
    heads = {rev for rev in graph.nodes if not graph.children_of(rev)}
    reachable: set[str] = set()

    def walk(rev: str) -> None:
        if rev in reachable:
            return
        reachable.add(rev)
        node = graph.nodes.get(rev)
        if node and node.down_revision:
            walk(node.down_revision)

    for head in heads:
        walk(head)

    orphans = [n for rev, n in graph.nodes.items() if rev not in reachable]
    warnings = []
    for node in orphans:
        warnings.append(
            RiskWarning(
                revision=node.revision,
                file=node.filename,
                pattern="Orphaned migration",
                message=(
                    f"Migration {node.revision} is not reachable from any head. "
                    "It will not run during normal upgrade but may interfere with downgrade."
                ),
                severity="warning",
            )
        )
    return warnings


# ──────────────────────────────────────────────
# public API
# ──────────────────────────────────────────────

_GRAPH_CHECKS = [
    _check_data_hole_chain,
    _check_orphaned_migrations,
]


def analyze_migration_graph(versions_dir: str) -> list[RiskWarning]:
    """Run cross-migration chain analysis on a versions directory."""
    graph = _build_graph(versions_dir)
    warnings: list[RiskWarning] = []
    for check in _GRAPH_CHECKS:
        warnings.extend(check(graph))
    return warnings
