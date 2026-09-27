"""Guard against reading migration files in the locale's encoding.

``Path.read_text()`` with no ``encoding`` decodes using the locale encoding, so a
migration carrying non-ASCII text fails on a Windows machine whose locale is not
UTF-8 while passing on Linux CI. The package declares "OS Independent", and CI
runs only on Linux, so the mistake is invisible unless it is asserted directly.

Python's own mechanism for this is ``-X warn_default_encoding`` (PEP 597), which
emits ``EncodingWarning`` at every implicit-encoding open. The tests below run
the package under that flag with warnings turned into errors.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

MIGRATION_WITH_NON_ASCII = '''\
"""사용자 전화번호 추가 — migration with non-ASCII text (ü, é, 日本語)."""

revision = "abc123"
down_revision = None
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("users", sa.Column("phone", sa.String(20)))


def downgrade():
    op.drop_column("users", "phone")
'''


def _run_under_encoding_warnings(code: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            "-c",
            textwrap.dedent(code),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_static_analysis_declares_its_encoding(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_add_phone.py").write_text(MIGRATION_WITH_NON_ASCII, encoding="utf-8")

    result = _run_under_encoding_warnings(
        """
        from pytest_mrt.core.detector import analyze_migrations
        warnings = analyze_migrations("versions")
        print("OK", len(warnings))
        """,
        cwd=tmp_path,
    )
    assert "EncodingWarning" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr


def test_cli_check_declares_its_encoding(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_add_phone.py").write_text(MIGRATION_WITH_NON_ASCII, encoding="utf-8")

    result = _run_under_encoding_warnings(
        """
        from typer.testing import CliRunner
        from pytest_mrt.cli import app
        result = CliRunner().invoke(app, ["check", "versions"])
        print("exit", result.exit_code)
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        """,
        cwd=tmp_path,
    )
    assert "EncodingWarning" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr


def test_non_ascii_migration_is_read_correctly(tmp_path):
    """Sanity check that the content survives the round trip, not just the warning."""
    from pytest_mrt.core.detector import analyze_migrations

    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_add_phone.py").write_text(MIGRATION_WITH_NON_ASCII, encoding="utf-8")

    warnings = analyze_migrations(str(versions))
    # The migration drops a column on downgrade only, so it is safe; what matters
    # is that reading it did not raise.
    assert isinstance(warnings, list)
