# Autonomous Skill-Native Agent Plan and Requirements

## Summary
Build a Python 3.12+ autonomous agent that uses the Agent Skills specification as its core context mechanism, with strong step-by-step observability of skill routing, LLM calls, output decoding, and execution.
v1 is demo-grade but robust, dual-provider (Anthropic + Gemini), CLI-first, local-skill-first, and intentionally permissive by default.
Use modern Python engineering practices by default: `uv` for environment/dependency management, `ruff` for linting/formatting, and strict static type checking.

## Standards Alignment
1. Skill format and loading follow the Agent Skills spec (`SKILL.md` with YAML frontmatter, references/scripts/resources layouts).
2. Progressive disclosure follows staged loading patterns: minimal metadata first, deeper content on demand.
3. Source references:
   - https://agentskills.io/specification
   - https://agentskills.io/integrate-skills
   - https://github.com/anthropics/skills

## Python Engineering Standards
1. Use `uv` for project bootstrap, dependency resolution, lockfile management, and local task execution.
2. Use `ruff` for linting and formatting (`ruff check`, `ruff format`).
3. Enforce strict type checking with `pyright` (or `mypy --strict` fallback if needed).
4. Store tool configuration in `pyproject.toml`.
5. Quality gates (local and CI):
   - `uv run ruff format --check .`
   - `uv run ruff check .`
   - `uv run pyright`
6. CLI framework: `typer`.
7. Configuration loading and validation: Pydantic models with strict field validation and clear startup errors for unknown keys/invalid values.

## Dependency Baseline
| Dependency | Purpose |
| --- | --- |
| `pydantic` v2 | Typed contracts and config validation |
| `typer` | Type-safe CLI |
| `anthropic` | Anthropic API client |
| `google-genai` | Gemini API client |
| `rapidfuzz` | Lexical prefilter scoring |
| `rich` | Live console event stream |
| `pyyaml` | YAML frontmatter parsing |
| `pytest` | Test framework |
| `pytest-mock` | Mocking in tests |
| `syrupy` or `snapshottest` | Event-log snapshot tests |

## Public Interfaces and Types

### CLI Commands
1. `agent run "<task>" --skills-dir ./skills --profile permissive --provider anthropic|gemini --debug-llm false --dry-run false --max-turns 8`
2. `agent skills list --skills-dir ./skills`
3. `agent skills inspect <skill_name> --show-frontmatter --show-sections`
4. `agent replay <run_id> --event-stream`
5. `agent config init`
6. `agent config validate --file agent.yaml`

### CLI Command Semantics
1. `agent run` with `--dry-run true` performs prefiltering, disclosure selection, token budgeting, and prompt composition, but skips LLM API calls and command/script execution.
2. `agent run` with `--dry-run true` still emits full planning-phase events and ends with `run_finished` with `mode=dry_run`.
3. `agent replay <run_id> --event-stream` replays stored JSONL events for a completed run to the rich console for post-hoc inspection.
4. Config discovery order for `agent run` and related commands is:
   - `--config <path>` (highest priority)
   - `./agent.yaml`
   - `~/.config/agent/agent.yaml`
   - built-in defaults (lowest priority)
5. `agent config init` writes `./agent.yaml` by default unless a custom output path is provided.

### Config File (`agent.yaml`)
```yaml
model:
  provider: anthropic  # anthropic | gemini
  name: claude-sonnet-4-5
  max_tokens: 4096
  max_context_tokens: 32000
  response_headroom_tokens: 2000
  structured_output_mode: native_with_json_fallback
  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
    gemini:
      api_key_env: GEMINI_API_KEY
runtime:
  profile: permissive
  shell_linux: /bin/bash
  shell_windows: pwsh
  timeout_seconds: 120
  max_turns: 8
  max_llm_retries: 3
  retry_base_delay_seconds: 1.0
  retry_max_delay_seconds: 8.0
  on_step_failure: retry_once_then_fallback_then_abort
  signal_grace_seconds: 10
skills:
  dir: ./skills
  prefilter_top_k: 8
  prefilter_min_score: 55  # rapidfuzz normalized score on 0-100 scale
  prefilter_zero_candidate_strategy: fallback_all_skills
  disclosure_max_reference_bytes: 120000
  disclosure_max_reference_tokens: 4000
logging:
  level: info
  jsonl_dir: ./runs
  run_id_pattern: "YYYYMMDD-HHMMSS-<short-uuid>"
  debug_llm_bodies: false
  sanitize_control_chars: true
  redact_secrets: true
```

