"""
Built-in default tests for pytest-mrt.

These are automatically collected when MRTConfig is registered in conftest.py.
To disable auto-collection, add the following to pyproject.toml or pytest.ini:

    [tool.pytest.ini_options]
    mrt_default_tests = "false"

You can also import individual tests explicitly:

    from pytest_mrt.default_tests import test_mrt_upgrade, test_mrt_downgrade_base
"""
from __future__ import annotations

import pytest


def test_mrt_single_head(mrt) -> None:
    """Exactly one head revision exists in the migration chain."""
    if mrt._django_mode:
        pytest.skip("single-head check not applicable to Django mode")
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(mrt._runner.alembic_cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Expected a single head revision, found {len(heads)}: {heads}.\n"
        "Run `alembic merge heads` to create a merge migration."
    )


def test_mrt_upgrade(mrt) -> None:
    """Migration chain upgrades to head without error."""
    if mrt._django_mode:
        pytest.skip("use test_mrt_all_reversible for Django mode")
    mrt.upgrade("head")


def test_mrt_downgrade_base(mrt) -> None:
    """Migration chain downgrades to base without error."""
    if mrt._django_mode:
        pytest.skip("use test_mrt_all_reversible for Django mode")
    mrt.upgrade("head")
    mrt._runner.downgrade_base()
    try:
        mrt.upgrade("head")  # restore to head so subsequent tests start clean
    except Exception as exc:
        pytest.fail(
            f"Migration chain failed to re-upgrade to head after downgrade_base: {exc}\n"
            "DB state is now at 'base'. Fix the upgrade() failure before continuing."
        )


def test_mrt_static_no_errors(mrt) -> None:
    """No static analysis errors found in migration files."""
    mrt.assert_no_static_errors()


def test_mrt_schema_matches_models(mrt) -> None:
    """Model definitions match the migration state (no schema drift).

    Requires ``MRTConfig(target_metadata='myapp.models:Base')`` to be set.
    Skipped automatically when target_metadata is not configured.
    """
    if mrt._config.target_metadata is None:
        pytest.skip(
            "target_metadata not configured — skipping schema drift check.\n"
            "Set MRTConfig(target_metadata='myapp.models:Base') to enable."
        )
    # Ensure migrations are applied before comparing schema.
    # This makes the test safe to run in isolation (e.g. pytest -k test_mrt_schema_matches_models).
    if not mrt._django_mode:
        mrt.upgrade("head")
    mrt.assert_schema_matches()
