import textwrap
import tempfile
from pathlib import Path
from pytest_mrt.core.detector import analyze_migrations


def _write_migration(tmpdir: Path, filename: str, content: str) -> None:
    (tmpdir / filename).write_text(textwrap.dedent(content))


def test_detects_drop_column(tmp_path):
    _write_migration(tmp_path, "001_drop.py", """
        revision = '001'
        def upgrade(): op.drop_column('users', 'email')
        def downgrade(): pass
    """)
    warnings = analyze_migrations(str(tmp_path))
    patterns = [w.pattern for w in warnings]
    assert "DROP COLUMN" in patterns


def test_detects_noop_downgrade(tmp_path):
    _write_migration(tmp_path, "002_noop.py", """
        revision = '002'
        def upgrade(): op.add_column('users', sa.Column('x', sa.String))
        def downgrade(): pass
    """)
    warnings = analyze_migrations(str(tmp_path))
    patterns = [w.pattern for w in warnings]
    assert "No downgrade" in patterns


def test_clean_migration_no_warnings(tmp_path):
    _write_migration(tmp_path, "003_clean.py", """
        revision = '003'
        def upgrade(): op.add_column('users', sa.Column('x', sa.String, nullable=True))
        def downgrade(): op.drop_column('users', 'x')
    """)
    warnings = analyze_migrations(str(tmp_path))
    assert warnings == []
