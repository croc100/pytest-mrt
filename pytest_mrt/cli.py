import sys
import typer
from rich.console import Console
from rich.table import Table
from rich import box

from .core.detector import RiskWarning, analyze_migrations

app = typer.Typer(help="MRT — Migration Rollback Tester")
console = Console()


def _severity_color(s: str) -> str:
    return "red" if s == "error" else "yellow"


@app.command()
def check(
    versions_dir: str = typer.Argument(help="Path to Alembic versions directory"),
    fail_on_warning: bool = typer.Option(False, "--strict", help="Exit 1 on warnings too"),
) -> None:
    """Statically analyze migrations for rollback risk patterns."""
    warnings = analyze_migrations(versions_dir)

    if not warnings:
        console.print("[green]✓ No rollback risks detected.[/green]")
        raise typer.Exit(0)

    errors = [w for w in warnings if w.severity == "error"]
    warns = [w for w in warnings if w.severity == "warning"]

    table = Table(box=box.ROUNDED, title="Rollback Risk Analysis", show_lines=True)
    table.add_column("Revision", style="cyan", no_wrap=True)
    table.add_column("Pattern", no_wrap=True)
    table.add_column("Sev", no_wrap=True)
    table.add_column("Message")

    for w in warnings:
        c = _severity_color(w.severity)
        table.add_row(w.revision, w.pattern, f"[{c}]{w.severity}[/{c}]", w.message)

    console.print(table)
    console.print()

    if errors:
        console.print(f"[red]{len(errors)} error(s)[/red], [yellow]{len(warns)} warning(s)[/yellow]")
        raise typer.Exit(1)
    elif warns and fail_on_warning:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] (--strict mode)")
        raise typer.Exit(1)
    else:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] — review before deploying")
        raise typer.Exit(0)