### Provider API Key Setup (Anthropic and Gemini)
1. API keys must be provided through environment variables; keys are never stored in `agent.yaml`.
2. Linux/macOS session setup:
   - `export ANTHROPIC_API_KEY="your_anthropic_key"`
   - `export GEMINI_API_KEY="your_gemini_key"`
3. Windows PowerShell session setup:
   - `$env:ANTHROPIC_API_KEY="your_anthropic_key"`
   - `$env:GEMINI_API_KEY="your_gemini_key"`
4. Persistent setup examples:
   - Linux/macOS: add exports to shell profile (`~/.bashrc` or `~/.zshrc`).
   - Windows: use user/system environment variables (for example via System Settings or `setx`).
5. Provider selection mapping:
   - `model.provider=anthropic` requires `ANTHROPIC_API_KEY`.
   - `model.provider=gemini` requires `GEMINI_API_KEY`.
6. Missing key behavior is fail-fast:
   - before `CALL_LLM`, validate that the selected provider key exists and is non-empty.
   - if missing, emit `run_failed` with reason `missing_provider_api_key` and do not call provider APIs.
7. Security requirement:
   - never print raw API keys in logs, errors, traces, or debug artifacts.

### Core Typed Contracts (Pydantic v2)
1. `SkillMetadata`: `name`, `description`, `tags`, `version`, `allowed_tools`, `references_index`.
2. `SkillCandidate`: `skill_name`, `score`, `reason`.
3. `TokenBudget`: `max_context_tokens`, `response_headroom_tokens`, `allocated_prompt_tokens`, `allocated_disclosure_tokens`.
4. `ModelDecision`: `selected_skill`, `reasoning_summary`, `required_disclosure_paths`, `planned_actions`.
5. `ActionStep`: `type` (`call_skill|run_command|ask_user|finish`), `params`, `expected_output`.
6. `StepExecutionResult`: `step_id`, `exit_code`, `stdout_summary`, `stderr_summary`, `retry_count`, `status`.
7. `LlmRequestMeta`: `provider`, `model`, `attempt`, `latency_ms`, `input_tokens`, `output_tokens`.
8. `EventRecord`: `run_id`, `trace_id`, `span_id`, `timestamp`, `event_type`, `payload`, `redaction_mode`.

### Event Log Schema (JSONL)
Each line is one `EventRecord`. Required event types:
1. `run_started`
2. `skill_catalog_loaded`
3. `skill_prefilter_completed`
4. `skill_disclosure_loaded`
5. `prompt_budget_computed`
6. `prompt_composed`
7. `llm_request_sent`
8. `llm_retry_scheduled`
9. `llm_response_received`
10. `llm_request_failed`
11. `llm_decision_decoded`
12. `skill_invocation_started`
13. `skill_step_executed`
14. `step_retry_scheduled`
15. `skill_invocation_finished`
16. `signal_received`
17. `graceful_shutdown_started`
18. `run_finished`
19. `run_failed`

## Architecture

### Modules
```text
agent/
  cli.py
  config.py
  logging/
    events.py
    jsonl_sink.py
    redaction.py
    sanitizer.py
  security/
    provenance.py
    secret_filter.py
  skills/
    registry.py
    parser.py
    disclosure.py
    router.py
  llm/
    provider_router.py
    base_client.py
    anthropic_client.py
    gemini_client.py
    prompt_builder.py
    token_budget.py
    structured_output.py
    decoder.py
  runtime/
    orchestrator.py
    state_machine.py
    policies.py
    retry.py
    signals.py
    executor.py
    shell_linux.py
    shell_windows.py
  storage/
    run_store.py
  demos/
    basic_demo_skills/
tests/
  fixtures/
```

