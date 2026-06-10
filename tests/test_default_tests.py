"""Unit tests for default_tests.py — call each injected test function directly."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import pytest_mrt.default_tests as _dt

# Aliases so pytest doesn't collect these as tests
_single_head = _dt.test_mrt_single_head
_upgrade = _dt.test_mrt_upgrade
_downgrade_base = _dt.test_mrt_downgrade_base
_up_down = _dt.test_mrt_up_down_consistency
_static = _dt.test_mrt_static_no_errors
_schema = _dt.test_mrt_schema_matches_models


def _mrt(django_mode=False):
    m = MagicMock(unsafe=True)
    m._django_mode = django_mode
    m._config.target_metadata = None
    return m


def _django_mrt_with_leaves(leaves: list[tuple[str, str]]):
    """Build a mock mrt in Django mode with a given leaf_nodes() list."""
    mrt = _mrt(django_mode=True)
    fake_graph = MagicMock()
    fake_graph.leaf_nodes.return_value = leaves
    fake_loader = MagicMock()
    fake_loader.graph = fake_graph
    fake_executor = MagicMock()
    fake_executor.loader = fake_loader
    mrt._django_verifier.runner._executor.return_value = fake_executor
    return mrt


# ── test_mrt_single_head ─────────────────────────────────────────────────────


def test_single_head_passes_one_head():
    mrt = _mrt()
    fake_script = MagicMock()
    fake_script.get_heads.return_value = ["abc123"]
    with patch("alembic.script.ScriptDirectory") as mock_sd:
        mock_sd.from_config.return_value = fake_script
        _single_head(mrt)


def test_single_head_fails_multiple_heads():
    mrt = _mrt()
    fake_script = MagicMock()
    fake_script.get_heads.return_value = ["abc123", "def456"]
    with patch("alembic.script.ScriptDirectory") as mock_sd:
        mock_sd.from_config.return_value = fake_script
        with pytest.raises(AssertionError, match="single head"):
            _single_head(mrt)


def test_single_head_django_passes_single_leaf_per_app():
    mrt = _django_mrt_with_leaves([("users", "0001_initial"), ("orders", "0001_initial")])
    _single_head(mrt)  # one leaf per app — should pass


def test_single_head_django_fails_multiple_leaves_same_app():
    mrt = _django_mrt_with_leaves(
        [("users", "0002_add_email"), ("users", "0002_add_phone")]
    )
    with pytest.raises(AssertionError, match="multiple leaf"):
        _single_head(mrt)


# ── test_mrt_upgrade ─────────────────────────────────────────────────────────


def test_upgrade_skips_django_mode():
    with pytest.raises(pytest.skip.Exception):
        _upgrade(_mrt(django_mode=True))


def test_upgrade_calls_upgrade_head():
    mrt = _mrt()
    _upgrade(mrt)
    mrt.upgrade.assert_called_once_with("head")


# ── test_mrt_downgrade_base ──────────────────────────────────────────────────


def test_downgrade_base_skips_django_mode():
    with pytest.raises(pytest.skip.Exception):
        _downgrade_base(_mrt(django_mode=True))


def test_downgrade_base_happy_path():
    mrt = _mrt()
    _downgrade_base(mrt)
    assert mrt.upgrade.call_count == 2
    mrt._runner.downgrade_base.assert_called_once()


def test_downgrade_base_fails_on_re_upgrade_error():
    mrt = _mrt()
    call_count = [0]

    def upgrade_side_effect(target):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("re-upgrade failed")

    mrt.upgrade.side_effect = upgrade_side_effect
    with pytest.raises(pytest.fail.Exception, match="re-upgrade to head"):
        _downgrade_base(mrt)


# ── test_mrt_up_down_consistency ─────────────────────────────────────────────


def test_up_down_consistency_calls_assert_all_reversible():
    mrt = _mrt()
    _up_down(mrt)
    mrt.assert_all_reversible.assert_called_once()


# ── test_mrt_static_no_errors ────────────────────────────────────────────────


def test_static_no_errors_calls_assert():
    mrt = _mrt()
    _static(mrt)
    mrt.assert_no_static_errors.assert_called_once()


# ── test_mrt_schema_matches_models ───────────────────────────────────────────


def test_schema_matches_skips_when_no_metadata():
    mrt = _mrt()
    with pytest.raises(pytest.skip.Exception):
        _schema(mrt)


def test_schema_matches_calls_assert_when_metadata_set():
    mrt = _mrt()
    mrt._config.target_metadata = "myapp.models:Base"
    _schema(mrt)
    mrt.upgrade.assert_called_once_with("head")
    mrt.assert_schema_matches.assert_called_once()


def test_schema_matches_skips_upgrade_in_django_mode():
    mrt = _mrt(django_mode=True)
    mrt._config.target_metadata = "myapp.models:Base"
    _schema(mrt)
    mrt.upgrade.assert_not_called()
    mrt.assert_schema_matches.assert_called_once()
