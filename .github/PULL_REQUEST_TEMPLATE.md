## What does this PR do?

<!-- One sentence summary -->

## Type

- [ ] New risk pattern
- [ ] Bug fix
- [ ] New database support
- [ ] Documentation
- [ ] Other

## For new risk patterns

Migration that triggers it:
```python
def upgrade():
    # paste here
```

Why it's dangerous:
<!-- What goes wrong in production? -->

## Checklist

- [ ] Tests added (both positive and negative case)
- [ ] `pytest tests/ -v` passes
- [ ] `mrt check examples/blog/alembic/versions/` still works
- [ ] Pattern added to README table if applicable
