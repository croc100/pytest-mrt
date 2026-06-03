from dataclasses import dataclass, field


@dataclass
class MRTConfig:
    alembic_ini: str = "alembic.ini"
    db_url: str = ""
    seed_rows: int = 10