### Orchestrator State Machine
1. `INIT`
2. `LOAD_SKILL_CATALOG`
3. `PREFILTER_SKILLS`
4. `DISCLOSE_CONTEXT_STAGE`
5. `CALL_LLM`
6. `DECODE_DECISION`
7. `EXECUTE_STEP`
8. `VERIFY_PROGRESS`
9. `HANDOFF_OR_FINISH`
10. `DONE`
11. `ERROR`

### Transition Rules and Loop Guard
| From | To | Condition |
| --- | --- | --- |
| `INIT` | `LOAD_SKILL_CATALOG` | Run starts |
| `LOAD_SKILL_CATALOG` | `PREFILTER_SKILLS` | Skill catalog load succeeds |
| `LOAD_SKILL_CATALOG` | `ERROR` | Catalog load fails |
| `PREFILTER_SKILLS` | `DISCLOSE_CONTEXT_STAGE` | Candidates found |
| `PREFILTER_SKILLS` | `DISCLOSE_CONTEXT_STAGE` | Zero candidates and strategy is `fallback_all_skills` |
| `PREFILTER_SKILLS` | `ERROR` | Zero candidates and strategy is `fail_fast` |
| `DISCLOSE_CONTEXT_STAGE` | `CALL_LLM` | Disclosure selected and budgeted |
| `CALL_LLM` | `CALL_LLM` | Transient provider error and retry budget remains |
| `CALL_LLM` | `DECODE_DECISION` | LLM response received |
| `CALL_LLM` | `ERROR` | Non-retryable provider error or retries exhausted |
| `DECODE_DECISION` | `CALL_LLM` | Structured decode fails and one repair/fallback retry remains |
| `DECODE_DECISION` | `EXECUTE_STEP` | Action step returned |
| `DECODE_DECISION` | `HANDOFF_OR_FINISH` | Finish or handoff decision returned |
| `DECODE_DECISION` | `ERROR` | Decision invalid after fallback path |
| `EXECUTE_STEP` | `VERIFY_PROGRESS` | Step execution succeeds |
| `EXECUTE_STEP` | `EXECUTE_STEP` | Step failure and retry policy allows one retry |
| `EXECUTE_STEP` | `HANDOFF_OR_FINISH` | Step failure and fallback skill selected |
| `EXECUTE_STEP` | `ERROR` | Step failure with abort policy |
| `VERIFY_PROGRESS` | `DISCLOSE_CONTEXT_STAGE` | More context/disclosure needed |
| `VERIFY_PROGRESS` | `CALL_LLM` | Continue reasoning with accumulated execution results |
| `VERIFY_PROGRESS` | `HANDOFF_OR_FINISH` | Objective met or blocked |
| `HANDOFF_OR_FINISH` | `DISCLOSE_CONTEXT_STAGE` | Handoff to next skill |
| `HANDOFF_OR_FINISH` | `DONE` | Final completion reached |
| `*` | `ERROR` | `max_turns` reached or fatal runtime error |

Loop guard:
1. `max_turns` defaults to `8` and is configurable.
2. A "turn" is defined as one `CALL_LLM` invocation attempt (including retries within that same attempt context).
3. Increment `turn_index` once when entering `CALL_LLM` for a new reasoning step (not on `EXECUTE_STEP` retries).
4. On `turn_index >= max_turns`, emit `run_failed` with reason `max_turns_exceeded`.

## Progressive Disclosure Design
1. Stage 0: scan skill directories and load only frontmatter metadata.
2. Stage 1: load selected skill heading and summary sections from `SKILL.md`.
3. Stage 2: load only requested references/sections listed by model decision.
4. Stage 3: load script descriptors and execution constraints when execution is requested.
5. Every disclosure transition emits `skill_disclosure_loaded` with exact files, bytes, and estimated tokens.
6. Disclosure caps enforce both `disclosure_max_reference_bytes` and `disclosure_max_reference_tokens`.

