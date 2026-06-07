from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

console = Console()

_TABLE = "_mrt_backups"


def clean_backups(
    database_url: str = typer.Option(
        ...,
        "--db",
        envvar="DATABASE_URL",
        help="Database URL (SQLAlchemy format, e.g. postgresql://user:pass@host/db)",
    ),
    label: str = typer.Option(
        None,
        "--label",
        help="Remove only this migration label (e.g. 0042_remove_user_phone__user_phone). "
        "Omit to remove all backup data.",
    ),
    list_only: bool = typer.Option(
        False, "--list", "-l", help="List backup labels without deleting."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """
    Remove mrt backup data from the _mrt_backups table.

    Run this after a deployment is confirmed stable and rollback is no longer
    needed.  Without --label, all backup data is removed.

    Examples:
      mrt clean-backups --db postgresql://user:pass@host/db
      mrt clean-backups --db $DATABASE_URL --label 0042__user_phone
      mrt clean-backups --db $DATABASE_URL --list
    """
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        console.print("[red]sqlalchemy is required. pip install sqlalchemy[/red]")
        raise typer.Exit(1)

    engine = create_engine(database_url)

    try:
        with engine.connect() as conn:
            # Check table exists
            try:
                if label:
                    result = conn.execute(
                        text(f"SELECT migration_label, COUNT(*) FROM {_TABLE} WHERE migration_label = :label GROUP BY migration_label"),
                        {"label": label},
                    )
                else:
                    result = conn.execute(
                        text(f"SELECT migration_label, COUNT(*) FROM {_TABLE} GROUP BY migration_label ORDER BY migration_label")
                    )
                rows = result.fetchall()
            except Exception:
                console.print(f"[yellow]Table {_TABLE!r} not found — nothing to clean.[/yellow]")
                raise typer.Exit(0)

            if not rows:
                console.print(f"[green]No backup data found in {_TABLE!r}.[/green]")
                raise typer.Exit(0)

            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            table.add_column("migration_label")
            table.add_column("rows", justify="right")
            total = 0
            for lbl, count in rows:
                table.add_row(lbl, str(count))
                total += count
            console.print(table)
            console.print()

            if list_only:
                raise typer.Exit(0)

            scope = f"label {label!r}" if label else "all labels"
            if not yes:
                confirmed = typer.confirm(f"Delete {total} backup rows ({scope})?")
                if not confirmed:
                    raise typer.Exit(0)

            if label:
                conn.execute(
                    text(f"DELETE FROM {_TABLE} WHERE migration_label = :label"),
                    {"label": label},
                )
            else:
                conn.execute(text(f"DELETE FROM {_TABLE}"))
            conn.commit()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Removed {total} backup rows from {_TABLE!r}.[/green]")
