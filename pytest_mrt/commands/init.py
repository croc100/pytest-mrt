from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def _detect_django_project() -> tuple[bool, str | None]:
    has_manage = Path("manage.py").exists()
    env_settings = os.environ.get("DJANGO_SETTINGS_MODULE")
    if has_manage:
        return True, env_settings
    return False, None


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


def init() -> None:
    """
    Scaffold conftest.py and a test file for your project.

    Auto-detects Alembic or Django project type.
    """
    is_django, django_settings = _detect_django_project()

    ini_candidates = ["alembic.ini", "alembic/alembic.ini", "migrations/alembic.ini"]
    found_ini = next((p for p in ini_candidates if Path(p).exists()), None)

    if is_django and not found_ini:
        console.print("[cyan]Detected: Django project[/cyan]")
        return _init_django(django_settings)

    if found_ini:
        console.print(f"[green]✓[/green] Found [bold]{found_ini}[/bold]")
    else:
        found_ini = typer.prompt("Path to alembic.ini", default="alembic.ini")

    db_url = typer.prompt(
        "Test database URL",
        default='os.environ.get("TEST_DATABASE_URL", "sqlite:///test.db")',
    )

    test_dir = "tests" if Path("tests").exists() else "."

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
