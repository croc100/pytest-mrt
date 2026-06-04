"""
Example: pytest-mrt in a real blog application.

Run:
    cd examples/blog
    pytest test_migrations.py -v -s

Expected output:
    001  ✓ reversible
    002  ✓ reversible
    003  ✓ reversible
    004  ✗ data loss (phone column values lost)
    005  ✗ data loss (username casing lost, noop downgrade)
"""


def test_all_migrations_are_reversible(mrt):
    """
    One test to rule them all.
    Checks every migration in sequence for safe rollback.
    """
    mrt.assert_all_reversible()


def test_specific_revision(mrt):
    """
    Check a single revision by ID.
    Useful in CI to gate only new migrations added in a PR.
    """
    result = mrt.check_revision("003")
    assert result.passed, result.failure_summary()
