# Observability

Each run writes JSONL events to:

`<logging.jsonl_dir>/<run_id>/events.jsonl`

LLM communication transcript (request/response context + decode summary) is written to:

`<logging.jsonl_dir>/<run_id>/llm_transcript.jsonl`

Replay a run:

```bash
uv run agent replay <run_id> --event-stream
```

Replay concise LLM transcript entries:

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
- `skill_step_executed`
- `run_finished` / `run_failed`

Transcript rows include:

- full prompt/response bodies (sanitized + redacted)
- provider/model/attempt metadata
- token usage and latency
- decoded action types
- response classification (`skill_call`, `tool_call`, `response`)
