"""Tests for cross-migration graph analysis."""
from __future__ import annotations
import textwrap
from pathlib import Path
import pytest
from pytest_mrt.core.graph import (
    analyze_migration_graph,
    _build_graph,
    _check_data_hole_chain,
    _check_orphaned_migrations,
)


@pytest.fixture()
def versions(tmp_path):
    d = tmp_path / "versions"
    d.mkdir()
    return d


def _write(versions: Path, name: str, content: str):
    (versions / name).write_text(textwrap.dedent(content).lstrip())


# ── graph building ────────────────────────────────

def test_build_graph_empty(versions):
    graph = _build_graph(str(versions))
    assert graph.nodes == {}


def test_build_graph_single(versions):
    _write(versions, "001.py", """
        revision = '001'
        down_revision = None
        def upgrade(): pass
        def downgrade(): pass
    """)
    graph = _build_graph(str(versions))
    assert "001" in graph.nodes


def test_build_graph_chain(versions):
    _write(versions, "001.py", "revision = '001'\ndown_revision = None\ndef upgrade(): pass\ndef downgrade(): pass\n")
    _write(versions, "002.py", "revision = '002'\ndown_revision = '001'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    graph = _build_graph(str(versions))
    assert graph.nodes["002"].down_revision == "001"


def test_linear_chain_order(versions):
    _write(versions, "001.py", "revision = '001'\ndown_revision = None\ndef upgrade(): pass\ndef downgrade(): pass\n")
    _write(versions, "002.py", "revision = '002'\ndown_revision = '001'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    _write(versions, "003.py", "revision = '003'\ndown_revision = '002'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    graph = _build_graph(str(versions))
    chain = graph.linear_chain()
    assert [n.revision for n in chain] == ["001", "002", "003"]


# ── data hole chain ───────────────────────────────

def test_data_hole_chain_detected(versions):
    _write(versions, "001.py", textwrap.dedent("""
        revision = '001'
        down_revision = None
        from alembic import op
        def upgrade():
            op.drop_column('users', 'email')
        def downgrade():
            pass
    """))
    _write(versions, "002.py", textwrap.dedent("""
        revision = '002'
        down_revision = '001'
        import sqlalchemy as sa
        from alembic import op
        def upgrade():
            op.add_column('users', sa.Column('email', sa.String(128)))
        def downgrade():
            op.drop_column('users', 'email')
    """))
    warnings = analyze_migration_graph(str(versions))
    patterns = [w.pattern for w in warnings]
    assert "Data hole chain" in patterns


def test_no_data_hole_without_readd(versions):
    _write(versions, "001.py", textwrap.dedent("""
        revision = '001'
        down_revision = None
        from alembic import op
        def upgrade():
            op.drop_column('users', 'email')
        def downgrade():
            pass
    """))
    graph = _build_graph(str(versions))
    warnings = _check_data_hole_chain(graph)
    assert not warnings


# ── orphaned migrations ───────────────────────────

def test_no_orphans_in_linear_chain(versions):
    _write(versions, "001.py", "revision = '001'\ndown_revision = None\ndef upgrade(): pass\ndef downgrade(): pass\n")
    _write(versions, "002.py", "revision = '002'\ndown_revision = '001'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    graph = _build_graph(str(versions))
    warnings = _check_orphaned_migrations(graph)
    assert not warnings


def test_empty_graph_no_orphans(versions):
    graph = _build_graph(str(versions))
    warnings = _check_orphaned_migrations(graph)
    assert not warnings


# ── ancestors ────────────────────────────────────

def test_ancestors_of_leaf(versions):
    _write(versions, "001.py", "revision = '001'\ndown_revision = None\ndef upgrade(): pass\ndef downgrade(): pass\n")
    _write(versions, "002.py", "revision = '002'\ndown_revision = '001'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    _write(versions, "003.py", "revision = '003'\ndown_revision = '002'\ndef upgrade(): pass\ndef downgrade(): pass\n")
    graph = _build_graph(str(versions))
    ancestors = graph.ancestors("003")
    revs = [n.revision for n in ancestors]
    assert "002" in revs
    assert "001" in revs


def test_ancestors_of_root_is_empty(versions):
    _write(versions, "001.py", "revision = '001'\ndown_revision = None\ndef upgrade(): pass\ndef downgrade(): pass\n")
    graph = _build_graph(str(versions))
    assert graph.ancestors("001") == []
