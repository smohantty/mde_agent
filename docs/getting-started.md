# Getting Started

## Install

```bash
uv sync
```

## Initialize config

```bash
uv run agent config init
```

## Dry run

```bash
uv run agent run "inventory workspace" --skills-dir demos/basic_demo_skills --dry-run
```

## First real run

```bash
uv run agent run "create a checklist" --skills-dir demos/basic_demo_skills --provider gemini
```

## Interactive continuous CLI mode

```bash
uv run agent chat --skills-dir demos/basic_demo_skills --provider anthropic
```

In chat mode, each input line is a task. The agent completes it, preserves session context,
then returns to waiting for your next input.

Use `Ctrl+D` to exit.
Use `--reload-skills-each-task` if you are editing `SKILL.md` files live and want hot-reload behavior.

## With MCP support

```bash
# Install with MCP optional dependency
uv sync --extra mcp
```

Configure MCP servers in `agent.yaml` — see [MCP Integration](mcp-integration.md#configuration).

## Further reading

- [Architecture Overview](architecture.md) — system context, module map, layer diagram
- [Decision Loop](decision-loop.md) — orchestrator runtime flow and sequence diagrams
- [Data Models](data-models.md) — type system, events, run directory structure
- [MCP Integration](mcp-integration.md) — MCP server connections and tool invocation
