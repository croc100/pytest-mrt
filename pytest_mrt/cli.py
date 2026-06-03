import typer
from rich.console import Console
from rich.table import Table
from .core.detector import analyze_migrations

app = typer.Typer(help="MRT — Migration Rollback Tester")
console = Console()


@app.command()
def check(
    versions_dir: str = typer.Argument("migrations/versions", help="Path to Alembic versions directory"),
):
    """Statically analyze migrations for rollback risk patterns."""
    warnings = analyze_migrations(versions_dir)

    if not warnings:
        console.print("[green]✓ No rollback risks detected.[/green]")
        raise typer.Exit(0)

    table = Table(title="Rollback Risk Analysis")
    table.add_column("Revision", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Pattern")
    table.add_column("Severity")
    table.add_column("Message")

    has_error = False
    for w in warnings:
        color = "red" if w.severity == "error" else "yellow"
        table.add_row(w.revision, w.file, w.pattern, f"[{color}]{w.severity}[/{color}]", w.message)
        if w.severity == "error":
            has_error = True

    console.print(table)
    raise typer.Exit(1 if has_error else 0)
