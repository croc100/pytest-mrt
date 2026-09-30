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


# ── one code, one rule ────────────────────────────────────────────────


def _generator():
    """Import the generator as a module, so a failure prints a readable diff.

    The tests above shell out to it, which is the right shape for "is the
    committed page stale". For these the interesting output is the list of
    offending sites, and a subprocess would hand it back as captured bytes that
    fail to decode on a non-UTF-8 console.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_rule_index

    return gen_rule_index


def test_no_two_rules_share_a_code():
    """A code names one rule.

    MRT413 was once given to a new rule in core/detector.py although
    adapters/django_detector.py already emitted it. Nothing failed: the index
    merged the two into a single row reading `error / warning` for severity and
    `Alembic, Django` for formats, which is the only place it showed at all.
    """
    g = _generator()
    collisions = g.code_collisions(g.collect_sites())
    assert not collisions, "codes naming more than one rule: " + "; ".join(
        f"{code} -> {sorted({s.pattern for s in group})} at "
        f"{', '.join(f'{s.path}:{s.lineno}' for s in group)}"
        for code, group in sorted(collisions.items())
    )


def test_shared_code_allowlist_is_not_stale():
    """Every SHARED_CODES entry still describes two differently-worded rules."""
    g = _generator()
    stale = g.stale_shared_codes(g.collect_sites())
    assert not stale, (
        f"SHARED_CODES entries the source no longer supports: {stale} — "
        "the code is gone, or its sites now agree on a pattern"
    )


def test_shared_codes_are_documented_with_a_reason():
    """The allowlist is only defensible if each entry says why."""
    g = _generator()
    empty = sorted(code for code, reason in g.SHARED_CODES.items() if not reason.strip())
    assert not empty, f"SHARED_CODES entries with no stated reason: {empty}"


def test_collision_check_catches_a_planted_duplicate():
    """The guard fails on a collision rather than merging it away.

    Without this, `test_no_two_rules_share_a_code` would keep passing if
    `code_collisions` were ever reduced to returning an empty dict.
    """
    g = _generator()
    real = g.collect_sites()
    victim = next(s for s in real if s.code == "MRT101")
    planted = g.Site(
        code=victim.code,
        pattern="Some entirely different rule",
        severity="warning",
        fmt="Django",
        path="pytest_mrt/adapters/django_detector.py",
        lineno=1,
    )
    collisions = g.code_collisions([*real, planted])
    assert victim.code in collisions
    assert len(collisions[victim.code]) == 2


def test_allowlisted_code_tolerates_divergent_wording():
    """A SHARED_CODES entry suppresses the check for that code and no other."""
    g = _generator()
    shared = next(iter(g.SHARED_CODES))
    sites = g.collect_sites()
    assert {s.pattern for s in g.sites_by_code(sites)[shared]}.__len__() > 1
    assert shared not in g.code_collisions(sites)


def test_every_site_carries_a_pattern_and_severity():
    """A rule with no pattern string renders as an em dash on the index."""
    g = _generator()
    bad = [str(s) for s in g.collect_sites() if not s.pattern or not s.severity]
    assert not bad, "sites missing a literal pattern or severity: " + "; ".join(bad)


# ── documented severity matches the source ────────────────────────────

ACCURACY_PAGE = ROOT / "docs" / "accuracy.md"

_ENTRY = re.compile(
    r"^#### (?:\d+|[GD]\d+)\. (.+?)\n\| \| \|\n\|---\|---\|\n\| \*\*Severity\*\* \| (\w+)",
    re.MULTILINE,
)

# docs/accuracy.md headings are prose, so they are matched to a rule by a
# normalized comparison against its pattern string. Eight of the 46 entries word
# their heading differently enough not to match; the count below keeps a rename
# from quietly shrinking what this check covers.
_MATCHED_ENTRIES = 38


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _severities_by_normalized_pattern() -> dict[str, set[str]]:
    g = _generator()
    by_pattern: dict[str, set[str]] = {}
    for site in g.collect_sites():
        by_pattern.setdefault(_norm(site.pattern), set()).add(site.severity)
    return by_pattern


def test_documented_severity_matches_the_source():
    """accuracy.md states each rule's severity, and severity sets the exit code.

    D5 and D7 were documented as warnings while django_detector.py emitted both
    as errors, so a reader could not tell from the docs why `mrt check` had
    failed their build.
    """
    by_pattern = _severities_by_normalized_pattern()
    entries = _ENTRY.findall(ACCURACY_PAGE.read_text(encoding="utf-8"))
    disagree = [
        f"{title!r}: page says {documented}, source emits {sorted(by_pattern[key])}"
        for title, documented in entries
        for key in [_norm(title)]
        if key in by_pattern and documented not in by_pattern[key]
    ]
    assert not disagree, "docs/accuracy.md disagrees with the detectors: " + "; ".join(disagree)


def test_severity_check_still_covers_what_it_did():
    """A renamed heading must not silently drop out of the check above."""
    by_pattern = _severities_by_normalized_pattern()
    entries = _ENTRY.findall(ACCURACY_PAGE.read_text(encoding="utf-8"))
    matched = sum(1 for title, _ in entries if _norm(title) in by_pattern)
    assert matched >= _MATCHED_ENTRIES, (
        f"only {matched} of {len(entries)} accuracy.md entries now match a rule pattern, "
        f"down from {_MATCHED_ENTRIES} — a heading was reworded, so the severity check "
        "above silently stopped covering it"
    )
