# TODO (Revisit Later)

Date created: 2026-02-17  
Owner: Codex review follow-ups

## Native Tool Use Follow-ups

- [ ] Prevent fallback request artifacts from overwriting native attempt artifacts in the same turn/call-site.
- [ ] Ensure fallback transcript records use the fallback prompt context, token estimate, and budget.
- [ ] Add tests for `native_only` strict failure behavior when no tool/function call is returned.
- [ ] Add tests that verify native + fallback attempts are both preserved in artifacts/transcript output.

## Documentation Updates

- [ ] Document `model.structured_output_mode` options: `json_only`, `native_with_json_fallback`, `native_only`.
- [ ] Document `native_tool_fallback` event semantics in observability docs.
- [ ] Add operator guidance for when to use each mode and expected failure behavior.

## MCP Integration (Planned)

- [ ] Define MCP architecture boundary (client/session lifecycle, tool discovery, invocation adapter).
- [ ] Add MCP configuration model (server registry, auth/env mapping, timeout/retry).
- [ ] Introduce canonical action path for MCP tool execution (without breaking existing `run_command` flow).
- [ ] Add provider-agnostic prompt/tooling strategy for MCP-discovered tools.
- [ ] Add observability events/artifacts for MCP calls (request, response, retries, failures, provenance).
- [ ] Add security controls for MCP allowlist/denylist and secret redaction in MCP payload logs.
- [ ] Add end-to-end tests with mocked MCP server and failure scenarios.

## MCP Post-Merge Fixes (Latest Review)

- [ ] Ensure MCP manager cleanup runs on all early-return paths (`dry_run`, missing provider key, other pre-loop exits).
- [ ] Fix MCP connection-failure cleanup so loop/thread/resources are always closed even when `connect_all()` fails.
- [ ] Wire and enforce `McpServerConfig.timeout_seconds` for MCP server connect/init/list-tools path.
- [ ] Resolve MCP tool-name collision behavior across servers (disambiguation strategy and call routing contract).
- [ ] Include `MCP_TOOLS` payload in prompt budget accounting to avoid under-reporting token usage.
- [ ] Add regression tests for all items above (especially cleanup + collision cases).
