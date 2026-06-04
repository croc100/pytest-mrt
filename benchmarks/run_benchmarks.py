"""
pytest-mrt performance benchmarks.

Measures static analysis and dynamic verification speed across different
migration chain sizes. Run this script to reproduce the published numbers.

Usage:
    python benchmarks/run_benchmarks.py
    python benchmarks/run_benchmarks.py --db-url postgresql://localhost/mrt_bench
"""
from __future__ import annotations
import argparse
import statistics
import tempfile
import textwrap
import time
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip())


def _setup_alembic_env(tmp: Path, db_url: str) -> str:
    versions = tmp / "versions"
    versions.mkdir()
    _write(tmp / "alembic.ini", f"""
        [alembic]
        script_location = {tmp}
        sqlalchemy.url = {db_url}
    """)
    _write(tmp / "env.py", """
        from alembic import context
        from sqlalchemy import engine_from_config, pool

        def run_migrations_online():
            connectable = engine_from_config(
                context.config.get_section(context.config.config_ini_section),
                prefix="sqlalchemy.", poolclass=pool.NullPool)
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=None)
                with context.begin_transaction():
                    context.run_migrations()
        run_migrations_online()
    """)
    _write(tmp / "script.py.mako", "")
    return str(tmp / "alembic.ini")


def _write_migrations(versions: Path, count: int) -> None:
    for i in range(1, count + 1):
        down = f"'{i-1:03d}'" if i > 1 else "None"
        _write(versions / f"{i:03d}.py", f"""
            revision = '{i:03d}'
            down_revision = {down}
            branch_labels = None
            depends_on = None
            import sqlalchemy as sa
            from alembic import op

            def upgrade():
                op.create_table('bench_{i:03d}',
                    sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('name', sa.String(64), nullable=False),
                    sa.Column('value', sa.Float, nullable=True),
                )

            def downgrade():
                op.drop_table('bench_{i:03d}')
        """)


def bench_static(migration_counts: list[int], runs: int = 5) -> dict:
    from pytest_mrt.core.detector import analyze_migrations

    results = {}
    for count in migration_counts:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            versions = tmp / "versions"
            versions.mkdir()
            _write_migrations(versions, count)

            timings = []
            for _ in range(runs):
                t0 = time.perf_counter()
                analyze_migrations(str(versions))
                timings.append(time.perf_counter() - t0)

            results[count] = {
                "mean_ms": statistics.mean(timings) * 1000,
                "median_ms": statistics.median(timings) * 1000,
                "min_ms": min(timings) * 1000,
            }
    return results


def bench_dynamic(migration_counts: list[int], db_url: str, runs: int = 3) -> dict:
    from pytest_mrt.core.runner import MigrationRunner
    from pytest_mrt.core.verifier import RollbackVerifier

    results = {}
    for count in migration_counts:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            db_path = str(tmp / "bench.db")
            actual_url = db_url if db_url != "sqlite" else f"sqlite:///{db_path}"
            ini = _setup_alembic_env(tmp, actual_url)
            _write_migrations(tmp / "versions", count)

            timings = []
            for _ in range(runs):
                t0 = time.perf_counter()
                runner = MigrationRunner(ini, actual_url)
                verifier = RollbackVerifier(runner)
                verifier.check_all()
                timings.append(time.perf_counter() - t0)

            results[count] = {
                "mean_s": statistics.mean(timings),
                "per_migration_ms": statistics.mean(timings) / count * 1000,
            }
    return results


def print_results(static: dict, dynamic: dict) -> None:
    print("\n=== Static analysis (mrt check) ===")
    print(f"{'Migrations':>12} {'Mean (ms)':>12} {'Median (ms)':>12} {'Min (ms)':>10}")
    print("-" * 50)
    for count, r in sorted(static.items()):
        print(f"{count:>12} {r['mean_ms']:>12.1f} {r['median_ms']:>12.1f} {r['min_ms']:>10.1f}")

    print("\n=== Dynamic verification (SQLite) ===")
    print(f"{'Migrations':>12} {'Total (s)':>12} {'Per migration (ms)':>20}")
    print("-" * 48)
    for count, r in sorted(dynamic.items()):
        print(f"{count:>12} {r['mean_s']:>12.2f} {r['per_migration_ms']:>20.1f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default="sqlite", help="Database URL for dynamic benchmarks")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    sizes = [10, 25, 50, 100]

    print("Running static analysis benchmarks...")
    static = bench_static(sizes, runs=args.runs)

    print("Running dynamic verification benchmarks...")
    dynamic = bench_dynamic(sizes, args.db_url, runs=args.runs)

    print_results(static, dynamic)
