from __future__ import annotations
from dataclasses import dataclass, field
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

_INTERNAL_TABLES = {"alembic_version"}


@dataclass
class ColumnInfo:
    name: str
    type_str: str
    nullable: bool
    default: str | None = None
    primary_key: bool = False


@dataclass
class TableInfo:
    name: str
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    pk_cols: list[str] = field(default_factory=list)
    fk_tables: list[str] = field(default_factory=list)


@dataclass
class SchemaSnapshot:
    tables: dict[str, TableInfo] = field(default_factory=dict)

    @classmethod
    def capture(cls, engine: Engine) -> SchemaSnapshot:
        snap = cls()
        with engine.connect() as conn:
            insp = inspect(conn)
            for tname in insp.get_table_names():
                if tname in _INTERNAL_TABLES:
                    continue
                ti = TableInfo(name=tname)
                pk_info = insp.get_pk_constraint(tname)
                ti.pk_cols = pk_info.get("constrained_columns", [])
                ti.fk_tables = list(
                    {fk["referred_table"] for fk in insp.get_foreign_keys(tname)}
                )
                for col in insp.get_columns(tname):
                    ti.columns[col["name"]] = ColumnInfo(
                        name=col["name"],
                        type_str=str(col["type"]),
                        nullable=col.get("nullable", True),
                        default=str(col["default"])
                        if col.get("default") is not None
                        else None,
                        primary_key=col["name"] in ti.pk_cols,
                    )
                snap.tables[tname] = ti
        return snap


@dataclass
class SchemaIssue:
    table: str
    message: str
    severity: str  # "error" | "warning"


@dataclass
class SchemaDiff:
    dropped_tables: list[str] = field(default_factory=list)
    added_tables: list[str] = field(default_factory=list)
    dropped_columns: dict[str, list[str]] = field(default_factory=dict)
    added_columns: dict[str, list[str]] = field(default_factory=dict)
    type_changed: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)

    @classmethod
    def compute(cls, before: SchemaSnapshot, after: SchemaSnapshot) -> SchemaDiff:
        diff = cls()
        before_t = set(before.tables)
        after_t = set(after.tables)
        diff.dropped_tables = sorted(before_t - after_t)
        diff.added_tables = sorted(after_t - before_t)
        for t in before_t & after_t:
            before_c = set(before.tables[t].columns)
            after_c = set(after.tables[t].columns)
            dropped = sorted(before_c - after_c)
            added = sorted(after_c - before_c)
            if dropped:
                diff.dropped_columns[t] = dropped
            if added:
                diff.added_columns[t] = added
            for col in before_c & after_c:
                bt = before.tables[t].columns[col].type_str
                at = after.tables[t].columns[col].type_str
                if bt != at:
                    diff.type_changed.setdefault(t, []).append((col, bt, at))
        return diff

    def verify_restored(
        self, before: SchemaSnapshot, after_rollback: SchemaSnapshot
    ) -> list[SchemaIssue]:
        issues = []
        before_t = set(before.tables)
        restored_t = set(after_rollback.tables)

        for t in before_t - restored_t:
            issues.append(
                SchemaIssue(t, f"Table '{t}' missing after rollback", "error")
            )

        for t in restored_t - before_t:
            issues.append(
                SchemaIssue(
                    t,
                    f"Table '{t}' still exists after rollback — downgrade is incomplete",
                    "error",
                )
            )

        for t in before_t & restored_t:
            before_c = set(before.tables[t].columns)
            restored_c = set(after_rollback.tables[t].columns)
            for col in before_c - restored_c:
                issues.append(
                    SchemaIssue(
                        t, f"Column '{t}.{col}' missing after rollback", "error"
                    )
                )
            for col in restored_c - before_c:
                issues.append(
                    SchemaIssue(
                        t,
                        f"Column '{t}.{col}' still present after rollback — downgrade is incomplete",
                        "warning",
                    )
                )

        return issues
