# Observability

Each run writes JSONL events to:

`<logging.jsonl_dir>/<run_id>/events.jsonl`

Replay a run:

```bash
uv run agent replay <run_id> --event-stream
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
