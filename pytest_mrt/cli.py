import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box

from . import __version__
from .core.detector import analyze_migrations

app = typer.Typer(
    name="mrt",
    help="MRT — Migration Rollback Tester",
    no_args_is_help=True,
)
console = Console()


def _severity_color(s: str) -> str:
    return "red" if s == "error" else "yellow"


# ──────────────────────────────────────────────
# mrt version
# ──────────────────────────────────────────────

@app.command("version")
def version_cmd() -> None:
    """Show version."""
    console.print(f"pytest-mrt {__version__}")


# ──────────────────────────────────────────────
# mrt check
# ──────────────────────────────────────────────

@app.command("check")
def check(
    versions_dir: str = typer.Argument(help="Path to Alembic versions directory"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 on warnings too"),
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
    elif warns and strict:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] (--strict mode)")
        raise typer.Exit(1)
    else:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] — review before deploying")
        raise typer.Exit(0)


# ──────────────────────────────────────────────
# mrt fix
# ──────────────────────────────────────────────

@app.command("fix")
def fix(
    migration_file: str = typer.Argument(help="Path to the migration .py file"),
    apply: bool = typer.Option(False, "--apply", help="Write the fix to the file"),
) -> None:
    """
    Auto-generate a missing or broken downgrade() function.

    Shows a diff of the suggested fix. Use --apply to write it to the file.
    """
    from .core.fixer import generate_fix, apply_fix

    if not Path(migration_file).exists():
        console.print(f"[red]File not found: {migration_file}[/red]")
        raise typer.Exit(1)

    fix_suggestion = generate_fix(migration_file)

    if fix_suggestion is None:
        console.print("[green]✓ No fix needed — downgrade() looks correct.[/green]")
        raise typer.Exit(0)

    console.print()
    console.print(f"[bold]{fix_suggestion.file}[/bold]  [dim]{fix_suggestion.revision}[/dim]")
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


# ──────────────────────────────────────────────
# mrt report
# ──────────────────────────────────────────────

@app.command("report")
def report(
    versions_dir: str = typer.Argument(help="Path to Alembic versions directory"),
    output: str = typer.Option("migration_report.html", "--output", "-o", help="Output file path"),
) -> None:
    """Generate an HTML safety report of your entire migration history."""
    from .core.html_report import generate_html_report

    warnings = analyze_migrations(versions_dir)
    html = generate_html_report(versions_dir, warnings)

    Path(output).write_text(html)
    console.print(f"[green]✓ Report saved to [bold]{output}[/bold][/green]")
    console.print(f"  Open it in your browser: [link=file://{Path(output).absolute()}]{Path(output).absolute()}[/link]")


# ──────────────────────────────────────────────
# mrt explain
# ──────────────────────────────────────────────

@app.command("explain")
def explain(
    migration_file: str = typer.Argument(help="Path to the migration .py file"),
) -> None:
    """
    Explain what a migration does in plain English using AI.

    Requires: pip install pytest-mrt[ai]
    Requires: ANTHROPIC_API_KEY environment variable
    """
    try:
        import anthropic
    except ImportError:
        console.print(Panel(
            "[red]AI support not installed.[/red]\n\n"
            "Run: [bold]pip install pytest-mrt\\[ai][/bold]",
            title="Missing dependency",
        ))
        raise typer.Exit(1)

    path = Path(migration_file)
    if not path.exists():
        console.print(f"[red]File not found: {migration_file}[/red]")
        raise typer.Exit(1)

    source = path.read_text()

    console.print(f"[dim]Analyzing {path.name}...[/dim]")

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""Explain this Alembic database migration file in plain English for someone who may not be deeply familiar with SQL or database migrations.

Cover:
1. What changes this migration makes to the database (in simple terms)
2. What happens to existing data
3. Whether the rollback (downgrade) correctly undoes the changes
4. Any risks or things to watch out for

Be concise. Use bullet points. Avoid jargon where possible.

Migration file ({path.name}):
```python
{source}
```""",
            }]
        )

        explanation = message.content[0].text
        console.print()
        console.print(Panel(explanation, title=f"[bold]{path.name}[/bold]", border_style="blue"))

    except Exception as e:
        console.print(f"[red]AI request failed: {e}[/red]")
        console.print("[dim]Make sure ANTHROPIC_API_KEY is set.[/dim]")
        raise typer.Exit(1)
