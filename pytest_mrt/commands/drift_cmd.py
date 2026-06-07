from __future__ import annotations

from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

console = Console()


def drift(
    metadata: str = typer.Argument(
        help="SQLAlchemy metadata import path, e.g. 'myapp.models:Base'"
    ),
    alembic_ini: str = typer.Option("alembic.ini", "--config", "-c", help="Path to alembic.ini"),
    db_url: str = typer.Option("", "--db-url", help="Database URL (overrides alembic.ini)"),
) -> None:
    """Check if SQLAlchemy model definitions match the current migration state.

    Compares the live DB schema (after running all migrations) against the
    SQLAlchemy models you point at. Exits 0 if clean, 1 if drift is found.

    Example:

        mrt drift myapp.models:Base --config alembic.ini --db-url sqlite:///test.db
    """
    from ..core.drift import compare_schema, describe_diff, load_metadata
    from ..core.runner import MigrationRunner

    try:
        target_metadata = load_metadata(metadata)
    except (ValueError, ImportError, AttributeError) as exc:
        console.print(f"[red]Error loading metadata:[/red] {exc}")
        raise typer.Exit(1)

    if not Path(alembic_ini).exists():
        console.print(f"[red]alembic.ini not found:[/red] {alembic_ini}")
        raise typer.Exit(1)

    try:
        runner = MigrationRunner(alembic_ini, db_url)
    except Exception as exc:
        console.print(f"[red]Failed to connect:[/red] {exc}")
        raise typer.Exit(1)

    console.print("[dim]Upgrading to head...[/dim]")
    try:
        runner.upgrade("head")
    except Exception as exc:
        console.print(f"[red]Migration failed:[/red] {exc}")
        raise typer.Exit(1)

    console.print("[dim]Comparing schema...[/dim]")
    diffs = compare_schema(runner.engine, target_metadata)

    if not diffs:
        console.print("[green]✓ No schema drift — models match migrations.[/green]")
        raise typer.Exit(0)

    table = Table(box=box.ROUNDED, title="Schema Drift", show_lines=True)
    table.add_column("#", style="dim", no_wrap=True)
    table.add_column("Difference")

    for i, d in enumerate(diffs, 1):
        table.add_row(str(i), describe_diff(d))

    console.print(table)
    console.print(
        f"\n[red]{len(diffs)} difference(s) found.[/red] Run migrations or update your models."
    )
    raise typer.Exit(1)