## Token Budget Management
1. Add `max_context_tokens` and `response_headroom_tokens` to config.
2. `prompt_builder.py` computes provider-specific budget per call:
   - budget = `max_context_tokens - response_headroom_tokens`
   - Anthropic path: use provider token counting from SDK/endpoint when available, otherwise fallback to local estimation.
   - Gemini path: use provider token counting from SDK/endpoint when available, otherwise fallback to local estimation.
   - Local estimation fallback: `estimated_tokens = ceil(char_count / 4)` with a safety multiplier before final truncation.
3. Allocate budget across components in fixed order:
   - system prompt
   - user task
   - run state summary
   - candidate skill metadata
   - disclosed content
4. When over budget, trim least-critical disclosed references first, then long history summaries, never system instructions.
5. Multi-turn accumulation is explicit: `prompt_builder` accepts `list[StepExecutionResult]` and serializes it into the run-state summary section for subsequent turns.
6. Emit `prompt_budget_computed` on every turn with token allocation details.

## Skill Routing and Invocation
1. Hybrid routing:
   - lexical prefilter (`rapidfuzz` + tag/keyword match) to top-K
   - `prefilter_min_score` uses rapidfuzz's normalized 0-100 score scale
   - model chooses primary skill from candidates
2. Zero-candidate behavior is configurable:
   - default: `fallback_all_skills` metadata-only view
   - optional: `fail_fast`
3. Multi-skill policy:
   - sequential execution with explicit logged handoff rationale
4. Execution policy:
   - instruction-first behavior
   - optional scripts only when selected skill references executable artifacts
5. Step failure policy:
   - retry once for retryable failures
   - then allow fallback-skill handoff
   - then abort with `run_failed` if still unresolved

## LLM Call and Structured Output Pipeline
1. Build prompt from task, run-state summary, top-K skill metadata, and disclosed content slices.
2. Use provider-native structured output first:
   - Anthropic: tool-use/function-style structured response path
   - Gemini: `response_mime_type: application/json` or function-calling path
3. Route through provider router and log provider/model metadata at `llm_request_sent`.
4. Apply transient-error retries with exponential backoff and jitter (`max_llm_retries`).
5. Decode structured output into `ModelDecision`.
6. Fallback path:
   - if native structured decoding fails, parse strict JSON response
   - one repair pass with schema reminder
   - fail deterministically if still invalid
7. In `debug_llm_bodies=true`, store full prompt/response artifacts in run folder; otherwise store redacted summaries only.

## Error Recovery and Resilience Policies
1. LLM resilience:
   - retry transient HTTP/network errors and rate limits up to `max_llm_retries`
   - backoff = exponential with jitter, bounded by `retry_max_delay_seconds`
2. Script resilience:
   - capture exit code/stdout/stderr
   - apply `on_step_failure` policy
   - emit `step_retry_scheduled` for retries
3. Prefilter degradation:
   - if no skills pass threshold, run `prefilter_zero_candidate_strategy`
4. Graceful shutdown:
   - on `SIGINT`/`SIGTERM`, emit signal events, stop new work, terminate child processes, flush JSONL sink, and emit terminal run event.

## Logging and Explainability Requirements
1. Console: live `rich` event stream with trace ID, turn number, selected skill, action, and status.
2. Files: JSONL event log per run in `runs/<run_id>/events.jsonl`.
3. Always log:
   - skill candidates and chosen skill rationale
   - exact disclosure files loaded with bytes/tokens
   - LLM call boundaries, retries, and decoder outcome
   - command invocations, stdout/stderr summaries, exit codes
4. Redaction defaults:
   - request/response bodies redacted by default
   - full bodies only in explicit debug mode
5. Output sanitization:
   - strip or escape terminal control characters from stdout/stderr before writing logs
6. Secret handling:
   - never log API keys or secret values, including debug mode
7. Run IDs:
   - `YYYYMMDD-HHMMSS-<short-uuid>` for sortable, human-readable traces.

## Security Baseline (Even in Permissive Profile)
1. Skill provenance validation:
   - warn and block by default if `SKILL.md` references scripts outside its skill directory tree.
