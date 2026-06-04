# Performance Benchmarks

Numbers measured on Apple M-series, SQLite, Python 3.12, pytest-mrt 0.7.0.  
Run yourself: `python benchmarks/run_benchmarks.py`

---

## Static analysis (`mrt check`)

No database required. Parses migration files with Python AST.

| Migrations | Mean   | Notes |
|-----------|--------|-------|
| 10        | 22 ms  | Typical microservice |
| 25        | 54 ms  | Medium Django app |
| 50        | 108 ms | Large monolith |
| 100       | 216 ms | Very large legacy codebase |

**~2.2 ms per migration file.** Safe to run on every commit.

---

## Dynamic verification (`mrt` fixture)

Requires a real database. Seeds rows, runs upgrade → downgrade, verifies data survival.

| Migrations | Total  | Per migration |
|-----------|--------|---------------|
| 10        | 0.33 s | 33 ms |
| 25        | 1.38 s | 55 ms |
| 50        | 4.29 s | 86 ms |
| 100       | 15.6 s | 156 ms |

**SQLite is fastest.** PostgreSQL and MySQL add ~20–40 ms per migration due to network round-trips.

---

## Recommended CI strategy

```
Push → static check (< 1s always) → gate on errors
PR   → dynamic check (parallel, only on migration file changes)
```

For most projects (< 50 migrations), the full dynamic suite runs in **under 5 seconds**.
