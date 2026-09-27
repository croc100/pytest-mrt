#!/usr/bin/env python3
"""Generate docs/rules.md — the MRT code index — from the detector sources.

`mrt check` prints codes like MRT213, and until this page existed 45 of the 52
codes appeared nowhere in the docs, so there was no way to look one up. The page
is generated rather than written because the hand-maintained count ("44
patterns") had already drifted from the source by one.

Run after adding or changing a rule:

    python scripts/gen_rule_index.py

`tests/test_rule_index.py` fails when the committed page no longer matches the
source, so CI catches a forgotten run.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "rules.md"
PATTERNS_PAGE = ROOT / "docs" / "patterns.md"

# Modules that emit rule codes, and the migration format each one reads.
SOURCES = {
    "pytest_mrt/core/detector.py": "Alembic",
    "pytest_mrt/core/compat.py": "Alembic",
    "pytest_mrt/adapters/django_detector.py": "Django",
    "pytest_mrt/adapters/django_compat.py": "Django",
}

# Editorial group titles. Membership is read from the source; only the titles
# live here, and an unknown family makes the script fail rather than guess.
FAMILIES = {
    "1": "MRT1xx — Irreversible migrations",
    "2": "MRT2xx — Data loss",
    "3": "MRT3xx — Renames and type changes",
    "4": "MRT4xx — Constraints, nullability and locking",
    "5": "MRT5xx — Sequences, triggers and types",
    "6": "MRT6xx — Squashed migrations (Django)",
    "7": "MRT7xx — Rolling-deploy compatibility",
    "9": "MRT9xx — Migration graph",
}


@dataclass
class Rule:
    code: str
    pattern: str
    severities: set[str]
    formats: set[str]
    sites: int

    @property
    def family(self) -> str:
        return self.code[3]


def _literal_str(node: ast.expr | None) -> str | None:
    """Return a string from a literal, an implicit concatenation, or an f-string."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        return "".join(parts) or None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_str(node.left) or ""
        right = _literal_str(node.right) or ""
        return (left + right) or None
    return None


def _arg(call: ast.Call, index: int, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    if len(call.args) > index:
        return call.args[index]
    return None


def collect_rules() -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for rel, fmt in SOURCES.items():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name):
                continue
            # Two shapes are in use: the _warn(m, pattern, message, severity)
            # helper, and RiskWarning(revision, filename, pattern, message,
            # severity) built directly where there is no MigrationAST to pass.
            if node.func.id == "_warn":
                pattern_i, severity_i = 1, 3
            elif node.func.id == "RiskWarning":
                pattern_i, severity_i = 2, 4
            else:
                continue
            code = _literal_str(_arg(node, 99, "code"))
            if not code or not re.fullmatch(r"MRT\d{3}", code):
                continue
            pattern = _literal_str(_arg(node, pattern_i, "pattern")) or ""
            severity = _literal_str(_arg(node, severity_i, "severity")) or ""
            if code in rules:
                existing = rules[code]
                existing.formats.add(fmt)
                existing.sites += 1
                # One code may legitimately fire at two severities — MRT411 is an
                # error when null=False is explicit and a warning when it is inferred.
                if severity:
                    existing.severities.add(severity)
            else:
                rules[code] = Rule(code, pattern, {severity} if severity else set(), {fmt}, 1)
    return rules


# Headings in docs/patterns.md whose wording differs from the rule's pattern
# string. Each one is validated against the real headings below, so renaming a
# section breaks this script instead of leaving a dead link on the page.
ALIASES = {
    "MRT204": "ON DELETE CASCADE added",
    "MRT304": "ALTER TYPE ... ADD VALUE (PostgreSQL ENUM)",
    "MRT401": "NOT NULL without server_default",
    "MRT402": "NOT NULL without restoring nullable",
    "MRT404": "ADD COLUMN with DEFAULT (large tables, PostgreSQL < 11)",
    "MRT405": "ADD COLUMN with DEFAULT (large tables, PostgreSQL < 11)",
    "MRT406": "CREATE UNIQUE CONSTRAINT on existing data",
    "MRT407": "CREATE INDEX without CONCURRENTLY (PostgreSQL)",
    "MRT408": "DROP INDEX without recreating",
    "MRT409": "DROP CONSTRAINT without recreating",
    "MRT501": "ALTER SEQUENCE / setval",
}


