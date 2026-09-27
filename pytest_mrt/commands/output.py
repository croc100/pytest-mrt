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

    Path(output).write_text(html, encoding="utf-8")
    console.print(f"[green]✓ Report saved to [bold]{output}[/bold][/green]")
    console.print(
        f"  Open it in your browser: [link=file://{Path(output).absolute()}]{Path(output).absolute()}[/link]"
    )


def explain(
    migration_file: str = typer.Argument(help="Path to the migration .py file"),
    model: str = typer.Option(DEFAULT_EXPLAIN_MODEL, "--model", "-m", help="Claude model to use"),
) -> None:
    """
    Explain what a migration does in plain English using AI.

    Requires: pip install pytest-mrt[ai]
    Requires: ANTHROPIC_API_KEY environment variable
    """
    path = Path(migration_file)
    if not path.exists():
        console.print(f"[red]File not found: {migration_file}[/red]")
        raise typer.Exit(1)

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

    source = path.read_text(encoding="utf-8")

    console.print(f"[dim]Analyzing {path.name}...[/dim]")

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=16000,
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

        explanation = next((block.text for block in message.content if block.type == "text"), "")
        console.print()
        console.print(Panel(explanation, title=f"[bold]{path.name}[/bold]", border_style="blue"))

    except Exception as e:
        console.print(f"[red]AI request failed: {e}[/red]")
        # Only an auth failure is about the key; saying so for every failure
        # sends people to check an environment variable that is already fine.
        if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError"):
            console.print("[dim]Check that ANTHROPIC_API_KEY is set and valid.[/dim]")
        elif type(e).__name__ == "NotFoundError":
            console.print(f"[dim]Model '{model}' was not found. Override it with --model.[/dim]")
        raise typer.Exit(1) from e
