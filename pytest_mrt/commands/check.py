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
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table | json"),
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

    if is_django:
        console.print("[dim]Detected: Django migrations[/dim]")
        warnings = analyze_django_migrations(versions_dir)
    else:
        warnings = analyze_migrations(versions_dir)

    if fmt == "json":
        import json
        import sys

        output = [
            {
                "revision": w.revision,
                "file": w.file,
                "code": w.code,
                "pattern": w.pattern,
                "severity": w.severity,
                "message": w.message,
                "line": w.line,
            }
            for w in warnings
        ]
        sys.stdout.write(json.dumps(output, indent=2) + "\n")
        has_errors = any(w.severity == "error" for w in warnings)
        has_warns = any(w.severity == "warning" for w in warnings)
        if has_errors or (strict and has_warns):
            raise typer.Exit(2)
        if has_warns:
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