def patterns_anchors() -> dict[str, str]:
    """Map a normalized heading from docs/patterns.md to its anchor."""
    anchors: dict[str, str] = {}
    for line in PATTERNS_PAGE.read_text(encoding="utf-8").split("\n"):
        if not line.startswith("### "):
            continue
        heading = line[4:].strip()
        # Mirrors python-markdown's toc slugify, which collapses runs of spaces
        # and hyphens — an em dash in "MRT701 — DROP COLUMN" leaves two spaces.
        anchor = re.sub(r"[^\w\s-]", "", heading.lower()).strip()
        anchor = re.sub(r"[-\s]+", "-", anchor)
        anchors[_norm(heading)] = anchor
        # Newer sections are titled "MRT601 — ...", so index them by code too.
        code_match = re.match(r"(MRT\d{3})\b", heading)
        if code_match:
            anchors[code_match.group(1)] = anchor
    for code, heading in ALIASES.items():
        if _norm(heading) not in anchors:
            sys.exit(
                f"ALIASES[{code}] names a heading that docs/patterns.md no longer has: {heading!r}"
            )
    return anchors


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def details_link(code: str, pattern: str, anchors: dict[str, str]) -> str:
    if code in anchors:
        return f"[explained](patterns.md#{anchors[code]})"
    if code in ALIASES:
        return f"[explained](patterns.md#{anchors[_norm(ALIASES[code])]})"
    key = _norm(pattern)
    if key in anchors:
        return f"[explained](patterns.md#{anchors[key]})"
    # Prefix match catches "Missing downgrade" against "Missing downgrade function".
    for heading, anchor in anchors.items():
        if heading.startswith(key) or key.startswith(heading):
            return f"[explained](patterns.md#{anchor})"
    return "—"


def render(rules: dict[str, Rule], anchors: dict[str, str]) -> str:
    lines = [
        "<!-- Generated by scripts/gen_rule_index.py — do not edit by hand. -->",
        "",
        "# Rule index",
        "",
        f"Every code `mrt check` can print: **{len(rules)} rules** across "
        f"{len(FAMILIES)} groups. Extracted from the detector sources, so this page cannot "
        "drift from the implementation — `tests/test_rule_index.py` fails if it does.",
        "",
        "Suppress any single rule inline with `# noqa: MRTxxx`, or change its severity with "
        "`MRTConfig(severity_overrides={...})`. See the "
        "[pattern explanations](patterns.md) for what each one costs you in production.",
        "",
        "A rule listed as `error / warning` fires at either severity depending on how certain the "
        "detection is — `MRT411`, for instance, is an error when a field is explicitly `null=False` "
        "with no default and a warning when that has to be inferred from the field type.",
        "",
    ]

    unknown = sorted({r.family for r in rules.values()} - set(FAMILIES))
    if unknown:
        sys.exit(f"No group title for families: {unknown} — add them to FAMILIES")

    for family, title in FAMILIES.items():
        members = sorted((r for r in rules.values() if r.family == family), key=lambda r: r.code)
        if not members:
            continue
        lines += [
            f"## {title}",
            "",
            "| Code | Severity | Pattern | Migrations | Details |",
            "|---|---|---|---|---|",
        ]
        for rule in members:
            formats = ", ".join(sorted(rule.formats))
            lines.append(
                f"| `{rule.code}` | {' / '.join(sorted(rule.severities)) or '—'} | {rule.pattern or '—'} "
                f"| {formats} | {details_link(rule.code, rule.pattern, anchors)} |"
            )
        lines.append("")

    counted = {
        fmt: sum(1 for r in rules.values() if fmt in r.formats) for fmt in ("Alembic", "Django")
    }
    explained = sum(1 for r in rules.values() if details_link(r.code, r.pattern, anchors) != "—")
    lines += [
        "## Counts",
        "",
        f"- With a prose section in [pattern explanations](patterns.md): **{explained} of {len(rules)}**. "
        "The rest are described by the message `mrt check` prints; the Django rules are the "
        "largest gap and are not yet written up there.",
        f"- Alembic migrations: **{counted['Alembic']}** rules",
        f"- Django migrations: **{counted['Django']}** rules",
        f"- Total distinct codes: **{len(rules)}**",
        "",
        "A rule listed for both formats is implemented once per format, over that format's own "
        "syntax — the two detectors share no rule bodies.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if docs/rules.md is stale")
    args = parser.parse_args()

    content = render(collect_rules(), patterns_anchors())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print("docs/rules.md is out of date — run: python scripts/gen_rule_index.py")
            return 1
        print("docs/rules.md is up to date")
        return 0

    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
