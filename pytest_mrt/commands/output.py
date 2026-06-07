from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ..config import DEFAULT_EXPLAIN_MODEL
from ..core.detector import analyze_migrations

console = Console()


def report(
    versions_dir: str = typer.Argument(help="Path to Alembic versions directory"),
    output: str = typer.Option("migration_report.html", "--output", "-o", help="Output file path"),
) -> None:
    """Generate an HTML safety report of your entire migration history."""
    from ..core.html_report import generate_html_report

    warnings = analyze_migrations(versions_dir)
    html = generate_html_report(versions_dir, warnings)

    Path(output).write_text(html)
    console.print(f"[green]✓ Report saved to [bold]{output}[/bold][/green]")
    console.print(
        f"  Open it in your browser: [link=file://{Path(output).absolute()}]{Path(output).absolute()}[/link]"
    )


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
        console.print(
            Panel(
                "[red]AI support not installed.[/red]\n\n"
                "Run: [bold]pip install pytest-mrt\\[ai][/bold]",
                title="Missing dependency",
            )
        )
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
            model=DEFAULT_EXPLAIN_MODEL,
            max_tokens=1024,
            messages=[
                {
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
                }
            ],
        )

        explanation = message.content[0].text
        console.print()
        console.print(Panel(explanation, title=f"[bold]{path.name}[/bold]", border_style="blue"))

    except Exception as e:
        console.print(f"[red]AI request failed: {e}[/red]")
        console.print("[dim]Make sure ANTHROPIC_API_KEY is set.[/dim]")
