import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box

from . import __version__
from .core.detector import analyze_migrations
from .adapters.django_detector import analyze_django_migrations, is_django_migration

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
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table | json"),
) -> None:
    """Statically analyze migrations for rollback risk patterns (Alembic and Django)."""
    # Auto-detect Django vs Alembic
    from pathlib import Path as _Path
    sample_files = list(_Path(versions_dir).rglob("*.py"))[:5]
    is_django = any(is_django_migration(p) for p in sample_files)

    if is_django:
        console.print("[dim]Detected: Django migrations[/dim]")
        warnings = analyze_django_migrations(versions_dir)
    else:
        warnings = analyze_migrations(versions_dir)

    if fmt == "json":
        import json, sys
        output = [
            {"revision": w.revision, "file": w.file, "pattern": w.pattern,
             "severity": w.severity, "message": w.message, "line": w.line}
            for w in warnings
        ]
        sys.stdout.write(json.dumps(output, indent=2) + "\n")
        has_errors = any(w.severity == "error" for w in warnings)
        raise typer.Exit(1 if has_errors or (strict and warnings) else 0)

    if not warnings:
        console.print("[green]✓ No rollback risks detected.[/green]")
        raise typer.Exit(0)

    errors = [w for w in warnings if w.severity == "error"]
    warns = [w for w in warnings if w.severity == "warning"]

    table = Table(box=box.ROUNDED, title="Rollback Risk Analysis", show_lines=True)
    table.add_column("Revision", style="cyan", no_wrap=True)
    table.add_column("Pattern", no_wrap=True)
    table.add_column("Sev", no_wrap=True)
    table.add_column("Line", no_wrap=True, justify="right")
    table.add_column("Message")

    for w in warnings:
        c = _severity_color(w.severity)
        line_str = str(w.line) if w.line is not None else ""
        table.add_row(w.revision, w.pattern, f"[{c}]{w.severity}[/{c}]", line_str, w.message)

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
# mrt init
# ──────────────────────────────────────────────

@app.command("init")
def init() -> None:
    """
    Scaffold conftest.py and a test file for your project.

    Auto-detects alembic.ini location.
    """
    import os

    # Find alembic.ini
    ini_candidates = ["alembic.ini", "alembic/alembic.ini", "migrations/alembic.ini"]
    found_ini = next((p for p in ini_candidates if Path(p).exists()), None)

    if found_ini:
        console.print(f"[green]✓[/green] Found [bold]{found_ini}[/bold]")
    else:
        found_ini = typer.prompt("Path to alembic.ini", default="alembic.ini")

    # Ask for DB URL
    db_url = typer.prompt(
        "Test database URL",
        default='os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db")',
    )

    # Detect test directory
    test_dir = "tests" if Path("tests").exists() else "."

    # Write conftest.py
    conftest_path = Path(test_dir) / "conftest.py"
    if conftest_path.exists():
        overwrite = typer.confirm(f"{conftest_path} already exists. Add MRTConfig?", default=False)
        if not overwrite:
            console.print("[dim]Skipping conftest.py[/dim]")
        else:
            _append_conftest(conftest_path, found_ini, db_url)
    else:
        _write_conftest(conftest_path, found_ini, db_url)
        console.print(f"[green]✓[/green] Created [bold]{conftest_path}[/bold]")

    # Write test file
    test_path = Path(test_dir) / "test_migrations.py"
    if not test_path.exists():
        test_path.write_text(
            '"""Migration rollback tests — powered by pytest-mrt"""\n\n\n'
            "def test_all_migrations_are_reversible(mrt):\n"
            '    """Check every migration can be safely rolled back."""\n'
            "    mrt.assert_all_reversible()\n"
        )
        console.print(f"[green]✓[/green] Created [bold]{test_path}[/bold]")

    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  [cyan]pytest {test_dir}/test_migrations.py -s[/cyan]")


def _write_conftest(path: Path, alembic_ini: str, db_url: str) -> None:
    path.write_text(
        f'import os\n'
        f'from pytest_mrt import MRTConfig\n\n\n'
        f'def pytest_configure(config):\n'
        f'    config._mrt_config = MRTConfig(\n'
        f'        alembic_ini="{alembic_ini}",\n'
        f'        db_url={db_url},\n'
        f'        # skip={{"revision_id": "Reason this is a known issue"}},\n'
        f'    )\n'
    )


def _append_conftest(path: Path, alembic_ini: str, db_url: str) -> None:
    existing = path.read_text()
    addition = (
        f'\n\n# Added by mrt init\n'
        f'from pytest_mrt import MRTConfig\n\n\n'
        f'def pytest_configure(config):\n'
        f'    config._mrt_config = MRTConfig(\n'
        f'        alembic_ini="{alembic_ini}",\n'
        f'        db_url={db_url},\n'
        f'    )\n'
    )
    path.write_text(existing + addition)
    console.print(f"[green]✓[/green] Updated [bold]{path}[/bold]")


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
