"""
Rule-based automatic fix generation for common migration issues.

Analyzes the upgrade() body and generates the missing or incorrect downgrade().
Does not modify files without explicit user confirmation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FixSuggestion:
    revision: str
    file: str
    issue: str
    original_downgrade: str
    suggested_downgrade: str
    confidence: str  # "high" | "medium" | "low"
    warning: str | None = None


def _fn_body(source: str, fn_name: str) -> str:
    m = re.search(
        rf"def {fn_name}\s*\([^)]*\)\s*(?:->.*?)?\s*:\s*\n((?:[ \t]+[^\n]*\n?)*)",
        source,
    )
    return m.group(1) if m else ""


def _indent(lines: list[str], spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in lines)


def _generate_reverse_ops(upgrade_body: str) -> list[str] | None:
    """
    Parse upgrade() operations and generate their reverse.
    Returns list of reverse op lines, or None if we can't auto-generate.
    """
    ops: list[str] = []

    # CREATE TABLE → DROP TABLE
    for m in re.finditer(r'op\.create_table\s*\(\s*["\'](\w+)["\']', upgrade_body):
        ops.append(f'op.drop_table("{m.group(1)}")')

    # ADD COLUMN → DROP COLUMN
    for m in re.finditer(
        r'op\.add_column\s*\(\s*["\'](\w+)["\'][^)]*sa\.Column\s*\(\s*["\'](\w+)["\']',
        upgrade_body,
        re.DOTALL,
    ):
        ops.append(f'op.drop_column("{m.group(1)}", "{m.group(2)}")')

    # CREATE INDEX → DROP INDEX
    for m in re.finditer(
        r'op\.create_index\s*\(\s*["\'](\w+)["\'],\s*["\'](\w+)["\']', upgrade_body
    ):
        ops.append(f'op.drop_index("{m.group(1)}", table_name="{m.group(2)}")')

    # DROP INDEX → CREATE INDEX (with columns)
    for m in re.finditer(
        r'op\.drop_index\s*\(\s*["\'](\w+)["\'][^)]*table_name\s*=\s*["\'](\w+)["\']',
        upgrade_body,
    ):
        ops.append(
            f'# TODO: recreate index "{m.group(1)}" on table "{m.group(2)}" with correct columns\n'
            f'# op.create_index("{m.group(1)}", "{m.group(2)}", ["column_name"])'
        )

    # RENAME TABLE → RENAME BACK
    for m in re.finditer(
        r'op\.rename_table\s*\(\s*["\'](\w+)["\'],\s*["\'](\w+)["\']', upgrade_body
    ):
        ops.append(f'op.rename_table("{m.group(2)}", "{m.group(1)}")')

    # RENAME COLUMN → RENAME BACK
    for m in re.finditer(
        r'op\.alter_column\s*\(\s*["\'](\w+)["\'],\s*["\'](\w+)["\'][^)]*new_column_name\s*=\s*["\'](\w+)["\']',
        upgrade_body,
        re.DOTALL,
    ):
        ops.append(
            f'op.alter_column("{m.group(1)}", "{m.group(3)}", new_column_name="{m.group(2)}")'
        )

    # CREATE UNIQUE CONSTRAINT → DROP CONSTRAINT
    for m in re.finditer(
        r'op\.create_unique_constraint\s*\(\s*["\'](\w+)["\'],\s*["\'](\w+)["\']',
        upgrade_body,
    ):
        ops.append(f'op.drop_constraint("{m.group(1)}", "{m.group(2)}")')

    # CREATE FOREIGN KEY → DROP CONSTRAINT
    for m in re.finditer(
        r'op\.create_foreign_key\s*\(\s*["\'](\w+)["\'],\s*["\'](\w+)["\']',
        upgrade_body,
    ):
        ops.append(f'op.drop_constraint("{m.group(1)}", "{m.group(2)}", type_="foreignkey")')

    return ops if ops else None


def _confidence(ops: list[str]) -> str:
    if any("TODO" in op for op in ops):
        return "medium"
    if len(ops) == 0:
        return "low"
    return "high"


def generate_fix(migration_path: str) -> FixSuggestion | None:
    """
    Analyze a migration file and return a fix suggestion if one can be generated.
    Returns None if the migration looks fine or if we can't auto-fix it.
    """
    path = Path(migration_path)
    source = path.read_text()

    rev_m = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
    revision = rev_m.group(1) if rev_m else path.stem

    has_downgrade = bool(re.search(r"def downgrade\s*\(", source))
    downgrade_body = _fn_body(source, "downgrade")
    upgrade_body = _fn_body(source, "upgrade")

    # Strip comments and blank lines to detect true noop
    non_comment_lines = [
        line.strip()
        for line in downgrade_body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    is_noop = not non_comment_lines or all(line == "pass" for line in non_comment_lines)

    if has_downgrade and not is_noop:
        return None  # downgrade looks non-trivial, nothing to fix automatically

    issue = "Missing downgrade()" if not has_downgrade else "No-op downgrade()"

    reverse_ops = _generate_reverse_ops(upgrade_body)

    if not reverse_ops:
        return FixSuggestion(
            revision=revision,
            file=path.name,
            issue=issue,
            original_downgrade=downgrade_body,
            suggested_downgrade="    # Could not auto-generate — too complex\n    # Review upgrade() and write the reverse manually",
            confidence="low",
            warning="Auto-fix could not determine the correct downgrade. Manual review required.",
        )

    suggested_body = _indent(reverse_ops)
    conf = _confidence(reverse_ops)

    warning = None
    if "drop_column" in suggested_body or "drop_table" in suggested_body:
        warning = (
            "The suggested downgrade drops data that was added in upgrade(). "
            "This is intentional — it reverses the upgrade — but verify this is what you want."
        )

    return FixSuggestion(
        revision=revision,
        file=path.name,
        issue=issue,
        original_downgrade=downgrade_body,
        suggested_downgrade=suggested_body,
        confidence=conf,
        warning=warning,
    )


def apply_fix(migration_path: str, fix: FixSuggestion) -> None:
    """Write the suggested downgrade() into the migration file."""
    path = Path(migration_path)
    source = path.read_text()

    new_downgrade_fn = f"def downgrade() -> None:\n{fix.suggested_downgrade}\n"

    if re.search(r"def downgrade\s*\(", source):
        # Replace existing downgrade
        source = re.sub(
            r"def downgrade\s*\([^)]*\)\s*(?:->.*?)?\s*:\s*\n(?:[ \t]+[^\n]*\n?)*",
            new_downgrade_fn,
            source,
        )
    else:
        # Append after upgrade
        source = source.rstrip() + "\n\n\n" + new_downgrade_fn

    path.write_text(source)
