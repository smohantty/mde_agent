# Code & Architecture Review Report

**Project**: mde_agent — Generic Skill-Native Agentic System
**Date**: 2026-02-17
**Scope**: Full codebase review — architecture, genericity, tool/function calling, MCP, provider parity, security, observability, testing

---

## 1. Project Overview

~2,800 lines of Python (excluding tests). Core layout:

| Layer | Key Files | Purpose |
|-------|-----------|---------|
| Orchestration | `agent/runtime/orchestrator.py` (~1,500 lines) | Main decision loop, turn management, action execution |
| Skills | `agent/skills/{registry,parser,router,disclosure}.py` | Skill loading, SKILL.md parsing, fuzzy routing, progressive disclosure |
| LLM | `agent/llm/{provider_router,anthropic_client,gemini_client,decoder,prompt_builder}.py` | Provider abstraction, structured output, action normalization |
| Logging | `agent/logging/{events,transcript,redaction,sanitizer}.py` | JSONL events + human-readable LLM transcript |
| Security | `agent/security/{provenance,secret_filter}.py` | Path traversal protection, secret detection |
| Config | `agent/config.py` | YAML config + .env fallback for API keys |
| CLI | `agent/cli.py` | Typer-based entry point |

5 demo skills in `demos/basic_demo_skills/`: content-summarizer, markdown-report-drafter, task-checklist-builder, keyword-search-extractor, workspace-inventory.

---

## 2. Genericity Assessment — Are There Skill-Specific Hacks?

### Verdict: NO hardcoded skill-specific hacks found

The codebase is genuinely generic. Every skill-aware behavior is data-driven through SKILL.md metadata:

- **Action aliases** — Skills declare `action_aliases` in frontmatter (e.g., `list_files: run_command`). The decoder resolves these generically via lookup, never by checking skill names.
- **Default action params** — Skills declare `default_action_params` in frontmatter. The decoder merges these when the model omits a command, using generic key lookup.
- **Routing** — `SkillRouter.prefilter()` uses `rapidfuzz.partial_ratio()` against `(name, description, tags)`. Pure fuzzy scoring, no special-case branches.
- **Disclosure** — `DisclosureEngine` operates on generic `SkillDefinition.sections` and file paths. No skill names checked.

### One Borderline Pattern

In `orchestrator.py` (self-handoff recovery, ~line 296), there is a preferred action name list:

```python
preferred = [
    "generate_summary", "aggregate_summaries", "extract_sections",
    "extract_key_sections", "read_file", "read_file_content",
    "list_files", "find_markdown_files", "identify_markdown_files",
]
```

This is used when a skill repeatedly hands off to itself — the system picks a recovery action from the skill's own `default_action_params` using this preference order. This is NOT a skill-specific hack (it doesn't key off any skill name), but it encodes assumptions about what "good" action names look like. If a skill uses completely different naming conventions, the fallback degrades to generic `rg`/`find` commands. Low risk, but worth noting.

---

## 3. Tool Calling, Function Calling, and MCP

### Current Design: Text-Based JSON Structured Output (No Native Tool Use)

The system does NOT use:
- Anthropic's native `tools` parameter / `tool_use` content blocks
- Gemini's native function calling / tool declarations
- MCP (Model Context Protocol) server integration

Instead, it uses a prompt-instructed JSON schema approach:
1. The prompt tells the LLM to return a JSON object with `selected_skill`, `reasoning_summary`, `required_disclosure_paths`, `planned_actions`
2. Both providers are configured for JSON output (Gemini via `response_mime_type: application/json`, Anthropic via prompt instruction)
3. The decoder normalizes the JSON into a `ModelDecision` Pydantic model

### 4 Canonical Action Types

```python
ActionType = Literal["call_skill", "run_command", "ask_user", "finish"]
```

- `run_command` — Executed locally via shell subprocess
- `call_skill` — Records a handoff intent (continues the loop for another turn)
- `ask_user` — Skipped in non-interactive mode
- `finish` — Triggers optional final answer synthesis, then exits

### Decoder Normalization

The decoder handles model variation gracefully:
- Extracts action type from multiple possible keys (`type`, `action_type`, `action`, `step_type`, `operation`)
- Applies skill-specific aliases first, then base aliases (`execute_skill` -> `call_skill`, `run` -> `run_command`, `complete` -> `finish`, etc.)
- Infers type from params if missing (`command` in params -> `run_command`, `skill_name` -> `call_skill`)
- Demotes unknown types to `ask_user` as safe fallback

### Implications

| Aspect | Current State | Impact |
|--------|--------------|--------|
| Native tool use | Not used | Loses structured guarantees and model grounding that native tools provide |
| MCP integration | Not present | Cannot connect to external tool servers |
| Function calling | Text-JSON only | Works but more fragile than schema-validated tool calls |
| Cross-provider parity | High | Both providers use identical prompt-based approach |

---

## 4. Provider Parity

### Architecture

```
Orchestrator -> ProviderRouter -> {AnthropicClient, GeminiClient}
                                         |
                                   BaseLlmClient (ABC)
                                   complete_structured(prompt, model, max_tokens, attempt) -> LlmResult
```

### Parity Status

| Feature | Anthropic | Gemini | Parity? |
|---------|-----------|--------|---------|
| Interface | `complete_structured()` | `complete_structured()` | YES |
| Prompt format | `messages: [{role:user, content:prompt}]` | `contents: prompt` | YES (abstracted) |
| JSON enforcement | Prompt-instructed | `response_mime_type: application/json` | Slight asymmetry |
| Response parsing | Extract text blocks -> JSON parse | `response.text` -> JSON parse | YES |
| Token tracking | `usage.input_tokens`, `output_tokens` | `usage_metadata` | YES |
| Native tool use | NOT used | NOT used | N/A |

