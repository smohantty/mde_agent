# Testing

Run test suite:

```bash
uv run pytest
```

Quality checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Coverage expectation for core modules is 85%+.

## See also

- [Architecture Overview](architecture.md) — module map and layer diagram for understanding test scope
