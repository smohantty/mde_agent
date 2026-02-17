# AGENT.md

This repository uses a single canonical agent guide:

- Read and follow `CLAUDE.md` for full project behavior, constraints, architecture intent, and implementation rules.

Do not duplicate or drift policy here.
If guidance needs updates, update `CLAUDE.md` and keep this file as a pointer.

## Quick Start for Any Coding Agent

1. Read `CLAUDE.md` before making changes.
2. Keep the system generic (no skill-specific hacks).
3. Preserve dynamic skill loading + progressive disclosure.
4. Preserve unified LLM request/response observability.
5. Validate with:
- `uv run ruff check .`
- `uv run pyright`
- `uv run pytest`

