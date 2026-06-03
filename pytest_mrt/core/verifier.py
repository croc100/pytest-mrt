from dataclasses import dataclass


@dataclass
class SeedRecord:
    table: str
    pk_col: str
    pk_vals: list
    expected_rows: list[dict]


class RollbackVerifier:
    def __init__(self, runner):
        self.runner = runner
        self._seeds: list[SeedRecord] = []

    def seed(self, table: str, rows: list[dict], pk_col: str = "id") -> None:
        from sqlalchemy import text
        pk_vals = []
        with self.runner.engine.begin() as conn:
            for row in rows:
                conn.execute(
                    text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(f':{k}' for k in row)})"),
                    row,
                )
                pk_vals.append(row[pk_col])
        self._seeds.append(SeedRecord(table, pk_col, pk_vals, rows))

    def verify(self) -> list[str]:
        failures = []
        for record in self._seeds:
            surviving = self.runner.fetch_rows(record.table, record.pk_col, record.pk_vals)
            surviving_pks = {r[record.pk_col] for r in surviving}
            lost_pks = [v for v in record.pk_vals if v not in surviving_pks]
            if lost_pks:
                failures.append(
                    f"Table '{record.table}': {len(lost_pks)} row(s) lost after rollback "
                    f"(pk={record.pk_col}, values={lost_pks})"
                )
        return failures

    def reset(self) -> None:
        self._seeds.clear()
