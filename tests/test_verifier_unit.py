"""Unit tests for RollbackVerifier — timeout, error recovery, check_all edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text

from pytest_mrt.core.verifier import RevisionResult, RollbackVerifier

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_runner_mock(revisions=None):
    runner = MagicMock()
    runner.engine = create_engine("sqlite://")
    with runner.engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
    runner.current_revision.return_value = None
    runner.get_revisions.return_value = revisions or []
    return runner


def _make_verifier(runner, **kwargs):
    v = RollbackVerifier.__new__(RollbackVerifier)
    v.runner = runner
    v.skip = kwargs.get("skip", {})
    v.custom_seeds = kwargs.get("custom_seeds", {})
    v.timeout = kwargs.get("timeout", None)
    v.min_revision = kwargs.get("min_revision", None)
    return v


# ── RevisionResult.risk_score ─────────────────────────────────────────────────


def test_risk_score_zero_when_no_failures():
    r = RevisionResult(revision="abc", passed=True)
    assert r.risk_score == 0


def test_risk_score_capped_at_100():
    r = RevisionResult(revision="abc", passed=False, failures=["a", "b", "c", "d", "e"])
    assert r.risk_score == 100


def test_risk_score_25_per_failure():
    r = RevisionResult(revision="abc", passed=False, failures=["x", "y"])
    assert r.risk_score == 50


# ── timeout branch ───────────────────────────────────────────────────────────


def test_check_revision_timeout_records_failure():
    """When migration exceeds the timeout, check_revision returns a failure."""
    runner = _make_runner_mock()

    def slow_check(*args, **kwargs):
        import time

        # Keep sleep short: ThreadPoolExecutor.shutdown(wait=True) blocks until
        # the thread finishes even after TimeoutError, so this controls test duration.
        time.sleep(0.5)

    verifier = _make_verifier(runner, timeout=0.05)

    with patch.object(verifier, "_run_migration_check", side_effect=slow_check):
        result = verifier.check_revision("rev1")

    assert not result.passed
    assert any("timed out" in f for f in result.failures)


def test_check_revision_timeout_triggers_recovery():
    """After a timeout, check_revision attempts DB state recovery."""
    runner = _make_runner_mock()
    # After timeout: current_revision returns "rev1" (DB is in upgraded state)
    runner.current_revision.side_effect = [None, "rev1"]

    def slow_check(*args, **kwargs):
        import time

        time.sleep(0.5)

    verifier = _make_verifier(runner, timeout=0.05)

    with patch.object(verifier, "_run_migration_check", side_effect=slow_check):
        result = verifier.check_revision("rev1")

    assert not result.passed
    assert any("timed out" in f for f in result.failures)
    # current != start_revision → recovery should have been attempted
    runner.downgrade_base.assert_called()


# ── error recovery ────────────────────────────────────────────────────────────


def test_check_revision_exception_triggers_recovery():
    """An unexpected exception during migration check is caught and DB is recovered."""
    runner = _make_runner_mock()
    runner.current_revision.side_effect = [None, "rev1"]  # start=None, during recovery=rev1

    verifier = _make_verifier(runner)

    with patch.object(verifier, "_run_migration_check", side_effect=RuntimeError("boom")):
        result = verifier.check_revision("rev1")

    assert not result.passed
    assert any("boom" in f for f in result.failures)
    # Recovery: downgrade_base should have been called since current != start
    runner.downgrade_base.assert_called()


def test_check_revision_recovery_failure_appends_message():
    """If recovery itself fails, an additional message is appended."""
    runner = _make_runner_mock()
    runner.current_revision.side_effect = [None, "rev1"]
    runner.downgrade_base.side_effect = RuntimeError("recovery failed")

    verifier = _make_verifier(runner)

    with patch.object(verifier, "_run_migration_check", side_effect=RuntimeError("original")):
        result = verifier.check_revision("rev1")

    assert not result.passed
    messages = " ".join(result.failures)
    assert "original" in messages
    assert "recovery failed" in messages or "State recovery" in messages


# ── check_all chain advance failure ──────────────────────────────────────────


def test_check_all_chain_advance_failure_stops_and_records():
    """When advancing past a floor revision fails, remaining revisions are not tested."""
    rev1 = MagicMock()
    rev1.revision = "rev1"
    rev2 = MagicMock()
    rev2.revision = "rev2"

    runner = _make_runner_mock(revisions=[rev1, rev2])
    # upgrade to rev1 (floor advance) raises
    runner.upgrade.side_effect = RuntimeError("migration broken")

    verifier = _make_verifier(runner, min_revision="rev1")

    results = verifier.check_all()

    # rev1 is at floor — skipped normally first, then advance fails
    assert any(r.revision == "rev1" and r.skipped for r in results)
    # There should be a failure record about the advance
    failures = [r for r in results if not r.passed and not r.skipped]
    assert failures, f"Expected a failure record, got: {results}"
    assert any("rev1" in " ".join(r.failures) for r in failures)


# ── skip logic ────────────────────────────────────────────────────────────────


def test_check_revision_skips_when_in_skip_dict():
    runner = _make_runner_mock()
    verifier = _make_verifier(runner, skip={"rev1": "intentional data migration"})

    result = verifier.check_revision("rev1")

    assert result.passed
    assert result.skipped
    assert "intentional" in result.skip_reason
    runner.upgrade.assert_not_called()


# ── failure_summary ────────────────────────────────────────────────────────────


def test_failure_summary_formats_all_failures():
    r = RevisionResult(revision="abc", passed=False, failures=["issue A", "issue B"])
    summary = r.failure_summary()
    assert "issue A" in summary
    assert "issue B" in summary
