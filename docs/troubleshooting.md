# Troubleshooting

## missing_provider_api_key

Set `ANTHROPIC_AUTH_TOKEN` (preferred) or `ANTHROPIC_API_KEY` for Anthropic, or set
`GEMINI_API_KEY` for Gemini.

## No skills found

Check `--skills-dir` and ensure each skill has a `SKILL.md` file with valid frontmatter.

## Decode failed

The model response did not match expected structured output schema.

## Max turns exceeded

Increase `runtime.max_turns` or simplify the task.

## MCP connection failed

Check that the MCP server command is correct and the `mcp` package is installed (`uv sync --extra mcp`). The agent continues without MCP tools when connection fails.

## MCP tool call failed

Verify the tool name exists on the connected server. Check server logs for errors. See [MCP Integration: Error Handling](mcp-integration.md#error-handling) for the full error matrix.

## See also

- [Decision Loop](decision-loop.md) — orchestrator runtime flow diagrams
- [MCP Integration](mcp-integration.md) — MCP lifecycle and error handling
