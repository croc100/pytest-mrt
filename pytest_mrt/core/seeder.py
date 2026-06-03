from __future__ import annotations
import re
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .schema import ColumnInfo, TableInfo


def _generate_value(col: ColumnInfo, index: int) -> Any:
    t = col.type_str.upper()
    if any(x in t for x in ("INT", "SERIAL", "BIGINT", "SMALLINT")):
        return index * 1000 + 1
    if any(x in t for x in ("FLOAT", "DOUBLE", "REAL", "NUMERIC", "DECIMAL")):
        return float(index * 1000 + 1)
    if "BOOL" in t:
        return True
    if "UUID" in t:
        return str(uuid.UUID(int=index + 10**12))
    if "JSON" in t:
        return '{"mrt": true}'
    if any(x in t for x in ("BYTEA", "BLOB", "BINARY")):
        return b"mrt_seed"
    if "TIMESTAMP" in t or "DATETIME" in t:
        return datetime(2024, 1, 1, index % 24, 0, 0)
    if "DATE" in t:
        return date(2024, 1, index % 28 + 1)
    if "TIME" in t:
        return time(index % 24, 0, 0)
    if any(x in t for x in ("VARCHAR", "TEXT", "CHAR", "STRING", "CLOB")):
        m = re.search(r"\((\d+)\)", t)
        limit = int(m.group(1)) if m else 255
        val = f"mrt_seed_{index:05d}"
        return val[:limit]
    return f"mrt_{index}"


def _topological_order(tables: dict[str, TableInfo]) -> list[str]:
    """Return table names ordered so FK parents come before children."""
    order: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for parent in tables.get(name, TableInfo(name)).fk_tables:
            if parent in tables:
                visit(parent)
        order.append(name)

    for name in tables:
        visit(name)
    return order


class SmartSeeder:
    def __init__(self, engine: Engine):
        self.engine = engine
        # table_name -> list of (pk_col, pk_val)
        self._seeded: dict[str, list[Any]] = {}

    def seed_all(self, tables: dict[str, TableInfo], count: int = 3) -> None:
        for tname in _topological_order(tables):
            self.seed_table(tables[tname], count)

    def seed_table(self, table: TableInfo, count: int = 3) -> None:
        if not table.pk_cols:
            return

        pk_col = table.pk_cols[0]
        inserted_pks: list[Any] = []

        for i in range(count):
            row: dict[str, Any] = {}
            for col_name, col_info in table.columns.items():
                if col_info.primary_key and any(
                    x in col_info.type_str.upper() for x in ("SERIAL", "AUTOINCREMENT")
                ):
                    continue
                if not col_info.nullable and col_info.default is None:
                    row[col_name] = _generate_value(col_info, i + len(self._seeded) * 100)
                elif not col_info.nullable:
                    row[col_name] = _generate_value(col_info, i + len(self._seeded) * 100)

            if not row:
                continue

            cols = ", ".join(f'"{c}"' for c in row)
            placeholders = ", ".join(f":{c}" for c in row)
            stmt = text(f'INSERT INTO "{table.name}" ({cols}) VALUES ({placeholders})')

            try:
                with self.engine.begin() as conn:
                    conn.execute(stmt, row)
                    if pk_col in row:
                        inserted_pks.append(row[pk_col])
                    else:
                        # Auto-generated PK — fetch last inserted
                        result = conn.execute(
                            text(f'SELECT "{pk_col}" FROM "{table.name}" ORDER BY "{pk_col}" DESC LIMIT 1')
                        )
                        val = result.scalar()
                        if val is not None:
                            inserted_pks.append(val)
            except Exception:
                # FK or constraint we can't satisfy — skip this table
                pass

        if inserted_pks:
            self._seeded.setdefault(table.name, []).extend(inserted_pks)

    def verify(self) -> list[str]:
        failures: list[str] = []
        with self.engine.connect() as conn:
            insp = inspect(conn)
            existing = set(insp.get_table_names())

        for tname, pk_vals in self._seeded.items():
            if tname not in existing:
                failures.append(f"Table '{tname}' no longer exists after rollback — all data lost")
                continue

            with self.engine.connect() as conn:
                insp = inspect(conn)
                pk_info = insp.get_pk_constraint(tname)
                pk_cols = pk_info.get("constrained_columns", [])
                if not pk_cols:
                    continue
                pk_col = pk_cols[0]

                placeholders = ", ".join(f":v{i}" for i in range(len(pk_vals)))
                params = {f"v{i}": v for i, v in enumerate(pk_vals)}
                result = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{tname}" WHERE "{pk_col}" IN ({placeholders})'),
                    params,
                )
                found = result.scalar() or 0

            if found < len(pk_vals):
                lost = len(pk_vals) - found
                failures.append(
                    f"Table '{tname}': {lost}/{len(pk_vals)} row(s) lost after rollback"
                )

        return failures

    def reset(self) -> None:
        self._seeded.clear()
