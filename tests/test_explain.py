"""Tests for mrt explain command."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pytest_mrt.cli import app

runner = CliRunner()

SAMPLE_MIGRATION = """\
\"\"\"add email column\"\"\"
revision = 'abc123'
down_revision = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('users', sa.Column('email', sa.String(256), nullable=True))


def downgrade():
    op.drop_column('users', 'email')
"""


def test_explain_missing_file():
    result = runner.invoke(app, ["explain", "nonexistent_file.py"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "No such" in result.output


def test_explain_missing_anthropic(tmp_path, monkeypatch):
    """Without anthropic installed, a clear error message is shown."""
    p = tmp_path / "0001_add_email.py"
    p.write_text(SAMPLE_MIGRATION)

    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    result = runner.invoke(app, ["explain", str(p)])
    assert result.exit_code == 1
    assert "pip install" in result.output


def test_explain_no_api_key(tmp_path, monkeypatch):
    """With anthropic installed but no API key, a clear error is shown."""
    pytest.importorskip("anthropic", reason="anthropic not installed")

    p = tmp_path / "0001_add_email.py"
    p.write_text(SAMPLE_MIGRATION)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    import anthropic

    def raise_auth(*args, **kwargs):
        raise anthropic.AuthenticationError(
            message="invalid x-api-key",
            response=None,
            body=None,
        )

    monkeypatch.setattr(anthropic.Anthropic, "messages", property(raise_auth), raising=False)

    result = runner.invoke(app, ["explain", str(p)])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output or "failed" in result.output.lower()


def test_explain_happy_path(tmp_path, monkeypatch):
    """With a mocked anthropic client, explain returns the AI response."""
    pytest.importorskip("anthropic", reason="anthropic not installed")

    p = tmp_path / "0001_add_email.py"
    p.write_text(SAMPLE_MIGRATION)

    from unittest.mock import MagicMock

    import anthropic

    fake_message = MagicMock()
    fake_message.content = [MagicMock(text="This migration adds an email column.")]

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    monkeypatch.setattr(anthropic, "Anthropic", lambda: fake_client)

    result = runner.invoke(app, ["explain", str(p)])
    assert result.exit_code == 0
    assert "email column" in result.output
