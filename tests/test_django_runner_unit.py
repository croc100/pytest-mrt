"""
Unit tests for django_runner.py — no real Django or database required.

Patches sys.modules to simulate Django presence/absence and uses
mock.patch on create_engine to avoid real database connections.
"""

from __future__ import annotations

import sys
import unittest.mock as mock

import pytest

# ── DjangoMigration ──────────────────────────────────────────────────────


def test_migration_revision():
    from pytest_mrt.adapters.django_runner import DjangoMigration

    m = DjangoMigration(app_label="myapp", name="0001_initial")
    assert m.revision == "myapp/0001_initial"


def test_migration_filename():
    from pytest_mrt.adapters.django_runner import DjangoMigration

    m = DjangoMigration(app_label="myapp", name="0001_initial")
    assert m.filename == "0001_initial.py"


# ── _sqlalchemy_url_to_django_db ─────────────────────────────────────────


def test_sqlite_file_url():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("sqlite:///path/to/db.sqlite3")
    assert db["ENGINE"] == "django.db.backends.sqlite3"
    assert "db.sqlite3" in db["NAME"]


def test_sqlite_memory_url():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("sqlite:///:memory:")
    assert db["ENGINE"] == "django.db.backends.sqlite3"
    assert db["NAME"] == ":memory:"


def test_postgresql_full_url():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("postgresql://user:secret@db.host:5432/mydb")
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "mydb"
    assert db["HOST"] == "db.host"
    assert db["PORT"] == "5432"
    assert db["USER"] == "user"
    assert db["PASSWORD"] == "secret"


def test_postgresql_no_auth_or_port():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("postgresql:///localdb")
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "localdb"
    assert "HOST" not in db
    assert "PORT" not in db
    assert "USER" not in db


def test_mysql_url():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("mysql://user:pw@localhost/mydb")
    assert db["ENGINE"] == "django.db.backends.mysql"
    assert db["NAME"] == "mydb"


def test_mssql_url():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("mssql+pymssql://user:pw@localhost/mydb")
    assert db["ENGINE"] == "mssql"


def test_oracle_url():
    from pytest_mrt.adapters.django_runner import _sqlalchemy_url_to_django_db

    db = _sqlalchemy_url_to_django_db("oracle+cx_oracle://user:pw@localhost:1521/orcl")
    assert db["ENGINE"] == "django.db.backends.oracle"


# ── _configure_django helpers ─────────────────────────────────────────────


def _make_django_mocks(configured: bool = False):
    mock_settings = mock.MagicMock()
    mock_settings.configured = configured
    mock_settings.DATABASES = {"default": {}}

    mock_django = mock.MagicMock()
    mock_conf = mock.MagicMock()
    mock_conf.settings = mock_settings

    return (
        {"django": mock_django, "django.conf": mock_conf},
        mock_django,
        mock_settings,
    )


# ── _configure_django ─────────────────────────────────────────────────────


def test_configure_already_configured():
    """Returns early without calling setup() when settings are already configured."""
    from pytest_mrt.adapters.django_runner import _configure_django

    mods, mock_django, _ = _make_django_mocks(configured=True)
    with mock.patch.dict("sys.modules", mods):
        _configure_django("sqlite:///:memory:", None, None, [])

    mock_django.setup.assert_not_called()


def test_configure_no_settings_module():
    """Calls configure() + setup() when no settings module is given."""
    from pytest_mrt.adapters.django_runner import _configure_django

    mods, mock_django, mock_settings = _make_django_mocks(configured=False)
    with mock.patch.dict("sys.modules", mods):
        _configure_django("sqlite:///:memory:", None, None, ["myapp"])

    mock_settings.configure.assert_called_once()
    mock_django.setup.assert_called_once()


def test_configure_with_settings_module(monkeypatch):
    """With settings_module, calls setup() and updates DATABASES."""
    from pytest_mrt.adapters.django_runner import _configure_django

    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    mods, mock_django, _ = _make_django_mocks(configured=False)
    with mock.patch.dict("sys.modules", mods):
        _configure_django("sqlite:///:memory:", "myproject.settings", None, [])

    mock_django.setup.assert_called_once()


def test_configure_with_project_dir(tmp_path):
    """project_dir is prepended to sys.path."""
    from pytest_mrt.adapters.django_runner import _configure_django

    mods, _, _ = _make_django_mocks(configured=False)
    with mock.patch.dict("sys.modules", mods):
        _configure_django("sqlite:///:memory:", None, str(tmp_path), [])

    assert str(tmp_path) in sys.path
    while str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))


def test_configure_import_error():
    """Raises ImportError with install hint when Django is not available."""
    from pytest_mrt.adapters.django_runner import _configure_django

    with mock.patch.dict("sys.modules", {"django": None}):
        with pytest.raises(ImportError, match="pip install django"):
            _configure_django("sqlite:///:memory:", None, None, [])


# ── DjangoMigrationRunner fixture ────────────────────────────────────────


@pytest.fixture
def runner():
    """DjangoMigrationRunner with Django and SQLAlchemy dependencies mocked."""
    with (
        mock.patch("pytest_mrt.adapters.django_runner._configure_django"),
        mock.patch("pytest_mrt.adapters.django_runner.create_engine") as mock_ce,
    ):
        mock_ce.return_value = mock.MagicMock()
        from pytest_mrt.adapters.django_runner import DjangoMigrationRunner

        return DjangoMigrationRunner("sqlite:///:memory:")


