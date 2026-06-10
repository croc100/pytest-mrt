# Plugin API — Stability Guarantee

This page documents which parts of pytest-mrt are **stable public API** vs **internal implementation details**.

Starting from v0.8, we follow [Semantic Versioning](https://semver.org/). Any breaking change to a stable API increments the major version.

---

## Stable public API (guaranteed no breaking changes in 0.x)

### `MRTConfig`

```python
from pytest_mrt import MRTConfig
```

All constructor parameters are stable:

| Parameter | Type | Stable since |
|---|---|---|
| `alembic_ini` | `str` | v0.4 |
| `db_url` | `str` | v0.4 |
| `seed_rows` | `int` | v0.5 |
| `skip` | `dict[str, str]` | v0.5 |
| `severity_overrides` | `dict[str, str]` | v0.7 |
| `custom_seeds` | `dict[str, Callable]` | v0.6 |
| `custom_checks` | `list[Callable]` | v0.7 |
| `migration_timeout` | `int \| None` | v0.8 |
| `django_settings` | `str \| None` | v1.0 |
| `django_apps` | `list[str] \| None` | v1.0 |
| `django_project_dir` | `str \| None` | v1.0 |
| `minimum_downgrade_revision` | `str \| None` | v1.4 |
| `target_metadata` | `str \| None` | v1.2 |

### `MRTFixture` methods (via `mrt` fixture)

```python
def test_example(mrt):
    mrt.upgrade("001")
    mrt.downgrade()
    mrt.assert_all_reversible()
```

| Method | Stable since |
|---|---|
| `upgrade(revision)` | v0.4 |
| `downgrade(revision)` | v0.4 |
| `seed(table, rows, pk_col)` | v0.5 |
| `check_static(versions_dir)` | v0.7 |
| `assert_no_static_errors(versions_dir)` | v0.7 |
| `check_revision(revision)` | v0.5 |
| `check_migration(app_label, name)` | v1.0 |
| `check_all(apps)` | v0.5 |
| `assert_reversible(revision)` | v0.5 |
| `assert_all_reversible(apps)` | v0.4 |
| `assert_data_intact()` | v0.5 |
| `assert_schema_matches(target_metadata, metadata_path)` | v1.2 |
| `reset()` | v0.5 |

### `RevisionResult` attributes

| Attribute | Type | Stable since |
|---|---|---|
| `revision` | `str` | v0.5 |
| `passed` | `bool` | v0.5 |
| `skipped` | `bool` | v0.5 |
| `skip_reason` | `str` | v0.5 |
| `failures` | `list[str]` | v0.5 |
| `risk_score` | `int` | v0.6 |
| `failure_summary()` | `str` | v0.5 |

### `RiskWarning` attributes

| Attribute | Type | Stable since |
|---|---|---|
| `revision` | `str` | v0.5 |
| `file` | `str` | v0.5 |
| `pattern` | `str` | v0.5 |
| `message` | `str` | v0.5 |
| `severity` | `str` | v0.5 |
| `line` | `int \| None` | v0.6 |

### `MigrationAST` (custom checks API)

Functions registered via `MRTConfig(custom_checks=[fn])` receive a `MigrationAST`:

```python
from pytest_mrt.core.ast_analyzer import MigrationAST
from pytest_mrt.core.detector import RiskWarning

def my_check(m: MigrationAST) -> list[RiskWarning]:
    ...
```

Stable attributes and methods:

| Member | Type | Stable since |
|---|---|---|
| `m.revision` | `str` | v0.7 |
| `m.filename` | `str` | v0.7 |
| `m.source` | `str` | v0.7 |
| `m._parse_error` | `Exception \| None` | v0.7 |
| `m.upgrade_calls()` | `list[CallInfo]` | v0.7 |
| `m.downgrade_calls()` | `list[CallInfo]` | v0.7 |
| `m.upgrade_methods()` | `set[str]` | v0.7 |
| `m.downgrade_methods()` | `set[str]` | v0.7 |
| `m.str_arg(call, index)` | `str \| None` | v0.7 |

`CallInfo` stable attributes:

| Attribute | Type |
|---|---|
| `method` | `str` — the `op.*` method name |
| `kw` | `dict[str, Any]` — keyword arguments |
| `node` | `ast.Call` — AST node (has `.lineno`) |

### `__version__`

```python
from pytest_mrt import __version__
```

Always a PEP 440 version string. Stable since v0.4.

---

## CLI exit codes (stable since v0.8)

```
mrt check <versions_dir>
```

| Exit code | Meaning |
|---|---|
| `0` | No issues detected |
| `1` | Warnings found (review before next release) |
| `2` | Errors found — migrations have rollback risks |
| `2` | Warnings found with `--strict` |
| `4` | Config error — e.g. `alembic.ini` not found (pytest session exit) |

These exit codes are stable and will not change.

---

## Not stable (internal, may change)

The following are implementation details. Do not import or depend on them:

| Module / symbol | Reason |
|---|---|
| `pytest_mrt.core.runner.MigrationRunner` | Internal adapter for Alembic |
| `pytest_mrt.core.seeder.SmartSeeder` | Internal test data layer |
| `pytest_mrt.core.schema.*` | Internal schema diffing |
| `pytest_mrt.core.verifier.RollbackVerifier` | Internal verification engine |
| `pytest_mrt.core.detector._*` | All private check functions |
| `pytest_mrt.adapters.django_detector.*` | Internal Django adapter |
| `pytest_mrt.reporter.*` | Internal Rich console output |

If you find yourself needing to import from these modules, [open an issue](https://github.com/croc100/pytest-mrt/issues/new/choose) — we may promote it to the stable API.

---

## Version policy

| Version bump | What it means |
|---|---|
| `0.x.y` patch | Bug fixes, no API changes |
| `0.x+1.0` minor | New features, fully backwards-compatible |
| `1.0.0` | Stable API declaration, SemVer from here |
| `2.0.0` | Breaking API change (will have deprecation warnings first) |

Deprecations are announced at least **one minor version** before removal.
