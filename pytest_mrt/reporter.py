from __future__ import annotations
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .core.verifier import RevisionResult

console = Console()


def print_revision_result(result: RevisionResult) -> None:
    if result.passed:
        console.print(f"  [green]✓[/green]  [bold]{result.revision}[/bold]  [dim]reversible[/dim]")
    else:
        console.print(f"  [red]✗[/red]  [bold]{result.revision}[/bold]  [red]data loss detected[/red]")
        for f in result.failures:
            console.print(f"     [dim]└─[/dim] [red]{f}[/red]")


def print_check_all_summary(results: list[RevisionResult]) -> None:
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    console.print()
    console.rule("[bold]MRT — Migration Rollback Test[/bold]", style="dim")
    console.print()

    for result in results:
        print_revision_result(result)

    console.print()

    if not failed:
        console.print(Panel(
            f"[green]All {len(results)} migration(s) are safely reversible.[/green]",
            border_style="green",
        ))
    else:
        lines = Text()
        lines.append(f"{len(failed)} migration(s) will cause data loss on rollback.\n\n", style="red bold")
        for r in failed:
            lines.append(f"  {r.revision}\n", style="red")
            for f in r.failures:
                lines.append(f"    └─ {f}\n", style="dim")
        console.print(Panel(lines, border_style="red", title="[red]Rollback Unsafe[/red]"))

    console.print()


def print_static_check_header(versions_dir: str) -> None:
    console.print()
    console.rule(f"[bold]MRT static analysis[/bold]  [dim]{versions_dir}[/dim]", style="dim")
    console.print()
