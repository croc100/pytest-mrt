from __future__ import annotations

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ..adapters.django_detector import analyze_django_migrations, is_django_migration
from ..core.detector import analyze_migrations

console = Console()


def _severity_color(s: str) -> str:
    return "red" if s == "error" else "yellow"


def check(
    versions_dir: str = typer.Argument(help="Path to Alembic versions directory"),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors (exit 2)"),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table | json | html"),
    output: str | None = typer.Option(None, "--output", "-o", help="Write output to file (for --format html/json)"),
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "Only check migrations added after this revision. "
            "Alembic: revision ID (e.g. 'a1b2c3d4'). "
            "Django: app_label.migration_name (e.g. 'myapp.0010_add_email'). "
            "Useful in CI to skip already-reviewed history."
        ),
    ),
) -> None:
    """Statically analyze migrations for rollback risk patterns (Alembic and Django)."""
    from pathlib import Path as _Path

    _path = _Path(versions_dir)
    if not _path.exists():
        console.print(f"[red]Error: path does not exist: {versions_dir}[/red]")
        raise typer.Exit(1)
    if not _path.is_dir():
        console.print(f"[red]Error: not a directory: {versions_dir}[/red]")
        raise typer.Exit(1)

    sample_files = list(_path.rglob("*.py"))[:5]
    is_django = any(is_django_migration(p) for p in sample_files)

    if since:
        # Validate that --since actually matches something before running analysis.
        if is_django:
            from ..adapters.django_detector import _django_migrations_since

            since_set = _django_migrations_since(versions_dir, since)
        else:
            from ..core.detector import _revisions_since

            since_set = _revisions_since(versions_dir, since)

        if not since_set:
            console.print(
                f"[yellow]Warning: --since {since} matched no migrations. "
                "Check the revision ID and try again.[/yellow]"
            )
            raise typer.Exit(1)

        console.print(
            f"[dim]--since {since}: checking {len(since_set)} migration(s) after this point[/dim]"
        )
        console.print(
            "[dim]Note: graph checks (orphan, data-hole detection) skipped — "
            "run without --since for full analysis.[/dim]"
        )

    if is_django:
        console.print("[dim]Detected: Django migrations[/dim]")
        warnings = analyze_django_migrations(versions_dir, since=since)
    else:
        warnings = analyze_migrations(versions_dir, since=since)

    if fmt == "json":
        import json
        import sys
        from datetime import datetime, timezone
        from importlib.metadata import version as pkg_version

        _FIXABLE_CODES = {"MRT101", "MRT102"}

        try:
            _ver = pkg_version("pytest-mrt")
        except Exception:
            _ver = "unknown"

        errors = [w for w in warnings if w.severity == "error"]
        warns = [w for w in warnings if w.severity == "warning"]

        payload = {
            "version": _ver,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {
                "total_issues": len(warnings),
                "errors": len(errors),
                "warnings": len(warns),
            },
            "findings": [
                {
                    "file": w.file,
                    "line": w.line,
                    "rule": w.code,
                    "severity": w.severity,
                    "pattern": w.pattern,
                    "message": w.message,
                    "fixable": w.code in _FIXABLE_CODES,
                }
                for w in warnings
            ],
        }
        json_text = json.dumps(payload, indent=2) + "\n"
        if output:
            from pathlib import Path as _Path
            _Path(output).write_text(json_text)
            console.print(f"[green]✓ JSON report saved to [bold]{output}[/bold][/green]")
        else:
            sys.stdout.write(json_text)
        has_errors = bool(errors)
        has_warns = bool(warns)
        if has_errors or (strict and has_warns):
            raise typer.Exit(2)
        if has_warns:
            raise typer.Exit(1)
        raise typer.Exit(0)

    if fmt == "html":
        from pathlib import Path as _Path

        from ..core.html_report import generate_html_report

        html = generate_html_report(versions_dir, warnings)
        out_path = output or "mrt-report.html"
        _Path(out_path).write_text(html)
        console.print(f"[green]✓ HTML report saved to [bold]{out_path}[/bold][/green]")
        console.print(
            f"  Open: [link=file://{_Path(out_path).absolute()}]{_Path(out_path).absolute()}[/link]"
        )
        errors = [w for w in warnings if w.severity == "error"]
        warns = [w for w in warnings if w.severity == "warning"]
        if errors or (strict and warns):
            raise typer.Exit(2)
        if warns:
            raise typer.Exit(1)
        raise typer.Exit(0)

    if not warnings:
        console.print("[green]✓ No rollback risks detected.[/green]")
        raise typer.Exit(0)

    errors = [w for w in warnings if w.severity == "error"]
    warns = [w for w in warnings if w.severity == "warning"]

    table = Table(box=box.ROUNDED, title="Rollback Risk Analysis", show_lines=True)
    table.add_column("Revision", style="cyan", no_wrap=True)
    table.add_column("Code", style="dim", no_wrap=True)
    table.add_column("Pattern", no_wrap=True)
    table.add_column("Sev", no_wrap=True)
    table.add_column("Line", no_wrap=True, justify="right")
    table.add_column("Message")

    for w in warnings:
        c = _severity_color(w.severity)
        line_str = str(w.line) if w.line is not None else ""
        table.add_row(
            w.revision, w.code, w.pattern, f"[{c}]{w.severity}[/{c}]", line_str, w.message
        )

    console.print(table)
    console.print()

    if errors:
        console.print(
            f"[red]{len(errors)} error(s)[/red], [yellow]{len(warns)} warning(s)[/yellow]"
        )
        raise typer.Exit(2)
    elif warns and strict:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] (--strict: treated as errors)")
        raise typer.Exit(2)
    else:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] — review before deploying")
        raise typer.Exit(1)
