from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from . import __version__
from .adapters.django_detector import analyze_django_migrations, is_django_migration
from .config import DEFAULT_EXPLAIN_MODEL
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
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors (exit 2)"),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table | json"),
) -> None:
    """Statically analyze migrations for rollback risk patterns (Alembic and Django)."""
    # Auto-detect Django vs Alembic
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


# ──────────────────────────────────────────────
# mrt drift
# ──────────────────────────────────────────────


@app.command("drift")
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
    from .core.drift import compare_schema, describe_diff, load_metadata
    from .core.runner import MigrationRunner

    # Load metadata
    try:
        target_metadata = load_metadata(metadata)
    except (ValueError, ImportError, AttributeError) as exc:
        console.print(f"[red]Error loading metadata:[/red] {exc}")
        raise typer.Exit(1)

    # Build runner (needs alembic.ini + db_url)
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


# ──────────────────────────────────────────────
# mrt init
# ──────────────────────────────────────────────


def _detect_django_project() -> tuple[bool, str | None]:
    """
    Returns (is_django, settings_module).
    Detects Django by: manage.py presence + DJANGO_SETTINGS_MODULE env var.
    """
    import os

    has_manage = Path("manage.py").exists()
    env_settings = os.environ.get("DJANGO_SETTINGS_MODULE")

    if has_manage:
        return True, env_settings
    return False, None


@app.command("init")
def init() -> None:
    """
    Scaffold conftest.py and a test file for your project.

    Auto-detects Alembic or Django project type.
    """
    # ── Detect project type ───────────────────────────────────────────
    is_django, django_settings = _detect_django_project()

    # Find alembic.ini (only relevant for Alembic projects)
    ini_candidates = ["alembic.ini", "alembic/alembic.ini", "migrations/alembic.ini"]
    found_ini = next((p for p in ini_candidates if Path(p).exists()), None)

    if is_django and not found_ini:
        console.print("[cyan]Detected: Django project[/cyan]")
        return _init_django(django_settings)

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
        f"import os\n"
        f"from pytest_mrt import MRTConfig\n\n\n"
        f"def pytest_configure(config):\n"
        f"    config._mrt_config = MRTConfig(\n"
        f'        alembic_ini="{alembic_ini}",\n'
        f"        db_url={db_url},\n"
        f'        # skip={{"revision_id": "Reason this is a known issue"}},\n'
        f"    )\n"
    )


def _append_conftest(path: Path, alembic_ini: str, db_url: str) -> None:
    existing = path.read_text()
    addition = (
        f"\n\n# Added by mrt init\n"
        f"from pytest_mrt import MRTConfig\n\n\n"
        f"def pytest_configure(config):\n"
        f"    config._mrt_config = MRTConfig(\n"
        f'        alembic_ini="{alembic_ini}",\n'
        f"        db_url={db_url},\n"
        f"    )\n"
    )
    path.write_text(existing + addition)
    console.print(f"[green]✓[/green] Updated [bold]{path}[/bold]")


def _init_django(detected_settings: str | None) -> None:
    """Interactive init for Django projects."""
    # Resolve settings module
    if detected_settings:
        console.print(f"[dim]DJANGO_SETTINGS_MODULE={detected_settings}[/dim]")
        settings = typer.prompt("Django settings module", default=detected_settings)
    else:
        console.print("[yellow]Tip:[/yellow] Set DJANGO_SETTINGS_MODULE or provide it below.")
        settings = typer.prompt("Django settings module (e.g. myproject.settings_test)")

    db_url = typer.prompt(
        "Test database URL",
        default='os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db")',
    )

    test_dir = "tests" if Path("tests").exists() else "."
    conftest_path = Path(test_dir) / "conftest.py"

    django_conftest = (
        f"import os\n"
        f"from pytest_mrt import MRTConfig\n\n\n"
        f"def pytest_configure(config):\n"
        f"    config._mrt_config = MRTConfig(\n"
        f"        db_url={db_url},\n"
        f'        django_settings="{settings}",\n'
        f'        # django_apps=["myapp", "otherapp"],  # restrict to specific apps\n'
        f"    )\n"
    )

    django_test = (
        '"""Migration rollback tests — powered by pytest-mrt"""\n\n\n'
        "def test_all_migrations_are_reversible(mrt):\n"
        '    """Check every migration can be safely rolled back."""\n'
        "    mrt.assert_all_reversible()\n"
    )

    if conftest_path.exists():
        overwrite = typer.confirm(f"{conftest_path} already exists. Add MRTConfig?", default=False)
        if not overwrite:
            console.print("[dim]Skipping conftest.py[/dim]")
        else:
            existing = conftest_path.read_text()
            conftest_path.write_text(existing + "\n\n# Added by mrt init\n" + django_conftest)
            console.print(f"[green]✓[/green] Updated [bold]{conftest_path}[/bold]")
    else:
        conftest_path.write_text(django_conftest)
        console.print(f"[green]✓[/green] Created [bold]{conftest_path}[/bold]")

    test_path = Path(test_dir) / "test_migrations.py"
    if not test_path.exists():
        test_path.write_text(django_test)
        console.print(f"[green]✓[/green] Created [bold]{test_path}[/bold]")

    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  [cyan]pytest {test_dir}/test_migrations.py -s[/cyan]")
    console.print()
    console.print("[dim]Static analysis (no DB needed):[/dim]")
    console.print("  [cyan]mrt check yourapp/migrations/[/cyan]")


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
    from .core.fixer import apply_fix, generate_fix

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
    console.print(
        f"  Open it in your browser: [link=file://{Path(output).absolute()}]{Path(output).absolute()}[/link]"
    )


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
        raise typer.Exit(1)
