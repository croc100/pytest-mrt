from __future__ import annotations

import random
import re
import uuid
import warnings
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .schema import ColumnInfo, TableInfo


def _q(engine: Engine, name: str) -> str:
    """Quote an identifier using the engine's dialect (handles MySQL backticks)."""
    return engine.dialect.identifier_preparer.quote(name)


# ──────────────────────────────────────────────
# DB introspection helpers
# ──────────────────────────────────────────────


def _get_enum_values(engine: Engine, table_name: str, col_name: str) -> list[str] | None:
    """
    Query the DB for valid ENUM values for a column.
    Returns None if the column is not an ENUM or values can't be determined.
    """
    dialect = engine.dialect.name
    try:
        with engine.connect() as conn:
            if dialect == "postgresql":
                result = conn.execute(
                    text("""
                    SELECT e.enumlabel
                    FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    JOIN pg_attribute a ON a.atttypid = t.oid
                    JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = :tname AND a.attname = :cname
                    ORDER BY e.enumsortorder
                """),
                    {"tname": table_name, "cname": col_name},
                )
                vals = [row[0] for row in result]
                return vals if vals else None

            elif dialect == "mysql":
                result = conn.execute(
                    text(
                        "SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_NAME = :tname AND COLUMN_NAME = :cname "
                        "AND TABLE_SCHEMA = DATABASE()"
                    ),
                    {"tname": table_name, "cname": col_name},
                )
                row = result.fetchone()
                if row and row[0].lower().startswith("enum("):
                    # enum('a','b','c') → ['a', 'b', 'c']
                    inner = row[0][5:-1]
                    return [v.strip("'") for v in inner.split(",")]
    except Exception:
        pass
    return None


def _get_unique_constraints(engine: Engine, table_name: str) -> list[list[str]]:
    """Return list of column groups that form unique constraints."""
    try:
        with engine.connect() as conn:
            insp = inspect(conn)
            constraints = insp.get_unique_constraints(table_name)
            pk = insp.get_pk_constraint(table_name)
            groups = [c["column_names"] for c in constraints]
            if pk.get("constrained_columns"):
                groups.append(pk["constrained_columns"])
            return groups
    except Exception:
        return []


# ──────────────────────────────────────────────
# value generation
# ──────────────────────────────────────────────


def _unique_seed(col_name: str, row_index: int) -> int:
    """Stable, collision-resistant seed per (column, row)."""
    return abs(hash(f"mrt_{col_name}_{row_index}")) % 10**8 + 10**8


