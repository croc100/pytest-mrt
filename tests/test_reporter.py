"""Tests for the rich console reporter."""
from __future__ import annotations

from io import StringIO

from rich.console import Console

from pytest_mrt.core.verifier import RevisionResult
from pytest_mrt.reporter import print_check_all_summary, print_revision_result


def _capture(fn, *args) -> str:
    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=False)
    import pytest_mrt.reporter as rep
    original = rep.console
    rep.console = console
    try:
        fn(*args)
    finally:
        rep.console = original
    return buf.getvalue()


def test_passed_result_output():
    result = RevisionResult(revision="001", passed=True)
    out = _capture(print_revision_result, result)
    assert "001" in out
    assert "reversible" in out.lower()


def test_failed_result_output():
    result = RevisionResult(revision="002", passed=False,
                            failures=["Row lost in users table"])
    out = _capture(print_revision_result, result)
    assert "002" in out
    assert "Row lost" in out


def test_skipped_result_output():
    result = RevisionResult(revision="003", passed=True,
                            skipped=True, skip_reason="intentional data migration")
    out = _capture(print_revision_result, result)
    assert "003" in out
    assert "skipped" in out.lower()


def test_summary_all_passed():
    results = [
        RevisionResult(revision="001", passed=True),
        RevisionResult(revision="002", passed=True),
    ]
    out = _capture(print_check_all_summary, results)
    assert "2" in out
    assert "reversible" in out.lower()


def test_summary_with_failures():
    results = [
        RevisionResult(revision="001", passed=True),
        RevisionResult(revision="002", passed=False,
                       failures=["Data lost in orders"]),
    ]
    out = _capture(print_check_all_summary, results)
    assert "002" in out
    assert "Data lost" in out


def test_risk_score_zero_on_pass():
    r = RevisionResult(revision="x", passed=True)
    assert r.risk_score == 0


def test_risk_score_scales_with_failures():
    r = RevisionResult(revision="x", passed=False,
                       failures=["a", "b", "c"])
    assert r.risk_score == 75


def test_risk_score_capped_at_100():
    r = RevisionResult(revision="x", passed=False,
                       failures=["a"] * 10)
    assert r.risk_score == 100


def test_failure_summary_format():
    r = RevisionResult(revision="x", passed=False,
                       failures=["Table lost", "Column missing"])
    summary = r.failure_summary()
    assert "Table lost" in summary
    assert "Column missing" in summary


def test_print_static_check_header():
    from pytest_mrt.reporter import print_static_check_header
    out = _capture(print_static_check_header, "alembic/versions")
    assert "MRT" in out or "alembic" in out or "versions" in out
