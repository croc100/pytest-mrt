# Django example — pytest-mrt

This example shows how to use `mrt check` with a Django app that has both safe and risky migrations.

## Run static analysis

```bash
pip install pytest-mrt

mrt check myapp/migrations/
```

Expected output:

```
╭──────────────────────┬────────────────────────────────┬───────┬──────┬──────────────────────────────────────────────────────╮
│ Revision             │ Pattern                        │ Sev   │ Line │ Message                                              │
├──────────────────────┼────────────────────────────────┼───────┼──────┼──────────────────────────────────────────────────────┤
│ myapp.0003_risky_not │ AddField NOT NULL without      │ error │   16 │ AddField('user', 'login_count') may be NOT NULL      │
│ _null                │ default                        │       │      │ without a default — will fail on non-empty tables    │
├──────────────────────┼────────────────────────────────┼───────┼──────┼──────────────────────────────────────────────────────┤
│ myapp.0004_run_sql_n │ RunSQL without reverse_sql     │ error │   16 │ migrations.RunSQL() has no reverse_sql — migration   │
│ o_reverse            │                                │       │      │ cannot be reversed automatically                     │
╰──────────────────────┴────────────────────────────────┴───────┴──────┴──────────────────────────────────────────────────────╯
2 error(s), 0 warning(s)
```

Migrations `0001` and `0002` are safe. Migrations `0003` and `0004` have known issues that `mrt check` catches before they reach production.

## Fix the issues

**0003** — Add a default or use `null=True`:
```python
field=models.IntegerField(null=False, default=0)
```

**0004** — Add `reverse_sql`:
```python
migrations.RunSQL(
    sql="UPDATE myapp_user SET login_count = 0 WHERE login_count IS NULL",
    reverse_sql="UPDATE myapp_user SET login_count = NULL",
)
```
