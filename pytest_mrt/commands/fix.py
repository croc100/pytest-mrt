from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()


def fix(
    migration_file: str = typer.Argument(help="Path to the migration .py file"),
    apply: bool = typer.Option(False, "--apply", help="Write the fix to the file"),
) -> None:
    """
    Auto-generate missing reverse operations for an Alembic or Django migration.

    For Alembic migrations: generates a missing or stub downgrade() function.
    For Django migrations: adds reverse_sql / reverse_code to operations that
    lack them (RunSQL, RunPython).

    Shows the suggested changes. Use --apply to write them to the file.
    """
    path = Path(migration_file)
    if not path.exists():
        console.print(f"[red]File not found: {migration_file}[/red]")
        raise typer.Exit(1)

    from ..adapters.django_fixer import is_django_migration

    if is_django_migration(path):
        _fix_django(migration_file, apply)
    else:
        _fix_alembic(migration_file, apply)


# ─────────────────────────────────────────────────────────────
# Alembic
# ─────────────────────────────────────────────────────────────


def _fix_alembic(migration_file: str, apply: bool) -> None:
    from ..core.fixer import apply_fix, generate_fix

    fix_suggestion = generate_fix(migration_file)

    if fix_suggestion is None:
        console.print("[green]✓ No fix needed — downgrade() looks correct.[/green]")
        raise typer.Exit(0)

    console.print()
    console.print(
        f"[bold]{fix_suggestion.file}[/bold]  [dim]{fix_suggestion.revision}[/dim]"
    )
    console.print(f"[yellow]Issue:[/yellow] {fix_suggestion.issue}")
    console.print()

    if fix_suggestion.warning:
        console.print(Panel(f"[yellow]{fix_suggestion.warning}[/yellow]", title="⚠  Note"))
        console.print()

    confidence_colors = {"high": "green", "medium": "yellow", "low": "red"}
    c = confidence_colors[fix_suggestion.confidence]
    console.print(f"Confidence: [{c}]{fix_suggestion.confidence}[/{c}]")
    console.print()

    console.print("[dim]Suggested downgrade():[/dim]")
    suggested = f"def downgrade() -> None:\n{fix_suggestion.suggested_downgrade}"
    console.print(Syntax(suggested, "python", theme="monokai", line_numbers=False))

    if not apply:
        console.print()
        console.print("[dim]Run with [bold]--apply[/bold] to write this fix to the file.[/dim]")
        raise typer.Exit(0)

    apply_fix(migration_file, fix_suggestion)
    console.print()
    console.print(f"[green]✓ Fix applied to {migration_file}[/green]")


# ─────────────────────────────────────────────────────────────
# Django
# ─────────────────────────────────────────────────────────────


def _fix_django(migration_file: str, apply: bool) -> None:
    from ..adapters.django_fixer import apply_django_fix, generate_django_fix

    try:
        fix_suggestion = generate_django_fix(migration_file)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if fix_suggestion is None:
        console.print(
            "[green]✓ No fix needed — all Django operations have reverse implementations.[/green]"
        )
        raise typer.Exit(0)

    console.print()
    console.print(
        f"[bold]{fix_suggestion.file}[/bold]  [dim]{fix_suggestion.migration_name}[/dim]"
        "  [cyan][Django][/cyan]"
    )
    console.print(f"[yellow]Issue:[/yellow] {fix_suggestion.issue}")
    console.print()

    # Table of individual patches
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("Line", style="dim", width=6)
    table.add_column("Operation")
    table.add_column("Fix")
    table.add_column("Confidence")

    confidence_colors = {"high": "green", "medium": "yellow", "low": "red"}
    for p in fix_suggestion.patches:
        c = confidence_colors[p.confidence]
        fix_label = (
            "add reverse_sql=migrations.RunSQL.noop"
            if p.op_name == "RunSQL"
            else "add reverse_code=migrations.RunPython.noop"
        )
        table.add_row(
            str(p.line),
            p.op_name,
            fix_label,
            f"[{c}]{p.confidence}[/{c}]",
        )
    console.print(table)
    console.print()

    # Show diff for each patch
    for p in fix_suggestion.patches:
        console.print(f"[dim]Line {p.line} — {p.op_name}:[/dim]")
        console.print("[red]- " + p.original_snippet.replace("\n", "\n- ") + "[/red]")
        console.print("[green]+ " + p.patched_snippet.replace("\n", "\n+ ") + "[/green]")
        console.print()

    if fix_suggestion.warning:
        console.print(Panel(f"[yellow]{fix_suggestion.warning}[/yellow]", title="⚠  Note"))
        console.print()

    if not apply:
        console.print("[dim]Run with [bold]--apply[/bold] to write this fix to the file.[/dim]")
        raise typer.Exit(0)

    apply_django_fix(migration_file, fix_suggestion)
    console.print(f"[green]✓ Fix applied to {migration_file}[/green]")