def _attach_executor(
    runner, *, leaf_plans=None, node_parent=None, node_missing=False, applied=None
):
    """Attach a configured mock _executor() to *runner* and return the mock executor."""
    mock_exec = mock.MagicMock()

    if leaf_plans is not None:
        mock_exec.loader.graph.leaf_nodes.return_value = list(leaf_plans.keys())
        mock_exec.loader.graph.forwards_plan.side_effect = lambda leaf: leaf_plans[leaf]

    if applied is not None:
        mock_exec.loader.applied_migrations = {k: None for k in applied}

    if node_missing:
        mock_exec.loader.graph.node_map.get.return_value = None
    elif node_parent is not None:
        mock_node = mock.MagicMock()
        mock_node.parents = [node_parent]
        mock_exec.loader.graph.node_map.get.return_value = mock_node
    else:
        mock_node = mock.MagicMock()
        mock_node.parents = []
        mock_exec.loader.graph.node_map.get.return_value = mock_node

    runner._executor = mock.MagicMock(return_value=mock_exec)
    return mock_exec


# ── DjangoMigrationRunner methods ────────────────────────────────────────


def test_runner_upgrade(runner):
    mock_exec = _attach_executor(runner)
    runner.upgrade("myapp", "0001_initial")
    mock_exec.migrate.assert_called_once_with([("myapp", "0001_initial")])


def test_runner_downgrade_to_parent(runner):
    """downgrade() targets the first same-app parent."""
    mock_parent = mock.MagicMock()
    mock_parent.key = ("myapp", "0000_squashed")

    mock_exec = _attach_executor(runner, node_parent=mock_parent)
    mock_exec.loader.graph.node_map.get.return_value.parents = [mock_parent]

    runner.downgrade("myapp", "0001_initial")
    mock_exec.migrate.assert_called_once_with([("myapp", "0000_squashed")])


def test_runner_downgrade_to_zero_when_no_same_app_parent(runner):
    """downgrade() targets (app, None) when parent is from a different app."""
    mock_parent = mock.MagicMock()
    mock_parent.key = ("otherapp", "0001_dep")

    mock_exec = _attach_executor(runner, node_parent=mock_parent)
    mock_exec.loader.graph.node_map.get.return_value.parents = [mock_parent]

    runner.downgrade("myapp", "0001_initial")
    mock_exec.migrate.assert_called_once_with([("myapp", None)])


def test_runner_downgrade_no_parents_at_all(runner):
    """downgrade() targets (app, None) when the migration has no parents."""
    mock_exec = _attach_executor(runner)  # node_parent=None → parents=[]
    mock_exec.loader.graph.node_map.get.return_value.parents = []

    runner.downgrade("myapp", "0001_initial")
    mock_exec.migrate.assert_called_once_with([("myapp", None)])


def test_runner_downgrade_migration_not_found(runner):
    """downgrade() raises KeyError when migration is absent from the graph."""
    _attach_executor(runner, node_missing=True)

    with pytest.raises(KeyError, match="myapp/0001_initial"):
        runner.downgrade("myapp", "0001_initial")


def test_runner_downgrade_app_zero(runner):
    mock_exec = _attach_executor(runner)
    runner.downgrade_app_zero("myapp")
    mock_exec.migrate.assert_called_once_with([("myapp", None)])


def test_runner_get_migrations_all(runner):
    """get_migrations() returns all migrations in topological order."""
    key1 = ("myapp", "0001_initial")
    key2 = ("myapp", "0002_add_field")
    _attach_executor(runner, leaf_plans={key2: [key1, key2]})

    from pytest_mrt.adapters.django_runner import DjangoMigration

    result = runner.get_migrations()
    assert len(result) == 2
    assert all(isinstance(m, DjangoMigration) for m in result)
    assert result[0].name == "0001_initial"
    assert result[1].name == "0002_add_field"


def test_runner_get_migrations_deduplicates(runner):
    """get_migrations() deduplicates keys that appear in multiple leaf plans."""
    key1 = ("myapp", "0001_initial")
    key2 = ("myapp", "0002_add")
    # Two leaves that share key1 in their plan
    _attach_executor(runner, leaf_plans={key2: [key1, key2], key1: [key1]})

    result = runner.get_migrations()
    names = [m.name for m in result]
    assert names.count("0001_initial") == 1


def test_runner_get_migrations_filtered_by_app(runner):
    """get_migrations(apps=[...]) excludes other app labels."""
    key1 = ("myapp", "0001_initial")
    key2 = ("otherapp", "0001_initial")
    _attach_executor(runner, leaf_plans={key1: [key1], key2: [key2]})

    result = runner.get_migrations(apps=["myapp"])
    assert all(m.app_label == "myapp" for m in result)
    assert len(result) == 1


def test_runner_current_state(runner):
    """current_state() returns the set of applied migration keys."""
    applied = {("myapp", "0001_initial"), ("myapp", "0002_add")}
    _attach_executor(runner, applied=applied)

    assert runner.current_state() == applied


def test_runner_dispose(runner):
    """dispose() calls engine.dispose() and closes the default DB connection."""
    mock_conn = mock.MagicMock()
    mock_connections = mock.MagicMock()
    mock_connections.__getitem__ = mock.MagicMock(return_value=mock_conn)

    mock_db = mock.MagicMock()
    mock_db.connections = mock_connections

    with mock.patch.dict("sys.modules", {"django.db": mock_db}):
        runner.dispose()

    runner.engine.dispose.assert_called_once()
    mock_conn.close.assert_called_once()
