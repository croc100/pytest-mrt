import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RiskWarning:
    revision: str
    file: str
    pattern: str
    message: str
    severity: str  # "error" | "warning"


_PATTERNS = [
    ("DROP COLUMN", r"op\.drop_column", "error", "Data loss on rollback — dropped column cannot be recovered"),
    ("DROP TABLE", r"op\.drop_table", "error", "Data loss on rollback — dropped table cannot be recovered"),
    ("NOT NULL no default", r"op\.add_column.*nullable=False(?!.*server_default)", "warning", "ADD NOT NULL without default may fail rollback on non-empty tables"),
    ("No downgrade", r"def downgrade\(\)[^:]*:\s*pass", "error", "downgrade() is a no-op — migration is irreversible"),
]


def analyze_migrations(versions_dir: str) -> list[RiskWarning]:
    warnings = []
    for path in sorted(Path(versions_dir).glob("*.py")):
        source = path.read_text()
        rev_match = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        revision = rev_match.group(1) if rev_match else path.stem
        for name, pattern, severity, message in _PATTERNS:
            if re.search(pattern, source, re.DOTALL):
                warnings.append(RiskWarning(revision, path.name, name, message, severity))
    return warnings
