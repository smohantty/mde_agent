# Observability

Each run writes JSONL events to:

`<logging.jsonl_dir>/<run_id>/events.jsonl`

LLM communication transcript (request/response context + decode summary) is written to:

`<logging.jsonl_dir>/<run_id>/llm_transcript.log`

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
- `skill_step_executed`
- `run_finished` / `run_failed`

Transcript entries include:

- full prompt/response bodies (sanitized + redacted)
- explicit request/response sections (`--- Raw Model Request ---`, `--- Raw Model Response ---`)
- raw request section includes provider payload wrapper (model/config/messages/contents)
- provider/model/attempt metadata
- token usage and latency
- raw action types from model output and normalized action types after decoding
- response classification (`skill_call`, `tool_call`, `response`)
- classification reason (`Response Kind Mapping`) so it is clear why a response was mapped
- user-focused plain-text blocks (no run/trace/span/timestamp/hash headers; those remain in `events.jsonl`)
