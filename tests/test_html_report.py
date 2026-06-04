"""Tests for HTML report generation."""
from __future__ import annotations
import tempfile
from pathlib import Path
import pytest
from pytest_mrt.core.detector import RiskWarning
from pytest_mrt.core.html_report import generate_html_report, _risk_score, _score_color


@pytest.fixture()
def versions_dir(tmp_path):
    v = tmp_path / "versions"
    v.mkdir()
    (v / "001_create_users.py").write_text(
        "revision = '001'\ndown_revision = None\n"
        "def upgrade(): pass\ndef downgrade(): pass\n"
    )
    (v / "002_add_col.py").write_text(
        "revision = '002'\ndown_revision = '001'\n"
        "def upgrade(): pass\ndef downgrade(): pass\n"
    )
    return str(v)


def test_html_report_is_valid_html(versions_dir):
    warnings = []
    html = generate_html_report(versions_dir, warnings)
    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html
    assert "</html>" in html


def test_html_report_contains_revision(versions_dir):
    warnings = []
    html = generate_html_report(versions_dir, warnings)
    assert "001" in html
    assert "002" in html


def test_html_report_shows_safe_when_no_warnings(versions_dir):
    html = generate_html_report(versions_dir, [])
    assert "Safe" in html


def test_html_report_shows_error_warning(versions_dir):
    warnings = [
        RiskWarning("001", "001.py", "DROP COLUMN in upgrade",
                    "Data permanently lost", "error", line=12)
    ]
    html = generate_html_report(versions_dir, warnings)
    assert "DROP COLUMN in upgrade" in html
    assert "Unsafe" in html


def test_html_report_line_number_shown(versions_dir):
    warnings = [
        RiskWarning("001", "001.py", "TRUNCATE", "Destroys all data", "error", line=42)
    ]
    html = generate_html_report(versions_dir, warnings)
    assert "42" in html


def test_html_report_summary_counts(versions_dir):
    warnings = [
        RiskWarning("001", "001.py", "DROP TABLE in upgrade", "msg", "error")
    ]
    html = generate_html_report(versions_dir, warnings)
    # 1 risky, 1 safe (002 has no warnings)
    assert "Will lose data" in html


def test_risk_score_no_issues():
    assert _risk_score([]) == 100


def test_risk_score_errors_reduce_score():
    w = [RiskWarning("x", "x.py", "p", "m", "error")]
    assert _risk_score(w) == 80  # 100 - 20


def test_risk_score_warnings_reduce_score():
    w = [RiskWarning("x", "x.py", "p", "m", "warning")]
    assert _risk_score(w) == 95  # 100 - 5


def test_risk_score_floor_zero():
    w = [RiskWarning("x", "x.py", "p", "m", "error")] * 10
    assert _risk_score(w) == 0


def test_score_color_green():
    assert _score_color(90) == "#22c55e"


def test_score_color_yellow():
    assert _score_color(65) == "#f59e0b"


def test_score_color_red():
    assert _score_color(30) == "#ef4444"
