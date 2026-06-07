from __future__ import annotations


def load_metadata(metadata_path: str):
    """Import SQLAlchemy metadata from a dotted path like 'myapp.models:Base'."""
    if ":" not in metadata_path:
        raise ValueError(
            f"Invalid metadata path '{metadata_path}'. "
            "Use the form 'myapp.models:Base' or 'myapp.models:Base.metadata'."
        )
    module_path, attr = metadata_path.rsplit(":", 1)
    import importlib

    mod = importlib.import_module(module_path)
    obj = getattr(mod, attr)
    # Accept either a declarative Base class or a MetaData instance directly.
    return getattr(obj, "metadata", obj)


def compare_schema(engine, target_metadata) -> list:
    """Return alembic autogenerate diffs between DB schema and target_metadata."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        return compare_metadata(ctx, target_metadata)


def describe_diff(diff) -> str:
    """Format a single alembic autogenerate diff tuple into a human-readable string."""
    if not isinstance(diff, tuple):
        return repr(diff)
    kind = diff[0]
    if kind == "add_table":
        return f"add table '{diff[1].name}' (in models, missing from DB)"
    if kind == "remove_table":
        return f"remove table '{diff[1].name}' (in DB, missing from models)"
    if kind == "add_column":
        return f"add column '{diff[2]}.{diff[3].name}' (in models, missing from DB)"
    if kind == "remove_column":
        return f"remove column '{diff[2]}.{diff[3].name}' (in DB, missing from models)"
    if kind == "modify_type":
        return f"column '{diff[2]}.{diff[3]}' type mismatch: models={diff[5]!r}, DB={diff[4]!r}"
    if kind == "modify_nullable":
        return f"column '{diff[2]}.{diff[3]}' nullable mismatch: models={diff[5]}, DB={diff[4]}"
    return repr(diff)