Assessment: True orchestration parity. Provider differences properly confined to client implementations. The JSON enforcement asymmetry is minor.

---

## 5. Orchestration Flow

```
Load skills
  -> Prefilter candidates (fuzzy scoring)
  -> Stage 1 disclosure (top 2 SKILL.md sections)
  -> Build prompt (TASK + RUN_STATE + CATALOG + CANDIDATES + DISCLOSED_CONTEXT)
  -> LLM call (with retry + logging)
  -> Decode response -> Normalize actions
  -> [Stage 2 disclosure if paths requested]
  -> Execute actions (run_command / call_skill / finish)
  -> [Self-handoff detection if looping]
  -> [Final answer synthesis from tool evidence on finish]
  -> Return RunResult
```

Key design strengths:
- **Progressive disclosure**: Stage 0 (catalog) -> Stage 1 (summary) -> Stage 2 (on-demand files) -> Stage 3 (scripts)
- **Self-handoff recovery**: Detects repeated `call_skill` to same skill, injects recovery commands, then blocks the skill
- **Final answer synthesis**: Second LLM call collects stdout evidence from tool executions and synthesizes a user-facing answer

---

## 6. Observability

### Dual-Layer Logging (Well-Implemented)

**Machine-oriented**: `runs/<run_id>/events.jsonl`
- Structured events: `run_started`, `llm_request_sent`, `llm_response_received`, `llm_decision_decoded`, `skill_step_executed`, `final_answer_synthesis_*`, etc.
- Correlation via `run_id`, `trace_id`, `span_id`

**Human-oriented**: `runs/<run_id>/llm_transcript.log`
- Per-LLM-call blocks with: turn, attempt, call site, provider, model, status
- Includes raw request/response, decode mapping, token usage, latency
- Call site tagged: `decision_loop` or `final_answer_synthesis`

Assessment: Excellent. Every LLM call routes through `_invoke_llm_with_logging()`. Consistent across all call sites. Sanitization + redaction applied everywhere.

---

## 7. Security Findings

### Positives
- API keys loaded from env vars first, `.env` as fallback
- Pattern-based redaction on all logged content (events + transcript)
- Control character sanitization prevents redaction bypass
- Path traversal protection in disclosure engine (`find_out_of_tree_paths`)
- Command timeout enforcement (120s default)
- `.env` is gitignored

### Issues Found

| Issue | Severity | Detail |
|-------|----------|--------|
| Weak redaction patterns | MEDIUM | Only matches `api_key`, `token`, `authorization: bearer`. Misses `api-key`, `apikey`, `secret`, `password`, `credentials`, `api_secret_key` |
| No command output redaction | MEDIUM | Stdout/stderr artifacts from `run_command` are written without redaction — could leak secrets if a command echoes env vars |
| Real API key in .env | INFO | `.env` contains a live Anthropic key — gitignored but worth rotating if ever exposed |

---

## 8. Testing Gaps

### What's Tested (12 test files, good component coverage)
- Decoder logic (aliases, defaults, normalization)
- Logging mechanics (JSONL, transcript, sanitization)
- Config loading (env vars, .env fallback)
- Retry logic (backoff curves)
- Skill parsing and routing
- Prompt budget computation

### What's NOT Tested

| Gap | Risk |
|-----|------|
| End-to-end runs with real/mock provider | HIGH — no integration tests |
| Final answer synthesis flow | MEDIUM — entire synthesis path untested |
| Self-handoff detection & recovery | MEDIUM — complex logic with no tests |
| Multi-turn disclosure propagation | MEDIUM — state accumulation untested |
| Provider-specific behavior divergence | LOW — both mocked identically |
| Token budget enforcement/truncation | LOW — logged but not enforced |

---

## 9. Summary

### Strengths
1. **Genuinely generic** — Zero hardcoded skill names in orchestration logic
2. **Clean provider abstraction** — Anthropic and Gemini share identical orchestration semantics
3. **Progressive disclosure works** — Context revealed incrementally, catalog stays lightweight
4. **Excellent observability** — Dual-layer logging with consistent call-site tagging
5. **Data-driven skill behavior** — Action aliases and default params flow through metadata, not code branches
6. **Robust decoder** — Handles model variation gracefully with alias resolution, type inference, and safe fallbacks

### Weaknesses / Gaps
1. **No native tool use** — Neither Anthropic's `tools` parameter nor Gemini's function calling is used; JSON-in-prompt is more fragile
2. **No MCP integration** — Cannot connect to external tool servers
3. **Redaction patterns too narrow** — Only covers 3 secret patterns; needs broader coverage
4. **Command output not redacted** — Stdout artifacts could leak secrets
5. **Testing gaps** — No end-to-end tests, no synthesis tests, no self-handoff recovery tests
6. **Orchestrator size** — `orchestrator.py` at ~1,500 lines is a monolith; could benefit from decomposition
7. **Token budget not enforced** — Logged but prompts can still exceed budget
8. **Self-handoff recovery preferred list** — Encodes assumptions about "good" action names; degrades gracefully but is a soft coupling

### Recommendations (Prioritized)
1. Consider native tool use — structured guarantees and better model grounding
2. Add MCP support — extensible external tool integration
3. Broaden redaction patterns — add `secret`, `password`, `credentials`, `apikey`, `api-key`
4. Redact command outputs — apply sanitization pipeline to stdout/stderr artifacts
5. Add integration tests — end-to-end with a mock provider returning realistic sequences
6. Decompose orchestrator — extract turn execution, synthesis, and self-handoff into focused modules
7. Enforce token budget — truncate or warn when prompt exceeds allocated tokens