def _generate_value(
    col: ColumnInfo,
    row_index: int,
    enum_values: list[str] | None = None,
) -> Any:
    t = col.type_str.upper()
    seed = _unique_seed(col.name, row_index)

    # ENUM — use actual DB values when available
    if enum_values:
        return enum_values[row_index % len(enum_values)]
    if "ENUM" in t:
        # Fallback: can't determine values without DB introspection
        return None

    if any(x in t for x in ("BIGINT", "BIGSERIAL")):
        return seed
    if any(x in t for x in ("TINYINT", "SMALLINT", "MEDIUMINT", "INT", "SERIAL")):
        return seed % (2**30)
    if any(x in t for x in ("FLOAT", "DOUBLE", "REAL", "NUMERIC", "DECIMAL")):
        return float(seed) / 1000.0
    if "BOOL" in t:
        return row_index % 2 == 0
    if "UUID" in t:
        return str(uuid.UUID(int=seed))
    if "JSONB" in t or "JSON" in t:
        return f'{{"mrt": {row_index}}}'
    if any(x in t for x in ("BYTEA", "VARBINARY", "BLOB", "BINARY")):
        return f"mrt_{row_index}".encode()
    if "TIMESTAMP" in t or "DATETIME" in t:
        return datetime(2020, 1, 1) + timedelta(seconds=seed % (10 * 365 * 86400))
    if "DATE" in t:
        return date(2020, 1, 1) + timedelta(days=seed % (10 * 365))
    if "TIME" in t:
        return time((seed // 3600) % 24, (seed // 60) % 60, seed % 60)
    if any(x in t for x in ("VARCHAR", "TEXT", "CHAR", "STRING", "CLOB")):
        m = re.search(r"\((\d+)\)", t)
        limit = int(m.group(1)) if m else 255
        # UUID guarantees uniqueness regardless of column length or row_index magnitude,
        # avoiding UNIQUE collisions when the same table is seeded across multiple
        # check_revision() calls (prior rows survive downgrade and remain in the DB).
        return uuid.uuid4().hex[:limit]

    return uuid.uuid4().hex


def _normalize_for_compare(val: Any) -> Any:
    """
    Normalize a DB-returned value for equality comparison.

    Different drivers return different Python types for the same DB value
    (e.g. psycopg2 returns datetime with tzinfo, sqlite3 returns a string).
    This normalizes to a canonical form so verify() doesn't produce false failures.
    """
    if isinstance(val, datetime):
        # Strip microseconds and timezone for comparison — seeded values have none
        return val.replace(microsecond=0, tzinfo=None)
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, memoryview):
        return bytes(val)
    if isinstance(val, str):
        # Some drivers return datetime as ISO string
        try:
            return datetime.fromisoformat(val).replace(microsecond=0, tzinfo=None)
        except (ValueError, TypeError):
            pass
    return val


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
        # Random offset makes generated values unique per seeder instance, preventing
        # UNIQUE constraint collisions when check_all() seeds the same table multiple times
        # (prior check's rows survive downgrade and remain in the DB for the next check).
        self._offset = random.randint(0, 10**6)

    def _q(self, name: str) -> str:
        return _q(self.engine, name)

    def _is_auto_pk(self, col: ColumnInfo) -> bool:
        """
        Detect auto-generated PK columns: SERIAL/BIGSERIAL, INTEGER AUTOINCREMENT,
        or columns with a server_default sequence. Checking by type string AND
        by whether SQLAlchemy marked them as having a server_default.
        """
        if not col.primary_key:
            return False
        t = col.type_str.upper()
        auto_markers = ("SERIAL", "BIGSERIAL", "AUTOINCREMENT", "AUTO_INCREMENT")
        if any(x in t for x in auto_markers):
            return True
        # SQLAlchemy reflects sequence-backed PKs with a default like "nextval(...)"
        if col.default and "nextval" in str(col.default).lower():
            return True
        return False

    def seed_all(self, tables: dict[str, TableInfo], count: int = 3) -> None:
        for tname in _topological_order(tables):
            self.seed_table(tables[tname], count)

    def seed_table(self, table: TableInfo, count: int = 3) -> None:
        if not table.pk_cols:
            return

        pk_col = table.pk_cols[0]
        unique_groups = _get_unique_constraints(self.engine, table.name)

        for row_index in range(count):
            row: dict[str, Any] = {}
            for col_name, col_info in table.columns.items():
                if self._is_auto_pk(col_info):
                    continue
                if not col_info.nullable:
                    enum_vals = None
                    if "ENUM" in col_info.type_str.upper():
                        enum_vals = _get_enum_values(self.engine, table.name, col_name)
                    val = _generate_value(col_info, self._offset + row_index, enum_vals)
                    if val is not None:
                        row[col_name] = val
                # nullable columns left as NULL intentionally

            # Ensure uniqueness for single-column unique constraints
            for group in unique_groups:
                if len(group) == 1 and group[0] in row:
                    col_name = group[0]
                    col_info = table.columns.get(col_name)
                    if col_info:
                        # Append row_index to guarantee uniqueness
                        val = row[col_name]
                        if isinstance(val, str):
                            row[col_name] = (val + f"_{row_index}")[:255]
                        elif isinstance(val, int):
                            row[col_name] = val + row_index

            if not row:
                continue

            cols = ", ".join(self._q(c) for c in row)
            placeholders = ", ".join(f":p_{c}" for c in row)
            params = {f"p_{c}": v for c, v in row.items()}
            tq = self._q(table.name)
            stmt = text(f"INSERT INTO {tq} ({cols}) VALUES ({placeholders})")

            try:
                with self.engine.begin() as conn:
                    conn.execute(stmt, params)

                with self.engine.connect() as conn:
                    pkq = self._q(pk_col)
                    if pk_col in row:
                        pk_val = row[pk_col]
                    else:
                        result = conn.execute(
                            text(f"SELECT {pkq} FROM {tq} ORDER BY {pkq} DESC LIMIT 1")
                        )
                        pk_val = result.scalar()

                    if pk_val is not None:
                        result = conn.execute(
                            text(f"SELECT * FROM {tq} WHERE {pkq} = :pk"),
                            {"pk": pk_val},
                        )
                        full_row = dict(result.mappings().first() or {})
                        self._rows.append(SeededRow(table.name, pk_col, pk_val, full_row))

            except Exception as exc:
                warnings.warn(
                    f"pytest-mrt: failed to seed row {row_index} into '{table.name}': {exc}",
                    stacklevel=2,
                )

    def seed_custom(self, table: str, pk_col: str, rows: list[dict]) -> None:
        """Insert caller-supplied rows and track them for verify()."""
        tq = self._q(table)
        pkq = self._q(pk_col)
        for row in rows:
            cols = ", ".join(self._q(c) for c in row)
            placeholders = ", ".join(f":p_{c}" for c in row)
            params = {f"p_{c}": v for c, v in row.items()}
            stmt = text(f"INSERT INTO {tq} ({cols}) VALUES ({placeholders})")
            try:
                with self.engine.begin() as conn:
                    conn.execute(stmt, params)
            except Exception as exc:
                warnings.warn(
                    f"pytest-mrt: failed to insert custom row into '{table}': {exc}",
                    stacklevel=2,
                )
                continue

            pk_val = row.get(pk_col)
            if pk_val is None:
                with self.engine.connect() as conn:
                    result = conn.execute(
                        text(f"SELECT {pkq} FROM {tq} ORDER BY {pkq} DESC LIMIT 1")
                    )
                    pk_val = result.scalar()

            if pk_val is not None:
                with self.engine.connect() as conn:
                    result = conn.execute(
                        text(f"SELECT * FROM {tq} WHERE {pkq} = :pk"), {"pk": pk_val}
                    )
                    full_row = dict(result.mappings().first() or {})
                    self._rows.append(SeededRow(table, pk_col, pk_val, full_row))

    def verify(self) -> list[str]:
        """
        Check that every seeded row:
        1. Still exists in its table after rollback
        2. Has the same column values for columns that survived the rollback

        Type-normalizes values before comparison to avoid false failures from
        driver-specific representations (datetime with/without tz, Decimal vs float).
        """
        failures: list[str] = []

        with self.engine.connect() as conn:
            insp = inspect(conn)
            existing_tables = set(insp.get_table_names())

        for seeded in self._rows:
            tname = seeded.table

            if tname not in existing_tables:
                failures.append(
                    f"Table '{tname}' no longer exists after rollback — all seeded rows lost. "
                    f"Fix: add op.create_table('{tname}', ...) to downgrade(), or "
                    "use MRTConfig(skip={...}) with a documented reason if the data loss is intentional."
                )
                continue

            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        f"SELECT * FROM {_q(self.engine, tname)} "
                        f"WHERE {_q(self.engine, seeded.pk_col)} = :pk"
                    ),
                    {"pk": seeded.pk_val},
                )
                row = result.mappings().first()

            if row is None:
                failures.append(
                    f"Table '{tname}': row {seeded.pk_col}={seeded.pk_val!r} lost after rollback. "
                    "This migration deletes or truncates data. "
                    "Fix: ensure downgrade() restores the rows, or use "
                    "MRTConfig(skip={...}) with a documented reason if the data loss is intentional."
                )
                continue

            current = dict(row)
            for col, expected in seeded.data.items():
                if col not in current:
                    continue  # column was dropped by this migration — expected
                actual = current[col]
                if _normalize_for_compare(actual) != _normalize_for_compare(expected):
                    failures.append(
                        f"Table '{tname}': column '{col}' changed after rollback "
                        f"(expected {expected!r}, got {actual!r}). "
                        "Fix: ensure downgrade() restores the original value of this column."
                    )

        return failures

    def reset(self) -> None:
        self._rows.clear()
