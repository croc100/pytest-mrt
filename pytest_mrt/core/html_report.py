"""HTML report generation for migration safety analysis."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .detector import RiskWarning

_SEVERITY_COLOR = {"error": "#ef4444", "warning": "#f59e0b"}
_SEVERITY_BG = {"error": "#fef2f2", "warning": "#fffbeb"}


def _risk_score(warnings: list[RiskWarning]) -> int:
    errors = sum(1 for w in warnings if w.severity == "error")
    warns = sum(1 for w in warnings if w.severity == "warning")
    score = max(0, 100 - errors * 20 - warns * 5)
    return score


def _score_color(score: int) -> str:
    if score >= 80:
        return "#22c55e"
    if score >= 50:
        return "#f59e0b"
    return "#ef4444"


def _revision_card(revision: str, warnings: list[RiskWarning]) -> str:
    errors = [w for w in warnings if w.severity == "error"]
    warns = [w for w in warnings if w.severity == "warning"]

    if errors:
        status_color = "#ef4444"
        status_icon = "✗"
        status_label = "Unsafe"
        card_border = "#fca5a5"
    elif warns:
        status_color = "#f59e0b"
        status_icon = "⚠"
        status_label = "Review"
        card_border = "#fcd34d"
    else:
        status_color = "#22c55e"
        status_icon = "✓"
        status_label = "Safe"
        card_border = "#86efac"

    rows = ""
    for w in warnings:
        color = _SEVERITY_COLOR[w.severity]
        line_info = f" <span style='color:#9ca3af'>line {w.line}</span>" if w.line else ""
        rows += f"""
        <tr>
          <td style="padding:6px 12px;color:{color};font-weight:600">{w.severity.upper()}</td>
          <td style="padding:6px 12px;font-family:monospace;font-size:0.85em">{w.pattern}{line_info}</td>
          <td style="padding:6px 12px;color:#374151">{w.message}</td>
        </tr>"""

    table = ""
    if rows:
        table = f"""
      <table style="width:100%;border-collapse:collapse;margin-top:12px;background:#fff;border-radius:6px;overflow:hidden">
        <thead>
          <tr style="background:#f9fafb">
            <th style="padding:6px 12px;text-align:left;color:#6b7280;font-size:0.8em">SEV</th>
            <th style="padding:6px 12px;text-align:left;color:#6b7280;font-size:0.8em">PATTERN</th>
            <th style="padding:6px 12px;text-align:left;color:#6b7280;font-size:0.8em">MESSAGE</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>"""

    fname = warnings[0].file if warnings else ""
    score = _risk_score(warnings)
    sc = _score_color(score)

    return f"""
  <div style="border:1px solid {card_border};border-radius:8px;padding:16px;margin-bottom:12px;background:#fff">
    <div style="display:flex;align-items:center;gap:12px">
      <span style="font-size:1.4em;color:{status_color}">{status_icon}</span>
      <div>
        <span style="font-family:monospace;font-weight:600;color:#111">{revision}</span>
        <span style="color:#9ca3af;font-size:0.85em;margin-left:8px">{fname}</span>
      </div>
      <span style="margin-left:auto;display:flex;align-items:center;gap:8px">
        <span style="font-size:0.8em;color:{sc};font-weight:700">Score {score}/100</span>
        <span style="padding:2px 10px;border-radius:20px;font-size:0.8em;
                     background:{status_color};color:#fff;font-weight:600">{status_label}</span>
      </span>
    </div>
    {table}
  </div>"""


def generate_html_report(versions_dir: str, warnings: list[RiskWarning]) -> str:
    # Group by revision
    by_revision: dict[str, list[RiskWarning]] = {}
    all_files = sorted(Path(versions_dir).glob("*.py"))

    for path in all_files:
        import re

        source = path.read_text()
        m = re.search(r'revision\s*=\s*["\']([^"\']+)["\']', source)
        rev = m.group(1) if m else path.stem
        by_revision.setdefault(rev, [])

    for w in warnings:
        by_revision.setdefault(w.revision, []).append(w)

    total = len(by_revision)
    safe = sum(1 for ws in by_revision.values() if not ws)
    risky = sum(1 for ws in by_revision.values() if any(w.severity == "error" for w in ws))
    review = total - safe - risky

    cards = ""
    for rev, ws in by_revision.items():
        cards += _revision_card(rev, ws)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>pytest-mrt Migration Safety Report</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f3f4f6; color: #111827; line-height: 1.5; }}
    .container {{ max-width: 900px; margin: 0 auto; padding: 32px 16px; }}
    .header {{ background: #1e1b4b; color: #fff; border-radius: 12px;
               padding: 32px; margin-bottom: 24px; }}
    .header h1 {{ font-size: 1.6em; font-weight: 700; margin-bottom: 4px; }}
    .header p {{ color: #a5b4fc; font-size: 0.9em; }}
    .summary {{ display: grid; grid-template-columns: repeat(3, 1fr);
                gap: 12px; margin-bottom: 24px; }}
    .stat {{ background: #fff; border-radius: 8px; padding: 20px;
             text-align: center; border: 1px solid #e5e7eb; }}
    .stat .number {{ font-size: 2.2em; font-weight: 700; }}
    .stat .label {{ font-size: 0.85em; color: #6b7280; margin-top: 4px; }}
    .section-title {{ font-size: 0.9em; font-weight: 600; color: #6b7280;
                      text-transform: uppercase; letter-spacing: 0.05em;
                      margin-bottom: 12px; }}
    .footer {{ text-align: center; color: #9ca3af; font-size: 0.8em; margin-top: 32px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Migration Safety Report</h1>
      <p>Generated by pytest-mrt · {now} · {versions_dir}</p>
    </div>

    <div class="summary">
      <div class="stat">
        <div class="number" style="color:#22c55e">{safe}</div>
        <div class="label">Safe to roll back</div>
      </div>
      <div class="stat">
        <div class="number" style="color:#f59e0b">{review}</div>
        <div class="label">Needs review</div>
      </div>
      <div class="stat">
        <div class="number" style="color:#ef4444">{risky}</div>
        <div class="label">Will lose data</div>
      </div>
    </div>

    <div class="section-title">All migrations ({total} total)</div>
    {cards}

    <div class="footer">
      Generated by <a href="https://github.com/croc100/pytest-mrt" style="color:#6366f1">pytest-mrt</a>
      · <a href="https://croc100.github.io/pytest-mrt" style="color:#6366f1">Documentation</a>
    </div>
  </div>
</body>
</html>"""
