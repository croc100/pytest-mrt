"""Shared SQL helpers for hand-built statements.

Every statement this package builds as a string must pass its table and column
names through :func:`quote_identifier`. Unquoted identifiers break on reserved
words (a table named ``order``), on mixed-case names under PostgreSQL, and on
MySQL, which wants backticks rather than double quotes.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine


def quote_identifier(engine: Engine, name: str) -> str:
    """Quote a table or column name for ``engine``'s dialect."""
    return engine.dialect.identifier_preparer.quote(name)