2. Path traversal protections:
   - normalize and validate all skill-relative paths before reading/executing.
3. Log injection mitigation:
   - sanitize control characters in all externally sourced text before persistence/display.
4. Secret redaction:
   - redact known secret patterns and configured env-key names from logs.

## Cross-Platform Execution
1. Linux command runner: `/bin/bash -lc`.
2. Windows command runner: `pwsh -NoProfile -Command`.
3. Path handling:
   - normalize via `pathlib`
   - OS-specific quoting adapter in executor
4. Timeout and cancellation:
   - per-step timeout from config
   - kill process tree on timeout or shutdown
5. Signal handling:
   - Linux: `SIGINT`/`SIGTERM`
   - Windows: CTRL+C equivalent handling with graceful shutdown path
6. Workspace behavior:
   - unrestricted local writes by default (as chosen)
   - network allowed by default (as chosen)

## MVP Skill Pack (Basic Linux Demo)
Create local skills under `demos/basic_demo_skills`:
1. `workspace-inventory`
2. `keyword-search-extractor`
3. `content-summarizer`
4. `task-checklist-builder`
5. `markdown-report-drafter`

Each skill includes:
1. `SKILL.md` with frontmatter and instructions.
2. `references/` with short examples/templates.
3. Optional `scripts/` for simple file parsing and text extraction.
4. Progressive references so stage-by-stage loading is visible in logs.

## Documentation Requirements
1. Documentation must be extensive and versioned in-repo under `docs/`.
2. Required documents:
   - `README.md`: project overview, quickstart, and common workflows.
   - `docs/getting-started.md`: install (`uv`), config init, provider selection, first run.
   - `docs/providers.md`: Anthropic/Gemini setup, API key steps for Linux/Windows, model selection, provider-specific caveats.
   - `docs/configuration.md`: full `agent.yaml` field reference and config discovery precedence.
   - `docs/skills.md`: skill layout, progressive disclosure stages, and safe script packaging.
   - `docs/observability.md`: event taxonomy, `agent replay`, run artifacts, troubleshooting logs.
   - `docs/testing.md`: how to run unit/integration tests, fixture strategy, snapshot updates.
   - `docs/troubleshooting.md`: missing API key, rate limits, decode errors, timeout and retry behavior.
3. Every user-facing CLI command must have usage examples in docs.
4. Every config field must have documented default, type, and allowed values.
5. Documentation updates are mandatory for any behavior or interface changes.

## Tests and Acceptance Criteria

### Static Quality Gates
1. Formatting check passes: `uv run ruff format --check .`.
2. Lint check passes: `uv run ruff check .`.
3. Type check passes: `uv run pyright`.

### Unit Tests
1. Skill parser handles valid/invalid frontmatter and missing mandatory fields.
2. Disclosure engine loads only requested files and respects byte and token caps.
3. Prefilter unit tests cover no-match, all-match, and tie-break scenarios.
4. Token budget allocator enforces prompt limits and deterministic trimming.
5. Structured output decoder handles Anthropic and Gemini native outputs plus JSON fallback.
6. Retry policy tests validate backoff and retry cutoff behavior.
7. State machine transition tests validate allowed transitions and max-turn termination.
8. Config model tests reject invalid keys/types and missing required fields.
9. Event logger writes schema-valid JSONL with sanitized output content.
10. Provider key resolution tests validate env var lookup per selected provider.
11. Missing API key tests verify fail-fast behavior (`missing_provider_api_key`) before any LLM call.
12. Config discovery tests validate precedence: `--config` > `./agent.yaml` > `~/.config/agent/agent.yaml` > defaults.
13. `--dry-run` tests verify no provider API calls and no command execution.
14. Unit-test target for core runtime/llm/skills modules: >= 85% line coverage.

