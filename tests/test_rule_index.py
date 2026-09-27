"""The rule index must stay in step with the detectors.

`mrt check` prints codes like MRT213. Before docs/rules.md existed, 45 of the 52
codes appeared nowhere in the documentation, and the hand-maintained count on the
README had already drifted from the source by one. These tests make that class of
drift a build failure rather than something a reader discovers.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "gen_rule_index.py"
RULES_PAGE = ROOT / "docs" / "rules.md"


def _codes_in_package() -> set[str]:
    codes: set[str] = set()
    for path in (ROOT / "pytest_mrt").rglob("*.py"):
        codes |= set(re.findall(r'code="(MRT\d{3})"', path.read_text(encoding="utf-8")))
    return codes


def test_rule_index_is_current():
    """docs/rules.md matches what the detectors emit right now."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"{result.stdout}{result.stderr}\n"
        "docs/rules.md is stale — run: python scripts/gen_rule_index.py"
    )


def test_every_code_is_documented():
    """No code can reach a user's terminal without a row on the index page."""
    page = RULES_PAGE.read_text(encoding="utf-8")
    documented = set(re.findall(r"`(MRT\d{3})`", page))
    missing = sorted(_codes_in_package() - documented)
    assert not missing, f"codes emitted but not on docs/rules.md: {missing}"


def test_index_documents_nothing_invented():
    """The page lists no code the package cannot emit."""
    page = RULES_PAGE.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `(MRT\d{3})`", page, re.MULTILINE))
    extra = sorted(documented - _codes_in_package())
    assert not extra, f"codes on docs/rules.md that no detector emits: {extra}"


def test_generator_is_deterministic():
    """Two runs produce the same bytes, so the page never churns in a diff."""
    first = subprocess.run(
        [sys.executable, str(GENERATOR)], capture_output=True, text=True, cwd=ROOT
    )
    assert first.returncode == 0, first.stderr
    before = RULES_PAGE.read_bytes()
    second = subprocess.run(
        [sys.executable, str(GENERATOR)], capture_output=True, text=True, cwd=ROOT
    )
    assert second.returncode == 0, second.stderr
    assert RULES_PAGE.read_bytes() == before


def test_every_generated_link_resolves():
    """Each patterns.md anchor the index links to exists as a heading there.

    The generator mirrors python-markdown's slugify; when that mirror was wrong
    (underscores stripped, runs of spaces not collapsed) the page shipped 11 dead
    links that only a --strict mkdocs build would have mentioned, at INFO level.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_rule_index

    anchors = set(gen_rule_index.patterns_anchors().values())
    linked = set(re.findall(r"patterns\.md#([\w-]+)", RULES_PAGE.read_text(encoding="utf-8")))
    dead = sorted(linked - anchors)
    assert not dead, f"rules.md links to anchors patterns.md does not have: {dead}"
