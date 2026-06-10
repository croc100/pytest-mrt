from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()


def fix(
    migration_file: str | None = typer.Argument(
        default=None, help="Path to a migration .py file. Omit to batch-fix all migrations."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write fixes to file(s). Required for batch mode."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview batch fixes without writing (use with --apply)."
    ),
    directory: str | None = typer.Option(
        None, "--dir", "-d", help="Directory to scan in batch mode (auto-detected if omitted)."
    ),
) -> None:
    """
    Auto-generate missing reverse operations for an Alembic or Django migration.

    For Alembic migrations: generates a missing or stub downgrade() function.
    For Django migrations: adds reverse_sql / reverse_code to operations that
    lack them (RunSQL, RunPython).

    Single-file mode: mrt fix <file> [--apply]
    Batch mode:       mrt fix --apply [--dry-run] [--dir <path>]
    """
    if migration_file is None:
        if not apply:
            console.print("[red]Error: batch mode requires --apply. Use: mrt fix --apply[/red]")
            console.print("[dim]To preview without writing: mrt fix --apply --dry-run[/dim]")
            raise typer.Exit(1)
        _fix_batch(directory, dry_run=dry_run)
        return

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

    if fix_suggestion.unsupported_ops and not fix_suggestion.patches:
        ops = ", ".join(sorted(set(fix_suggestion.unsupported_ops)))
        console.print(
            f"[yellow]mrt fix cannot auto-fix this migration.[/yellow]\n"
            f"Operation(s) found: [bold]{ops}[/bold]\n\n"
            "These operations must be fixed manually:\n"
            "  - AddField / AlterField: add server_default or handle nullable migration\n"
            "  - RenameField / RenameModel: verify old_name is correct and reversible\n\n"
            "Run [bold]mrt check[/bold] to see the specific warnings."
        )
        raise typer.Exit(1)

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


# ─────────────────────────────────────────────────────────────
# Batch mode
# ─────────────────────────────────────────────────────────────


def _find_migration_dir(base: Path) -> Path | None:
    candidates = [
        base / "migrations",
        base / "alembic" / "versions",
        base / "versions",
    ]
    for c in candidates:
        if c.is_dir() and list(c.glob("*.py")):
            return c
    return None


def _fix_batch(directory: str | None, *, dry_run: bool) -> None:
    from ..adapters.django_fixer import (
        apply_django_fix,
        generate_django_fix,
        is_django_migration,
    )
    from ..core.fixer import apply_fix, generate_fix

    if directory:
        scan_dir = Path(directory)
    else:
        scan_dir = _find_migration_dir(Path.cwd())

    if scan_dir is None or not scan_dir.is_dir():
        console.print(
            "[red]Error: could not find a migrations directory. Use --dir to specify.[/red]"
        )
        raise typer.Exit(1)

    files = sorted(scan_dir.rglob("*.py"))
    if not files:
        console.print(f"[yellow]No .py files found in {scan_dir}[/yellow]")
        raise typer.Exit(0)

    label = "[dim](dry-run)[/dim] " if dry_run else ""
    console.print(f"[dim]Scanning {len(files)} file(s) in {scan_dir} …[/dim]")

    fixed = 0
    skipped = 0
    failed = 0

    for f in files:
        if f.name.startswith("__"):
            continue
        try:
            if is_django_migration(f):
                django_suggestion = generate_django_fix(str(f))
                if django_suggestion is None or (
                    django_suggestion.unsupported_ops and not django_suggestion.patches
                ):
                    skipped += 1
                    continue
                console.print(f"  {label}[cyan]{f.name}[/cyan] — {django_suggestion.issue}")
                if not dry_run:
                    apply_django_fix(str(f), django_suggestion)
                fixed += 1
            else:
                alembic_suggestion = generate_fix(str(f))
                if alembic_suggestion is None:
                    skipped += 1
                    continue
                console.print(
                    f"  {label}[cyan]{f.name}[/cyan] — {alembic_suggestion.issue}"
                    f" (confidence: {alembic_suggestion.confidence})"
                )
                if not dry_run:
                    apply_fix(str(f), alembic_suggestion)
                fixed += 1
        except Exception as e:
            console.print(f"  [red]✗ {f.name}: {e}[/red]")
            failed += 1

    console.print()
    if dry_run:
        console.print(
            f"[dim]Dry-run complete: {fixed} fixable, {skipped} clean, {failed} error(s).[/dim]"
        )
        console.print("[dim]Run without --dry-run to apply.[/dim]")
    else:
        console.print(
            f"[green]✓ Done: {fixed} fixed, {skipped} already clean, {failed} error(s).[/green]"
        )

    if failed:
        raise typer.Exit(1)
