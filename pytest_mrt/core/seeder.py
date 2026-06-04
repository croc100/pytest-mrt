from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .schema import ColumnInfo, TableInfo


# ──────────────────────────────────────────────
# value generation
# ──────────────────────────────────────────────

def _unique_seed(col_name: str, row_index: int) -> int:
    """Stable, collision-resistant seed per (column, row)."""
    return abs(hash(f"mrt_{col_name}_{row_index}")) % 10 ** 8 + 10 ** 8


def _generate_value(col: ColumnInfo, row_index: int) -> Any:
    t = col.type_str.upper()
    seed = _unique_seed(col.name, row_index)

    if any(x in t for x in ("BIGINT", "BIGSERIAL")):
        return seed
    if any(x in t for x in ("INT", "SERIAL", "SMALLINT")):
        return seed % (2 ** 30)  # stay within 32-bit range
    if any(x in t for x in ("FLOAT", "DOUBLE", "REAL", "NUMERIC", "DECIMAL")):
        return float(seed) / 1000.0
    if "BOOL" in t:
        return row_index % 2 == 0
    if "UUID" in t:
        return str(uuid.UUID(int=seed))
    if "JSONB" in t or "JSON" in t:
        return f'{{"mrt": {row_index}}}'
    if any(x in t for x in ("BYTEA", "BLOB", "BINARY")):
        return f"mrt_{row_index}".encode()
    if "TIMESTAMP" in t or "DATETIME" in t:
        return datetime(2024, 1, row_index % 28 + 1, row_index % 24, 0, 0)
    if "DATE" in t:
        return date(2024, 1, row_index % 28 + 1)
    if "TIME" in t:
        return time(row_index % 24, 0, 0)
    if any(x in t for x in ("VARCHAR", "TEXT", "CHAR", "STRING", "CLOB")):
        m = re.search(r"\((\d+)\)", t)
        limit = int(m.group(1)) if m else 255
        # Include column name for cross-column uniqueness
        val = f"mrt_{col.name[:8]}_{row_index:04d}"
        return val[:limit]

    return f"mrt_{row_index}"


# ──────────────────────────────────────────────
# FK ordering
# ──────────────────────────────────────────────

def _topological_order(tables: dict[str, TableInfo]) -> list[str]:
    order: list[str] = []
    visited: set[str] = set()

    def visit(name: str, stack: set[str] = set()) -> None:
        if name in visited:
            return
        if name in stack:
            # Circular FK — skip parent and just insert in whatever order
            return
        stack = stack | {name}
        visited.add(name)
        for parent in tables.get(name, TableInfo(name)).fk_tables:
            if parent in tables and parent != name:
                visit(parent, stack)
        order.append(name)

    for name in tables:
        visit(name)
    return order


# ──────────────────────────────────────────────
# seeded row record
# ──────────────────────────────────────────────

@dataclass
class SeededRow:
    table: str
    pk_col: str
    pk_val: Any
    data: dict[str, Any]  # full column snapshot at seed time


# ──────────────────────────────────────────────
# seeder
# ──────────────────────────────────────────────

class SmartSeeder:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._rows: list[SeededRow] = []

    def seed_all(self, tables: dict[str, TableInfo], count: int = 3) -> None:
        for tname in _topological_order(tables):
            self.seed_table(tables[tname], count)

    def seed_table(self, table: TableInfo, count: int = 3) -> None:
        if not table.pk_cols:
            return

        pk_col = table.pk_cols[0]

        for row_index in range(count):
            row: dict[str, Any] = {}
            for col_name, col_info in table.columns.items():
                is_auto = col_info.primary_key and any(
                    x in col_info.type_str.upper()
                    for x in ("SERIAL", "AUTOINCREMENT", "AUTO_INCREMENT")
                )
                if is_auto:
                    continue
                if not col_info.nullable:
                    row[col_name] = _generate_value(col_info, row_index)
                # nullable columns left as NULL intentionally

            if not row:
                continue

            cols = ", ".join(f'"{c}"' for c in row)
            placeholders = ", ".join(f":p_{c}" for c in row)
            params = {f"p_{c}": v for c, v in row.items()}
            stmt = text(f'INSERT INTO "{table.name}" ({cols}) VALUES ({placeholders})')

            try:
                with self.engine.begin() as conn:
                    conn.execute(stmt, params)

                # Fetch actual inserted row (to capture auto-generated PK)
                with self.engine.connect() as conn:
                    if pk_col in row:
                        pk_val = row[pk_col]
                    else:
                        result = conn.execute(
                            text(f'SELECT "{pk_col}" FROM "{table.name}" ORDER BY "{pk_col}" DESC LIMIT 1')
                        )
                        pk_val = result.scalar()

                    if pk_val is not None:
                        # Fetch full row for later comparison
                        result = conn.execute(
                            text(f'SELECT * FROM "{table.name}" WHERE "{pk_col}" = :pk'),
                            {"pk": pk_val},
                        )
                        full_row = dict(result.mappings().first() or {})
                        self._rows.append(SeededRow(table.name, pk_col, pk_val, full_row))

            except Exception:
                # FK or constraint violation we can't satisfy — skip this table
                pass

    def verify(self) -> list[str]:
        """
        Check that every seeded row:
        1. Still exists in its table
        2. Has the same column values for columns that survived the rollback
        """
        failures: list[str] = []

        with self.engine.connect() as conn:
            insp = inspect(conn)
            existing_tables = set(insp.get_table_names())

        for seeded in self._rows:
            tname = seeded.table

            if tname not in existing_tables:
                failures.append(
                    f"Table '{tname}' no longer exists after rollback — all data lost"
                )
                continue

            with self.engine.connect() as conn:
                result = conn.execute(
                    text(f'SELECT * FROM "{tname}" WHERE "{seeded.pk_col}" = :pk'),
                    {"pk": seeded.pk_val},
                )
                row = result.mappings().first()

            if row is None:
                failures.append(
                    f"Table '{tname}': row {seeded.pk_col}={seeded.pk_val!r} lost after rollback"
                )
                continue

            # Value comparison — only for columns that still exist
            current = dict(row)
            for col, expected in seeded.data.items():
                if col not in current:
                    continue  # column was dropped by this migration — expected
                actual = current[col]
                if actual != expected:
                    failures.append(
                        f"Table '{tname}': column '{col}' value changed after rollback "
                        f"(expected {expected!r}, got {actual!r})"
                    )

        return failures

    def reset(self) -> None:
        self._rows.clear()
