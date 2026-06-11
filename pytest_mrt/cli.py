import typer
from rich.console import Console

from . import __version__
from .commands.check import check
from .commands.drift_cmd import drift
from .commands.init import init
from .commands.output import explain, report

app = typer.Typer(
    name="mrt",
    help="MRT — Migration Rollback Tester",
    no_args_is_help=True,
)
_console = Console()


@app.command("version")
def version_cmd() -> None:
    """Show version."""
    _console.print(f"pytest-mrt {__version__}")


app.command("check")(check)
app.command("drift")(drift)
app.command("init")(init)
app.command("report")(report)
app.command("explain")(explain)
