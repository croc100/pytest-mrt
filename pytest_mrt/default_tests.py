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
    """Exactly one head revision exists in the migration chain.

    Multiple heads indicate an unresolved branch — usually a merge conflict
    that was committed without running ``alembic merge heads`` (Alembic) or
    ``manage.py makemigrations --merge`` (Django).
    """
    if mrt._django_mode:
        executor = mrt._django_verifier.runner._executor()
        leaves = executor.loader.graph.leaf_nodes()
        # Group by app so the error message is actionable
        from collections import defaultdict

        by_app: dict[str, list[str]] = defaultdict(list)
        for app_label, name in leaves:
            by_app[app_label].append(name)
        branched = {app: names for app, names in by_app.items() if len(names) > 1}
        assert not branched, (
            f"Migration graph has multiple leaf nodes in {len(branched)} app(s):\n"
            + "\n".join(f"  {app}: {names}" for app, names in branched.items())
            + "\nRun `python manage.py makemigrations --merge` to create a merge migration."
        )
        return

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


def test_mrt_up_down_consistency(mrt) -> None:
    """Every revision can be individually upgraded and rolled back without data loss.

    For each revision in the chain (oldest → newest):
      1. Upgrade to that revision
      2. Seed realistic data into the affected tables
      3. Downgrade one step
      4. Verify schema is fully restored
      5. Verify seeded data survived the round-trip

    Unlike ``test_mrt_downgrade_base`` (which tests the whole chain at once),
    this test pinpoints exactly which revision fails and what data was lost.
    Works for both Alembic and Django modes.
    """
    mrt.assert_all_reversible()


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
