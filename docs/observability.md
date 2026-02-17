# Observability

Each run writes JSONL events to:

`<logging.jsonl_dir>/<run_id>/events.jsonl`

LLM communication transcript (request/response context + decode summary) is written to:

`<logging.jsonl_dir>/<run_id>/llm_transcript.log`

Every LLM invocation is logged the same way across call sites, including:

- `decision_loop`
- `final_answer_synthesis`

Replay a run:

```bash
uv run agent replay <run_id> --event-stream
```

Replay readable LLM transcript entries:

```bash
uv run agent replay <run_id> --llm-transcript
```

Core events include:

- `run_started`
- `skill_prefilter_completed`
- `skill_disclosure_loaded`
- `prompt_budget_computed`
- `llm_request_sent`
- `llm_response_received`
- `llm_decision_decoded`
- `self_handoff_detected` (loop-safety signal for repeated same-skill handoffs)
- `self_handoff_recovery_applied` (fallback actions injected to break repeated same-skill handoffs)
- `mcp_servers_connected` / `mcp_connection_failed`
- `mcp_tool_call_started` / `mcp_tool_call_completed` / `mcp_tool_call_failed`
- `mcp_servers_disconnected`
- `skill_step_executed`
- `run_finished` / `run_failed`

For the complete event types reference table (30+ events with phases and payloads), see [Data Models: Event Types Reference](data-models.md#event-types-reference).

`llm_request_sent`, `llm_response_received`, `llm_request_failed`, and `llm_retry_scheduled`
now include `call_site` in payload so you can see where the model call originated.

Transcript entries include:

- full prompt/response bodies (sanitized + redacted)
- explicit request/response sections (`--- Raw Model Request ---`, `--- Raw Model Response ---`)
- raw request section includes provider payload wrapper (model/config/messages/contents)
- provider/model/attempt metadata
- call-site metadata (`Call Site: decision_loop|final_answer_synthesis|unspecified`)
- token usage and latency
- raw action types from model output and normalized action types after decoding
- response classification (`skill_call`, `tool_call`, `response`)
- classification reason (`Response Kind Mapping`) so it is clear why a response was mapped
- user-focused plain-text blocks (no run/trace/span/timestamp/hash headers; those remain in `events.jsonl`)

Each attempt also writes per-attempt artifacts:

- `artifacts/llm/<call_site>_turn_<n>_attempt_<m>_request.txt`
- `artifacts/llm/<call_site>_turn_<n>_attempt_<m>_response.txt`

## See also

- [Data Models: Run Directory Structure](data-models.md#run-directory-structure) — full artifact layout
- [Data Models: LLM Transcript Record](data-models.md#llm-transcript-record) — transcript record schema
- [Decision Loop: LLM Invocation with Retry](decision-loop.md#llm-invocation-with-retry) — retry and logging sequence diagram
