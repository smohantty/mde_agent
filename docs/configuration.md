# Configuration

Default config file is `agent.yaml`.

## Discovery precedence

1. `--config <path>`
2. `./agent.yaml`
3. `~/.config/agent/agent.yaml`
4. built-in defaults

## Validate config

```bash
uv run agent config validate --file agent.yaml
```

## Important fields

- `model.provider`: `anthropic` or `gemini`
- `model.max_context_tokens`: context budget ceiling
- `runtime.max_turns`: LLM turn guard (one turn = one `CALL_LLM` invocation)
- `skills.dir`: default skills directory (used by `agent run` and `agent chat` when `--skills-dir` is not provided)
- `skills.prefilter_min_score`: rapidfuzz score threshold (0-100)
- `logging.jsonl_dir`: run output directory
- `logging.run_id_pattern`: human-readable run-id format
- `logging.llm_transcript_enabled`: enable per-run LLM transcript logging
- `logging.llm_transcript_filename`: transcript filename under each run directory
- `mcp.enabled`: enable MCP server connections (default: `true`)
- `mcp.tool_call_timeout_seconds`: timeout for individual MCP tool calls
- `mcp.servers`: map of server name → `McpServerConfig`

## Chat mode notes

- `agent chat` is an interactive CLI loop that executes each input as a task and waits for the next input.
- Chat mode carries session context across tasks using rolling summaries.
- By default, skills are parsed once at chat startup for performance.
- Use `agent chat --reload-skills-each-task` to reparse skills before every task (useful while editing skills live).
- One chat session uses one run id and appends all per-task logs into the same run directory.

## See also

- [Architecture: Configuration Model](architecture.md#configuration-model) — full class diagram of all config sections
- [MCP Integration: Configuration](mcp-integration.md#configuration) — MCP server configuration examples