### Integration Tests (Linux CI)
1. Run static quality gates through `uv run`.
2. End-to-end `agent run` with mock Anthropic response selecting one skill.
3. End-to-end `agent run` with mock Gemini response selecting one skill.
4. Multi-turn loop where execution results are fed into the next LLM turn.
5. Script non-zero exit path verifies retry/fallback/abort policy behavior.
6. LLM transient failure path verifies retry and final failure behavior.
7. Zero-candidate prefilter path verifies fallback strategy behavior.
8. Debug mode writes full prompt/response artifacts.
9. Snapshot tests assert deterministic event sequence for known scenarios.
10. Provider key missing scenario fails fast with clear error event and message.

### Mocking and Fixture Strategy
1. Implement `MockProviderClient` with fixture replay from `tests/fixtures/provider_responses/`.
2. Store canonical request/response fixtures for both Anthropic and Gemini paths.
3. Use event-log snapshots from `tests/fixtures/event_snapshots/` for observability regressions.

### Manual Windows Validation
1. Run same demo tasks in PowerShell 7+.
2. Verify script execution, path quoting, and event stream parity.
3. Validate run artifacts in `runs/<run_id>/`.
4. Validate CTRL+C graceful shutdown events and child process cleanup.

### Acceptance Criteria
1. A run shows complete trace from prefilter to disclosure to LLM decode to execution to finish/fail.
2. Logs explicitly show invoked skill, rationale, disclosed context, retries, and recovery actions.
3. LLM interactions are observable without leaking full bodies unless debug is enabled.
4. Progressive disclosure shows token-aware context budgeting in logs.
5. The same task flow can execute through Anthropic or Gemini with equivalent event semantics.
6. Multi-turn tasks complete within `max_turns` and terminate safely on guard breach.
7. API key setup is fully documented for Linux/macOS and Windows, and missing-key failures are explicit and test-covered.
8. Documentation set in `docs/` is complete, accurate, and sufficient for first-time setup without code reading.

## Delivery Plan
1. Milestone 1: Bootstrap with `uv`, `pyproject.toml`, `ruff`, `pyright`, `typer`, and strict config models.
2. Milestone 2: CLI skeleton, run-store, event logger, sanitization/redaction, and run ID generation.
3. Milestone 3: Skill registry/parser/router, provenance checks, staged disclosure, and token budget allocator.
4. Milestone 4: Provider abstraction, Anthropic/Gemini clients, native structured output, JSON fallback, and retry policy.
5. Milestone 5: Orchestrator transition engine, multi-turn loop semantics, step failure policy, and graceful shutdown handling.
6. Milestone 6: Linux/Windows command execution adapters and basic demo skill pack.
7. Milestone 7: CI tests, fixture replay, event snapshot testing, coverage reporting, and manual Windows validation checklist.
8. Milestone 8: Complete documentation pass (`README.md` + `docs/`) with API key setup and operator runbooks.

## Open Design Decisions
1. Default model names per provider (`anthropic` and `gemini`) to pin for reproducible demos.
2. Whether to keep permissive profile as default for v1.1 or switch to strict-by-default with explicit `--profile permissive`.
3. Whether to move from JSONL-only run state to SQLite in v2 for query-heavy analytics.

## Assumptions and Defaults Locked
1. Python 3.12+, dual-provider support for Anthropic and Gemini (default provider configurable).
2. CLI + live event stream (`typer` + `rich`).
3. Structured JSON logs with trace IDs and sanitized output.
4. Local skill folder only for v1.
5. Single orchestrator loop with multi-turn execution and explicit `max_turns` guard.
6. Instruction-first with optional scripts.
7. Sequential multi-skill handoff.
8. Provider-native structured output first, strict JSON fallback second.
9. Redacted LLM bodies by default, full bodies only in debug.
10. JSONL-only run state storage for v1.
11. `uv`-first workflow (`uv` for env/deps/tasks), optional `pipx` for CLI installation.
12. Linux CI, plus manual Windows checks.
13. Permissive runtime profile by default (network allowed, unrestricted writes, no hard command allowlist).
14. `ruff` and strict type checking are mandatory quality gates.
15. API keys are env-var only, never persisted to config files or logs.
16. Extensive documentation and strong unit-test coverage are required deliverables, not optional follow-up work.
