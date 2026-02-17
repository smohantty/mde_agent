# CLAUDE.md

Canonical agent guide for this repository.

This file defines how any coding agent (Claude, Codex, or similar) should reason about and modify this project.
`AGENT.md` is intentionally thin and points here.

## 1) Project Identity

This repository is a **generic skill-native agentic system**.

Primary goal:
- Accept a user task.
- Discover and load skills dynamically.
- Progressively disclose skill context.
- Let the LLM decide whether to use `skill_call`, `tool_call` (`run_command`), direct response, or finish.
- Execute actions and return a result.

This is **not** a hardcoded demo bot.
The architecture must remain provider-agnostic and skill-agnostic.

## 2) Non-Negotiable Design Rules

1. No skill-specific hacks.
- Do not add logic that keys off specific skill names (for example: `content-summarizer`) to force outcomes.
- Do not add one-off behavior to make a single demo pass.

2. Keep the system generic.
- Changes must work for arbitrary skills and arbitrary tasks.
- Skills are data; orchestrator logic is generic.

3. Keep provider abstraction intact.
- Anthropic and Gemini must use the same orchestration semantics.
- Provider differences belong in provider clients, not in agent policy logic.

4. Progressive disclosure is mandatory.
- Do not push full skill internals into initial prompt context.
- Catalog first, deeper context only on demand.

5. Preserve observability.
- Every LLM call path must stay observable.
- Logging and transcript behavior is a core product requirement.

## 3) Core Runtime Model

Main orchestration entrypoint:
- `agent/runtime/orchestrator.py`

High-level loop:
1. Load config and provider setup.
2. Load skills from skills directory.
3. Prefilter candidates (`SkillRouter`).
4. Stage-1 disclosure for top candidate (`DisclosureEngine`).
5. Build prompt (`build_prompt`).
6. Call LLM via centralized LLM invocation helper.
7. Decode model decision (`decode_model_decision`).
8. Execute planned actions (`run_command`, `call_skill`, `ask_user`, `finish`).
9. Optionally disclose more context and continue turn loop.
10. On finish, optionally synthesize final answer from tool evidence.

## 4) Skills Contract

Skills are loaded from local directories and parsed from `SKILL.md`.

Expected skill layout:
- `SKILL.md`
- `references/`
- `scripts/`

Progressive disclosure stages:
- Stage 0: metadata catalog (name/description/tags/tools/indexes).
- Stage 1: summary sections from `SKILL.md`.
- Stage 2: requested references/paths.
- Stage 3: script descriptors or executable artifacts when needed.

Important:
- `ALL_SKILL_FRONTMATTER` in prompt should remain lightweight catalog data.
- Detailed commands/internals should come from disclosed context or scripts on demand.

## 5) Action Semantics

Canonical action types:
- `run_command`
- `call_skill`
- `ask_user`
- `finish`

Interpretation rules:
- `selected_skill` can be `null`.
- `call_skill` is optional and only used when delegation is needed.
- `run_command` actions should be executable and validated.
- `finish` should include user-facing completion content.

Decoder responsibilities:
- Normalize provider/model variations to canonical actions.
- Avoid unsafe assumptions.
- Keep behavior generic via alias/default maps, not hardcoded skill names.

## 6) LLM Provider Model

Provider abstraction:
- `agent/llm/provider_router.py`
- `agent/llm/anthropic_client.py`
- `agent/llm/gemini_client.py`

Rules:
- All providers pass through shared orchestrator logic.
- Any provider-specific payload formatting stays in provider clients.
- Structured output expectations should remain consistent across providers.

## 7) Observability Requirements

Run outputs:
- `runs/<run_id>/events.jsonl`
- `runs/<run_id>/llm_transcript.log`
- `runs/<run_id>/artifacts/...`

Required behavior:
- Log all LLM calls across call sites (`decision_loop`, `final_answer_synthesis`, future sites).
- Include call site in LLM events and transcript entries.
- Keep transcript user-readable and events machine-oriented.

Do not remove or weaken:
- request/response boundaries,
- decode mapping visibility,
- retry/failure observability,
- redaction/sanitization safeguards.

## 8) Security and Secrets

Provider key resolution order:
1. Environment variable
2. Local `.env` fallback

Rules:
- Never log raw API keys.
- `.env` must stay gitignored.
- Redaction/sanitization must remain enabled for logged prompt/response artifacts.

## 9) Change Guidelines for Agents

When editing this repo:
1. Prefer minimal, generic changes over task-specific shortcuts.
2. Preserve compatibility with both providers.
3. Preserve progressive disclosure behavior.
4. Update tests when behavior changes.
5. Update docs when interfaces/logging change.

Before finishing changes, run:
- `uv run ruff check .`
- `uv run pyright`
- `uv run pytest`

## 10) Acceptance Bar for New Features

A feature is acceptable only if:
1. It works without naming or hardcoding a specific skill.
2. It preserves dynamic routing and progressive disclosure.
3. It does not assume a specific LLM provider.
4. It is observable in both events and transcript.
5. It keeps tests green.

## 11) What Not To Do

Do not:
- Inject large skill command blobs into base prompt context by default.
- Add emergency branches that only handle one demo task.
- Force skill calls when the model chooses a direct tool or finish path.
- Bypass the central LLM logging path.

