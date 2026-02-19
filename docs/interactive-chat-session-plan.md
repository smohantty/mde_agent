# Plan: Interactive Continuous CLI Session Mode (`agent chat`)

## Summary
Implement a CLI-only interactive mode where the agent waits for plain text input, executes each task to completion, then returns to waiting for the next input in the same process.

This replaces the earlier queue/worker direction for this feature.

Locked product behavior:
1. Plain generic text input (no command language required).
2. Session-wide context is retained across prompts.
3. Use predefined configured `skills.dir` and configured MCP setup.
4. Ctrl+C during run exits the whole process.
5. Session memory uses rolling summaries (not full raw history).
6. Skills are cached at chat-session start by default for performance; optional per-task reload mode is available.

## Public APIs / Interfaces / Types

## CLI surface
1. Add `agent chat` command as the interactive entrypoint.
2. `agent chat` options:
`--provider`, `--profile`, `--max-turns`, `--show-progress`, `--config`, optional `--skills-dir` override, `--reload-skills-each-task`.
3. Default skills path for chat:
CLI `--skills-dir` if provided, otherwise `config.skills.dir`.
4. Skill loading mode:
default is cached skills for whole session;
`--reload-skills-each-task` reparses `SKILL.md` before each task.

## Orchestrator and prompt interface changes
1. Extend `Orchestrator.run(...)` with optional `session_context` argument.
2. Extend `build_prompt(...)` with optional `session_context` argument.
3. Add new prompt section:
`SESSION_CONTEXT` serialized JSON, included on each task in chat mode.
4. Add reusable skill preparation path to avoid reparsing:
`Orchestrator.prepare_skills(skills_dir)` returns prepared skill context;
`Orchestrator.run(...)` accepts optional preloaded/prepared skills context.

## New runtime types/modules
1. Add `agent/runtime/chat_session.py`:
`ChatSessionMemory`, `SessionTaskRecord`, rolling-summary clipping logic.
2. Optional type additions in `agent/types.py` (if used broadly):
`SessionContextEntry` model for prompt payload consistency.
3. Add prepared skill context type (module-local or typed model), containing:
`skills`, `skill_action_aliases`, `skill_default_action_params`, `all_skill_frontmatter`, `resolved_skills_dir`.

## Detailed Design

## 1) Chat loop command
1. In `agent/cli.py`, implement `@app.command("chat")`.
2. Load config once at session start.
3. Resolve `skills_dir` once (CLI override else `cfg.skills.dir`).
4. Instantiate one `Orchestrator(cfg)` and one `ChatSessionMemory`.
5. Resolve skill strategy once:
if `--reload-skills-each-task` is false, call `orchestrator.prepare_skills(skills_dir)` once and reuse it for all prompts.
if true, do not cache and let each run load fresh skills.
6. Loop:
read one line from stdin;
ignore empty lines;
invoke `orchestrator.run(task=..., session_context=memory_payload, prepared_skills=...)`;
render run result and artifact paths;
append summarized result to memory;
return to prompt.
7. Exit behavior:
`KeyboardInterrupt` (Ctrl+C) exits process immediately with clean message and non-error exit code policy defined in implementation notes below.
`EOF` (Ctrl+D) exits cleanly.

## 2) Session context memory model
1. For each finished task, store:
`task_text`, `run_id`, `status`, `summary`, `timestamp`.
2. Summary source priority:
`final_summary.md` content (stripped) if present, else `RunResult.message`.
3. Rolling summary policy:
keep most recent N entries and trim each summary to M chars;
also enforce aggregate approximate token cap before prompt injection.
4. Memory is in-process only (ephemeral for that CLI session).

## 3) Prompt integration
1. Update `agent/llm/prompt_builder.py` to add `SESSION_CONTEXT` section when context exists.
2. Keep existing sections and rules unchanged.
3. Ensure `SESSION_CONTEXT` is lightweight JSON and does not include large artifacts.
4. Memory clipping happens before passing into prompt builder.

## 4) MCP and skills behavior in chat mode
1. No new MCP configuration model is needed.
2. Each chat task run uses existing orchestrator MCP flow:
if configured and enabled, connect tools and execute as normal.
3. Skills use session-level cache by default:
`SkillRegistry.load()` + derived prompt/decoder structures are computed once per chat session.
4. Optional hot-reload mode:
`--reload-skills-each-task` forces reparsing skills every task (useful while editing skills during a live session).
5. No queue/daemon/background worker components are introduced.

## 5) UX behavior
1. Prompt style:
simple `agent> ` input line.
2. No slash commands in v1 (generic text only).
3. Print per-task completion line:
success/failure, run_id, and paths (events, transcript, final summary when present).
4. Keep existing progress event renderer behavior during each task run.

## 6) Backward compatibility
1. Keep `agent run` unchanged (single-shot mode remains supported).
2. `agent chat` is additive and recommended for continuous interactive use.
3. Existing replay/config/skills commands remain unchanged.

## Implementation Steps (ordered)

1. Add chat memory module (`agent/runtime/chat_session.py`) with rolling summary + clipping utilities.
2. Add optional `session_context` parameter to `Orchestrator.run`.
3. Add `Orchestrator.prepare_skills(skills_dir)` and `prepared_skills` override path in `run(...)`.
4. Thread `session_context` into `build_prompt`.
5. Add optional `SESSION_CONTEXT` section to prompt builder.
6. Implement `agent chat` command loop in `agent/cli.py`, including `--reload-skills-each-task`.
7. Wire chat command to resolved config `skills.dir` by default and select cache vs reload path.
8. Add docs updates for chat usage and behavior, including skill cache tradeoff and reload flag.
9. Add/adjust tests for CLI chat flow, session context propagation, and skill cache behavior.
10. Run checks: `uv run ruff check .`, `uv run pyright`, `uv run pytest`.

## Test Cases and Scenarios

1. `agent chat` processes two sequential inputs and calls orchestrator twice.
2. Second task receives session context containing first task summary.
3. Empty input line is ignored and does not trigger a run.
4. Ctrl+D exits chat loop cleanly.
5. Ctrl+C exits chat process immediately.
6. Chat default skills dir comes from `config.skills.dir` when `--skills-dir` is absent.
7. `--skills-dir` override in chat is honored.
8. Prompt includes `SESSION_CONTEXT` only when context exists.
9. Rolling memory cap trims old entries and long summaries.
10. With default chat mode, skill parsing/preparation happens once for multiple prompts in a single session.
11. With `--reload-skills-each-task`, skill parsing runs once per prompt.
12. Non-regression: existing `agent run` and current tests continue passing.

## Important Changes to Public Interfaces/Types

1. `Orchestrator.run(...)`:
add `session_context: list[dict[str, Any]] | None = None`.
2. `build_prompt(...)`:
add `session_context: list[dict[str, Any]] | None = None`.
3. New runtime abstraction:
`ChatSessionMemory` and `SessionTaskRecord` for cross-task session state.
4. New orchestrator interfaces:
`prepare_skills(skills_dir)` and optional `prepared_skills` input to `run(...)`.
5. New CLI command:
`agent chat`.
6. New chat CLI option:
`--reload-skills-each-task`.

## Assumptions and Defaults

1. Session context is ephemeral (not persisted across restarts).
2. Generic plain text input only; no slash command system in v1.
3. Ctrl+C exits entire chat process by design.
4. Rolling summary defaults:
N recent tasks and token/char caps chosen conservatively to protect prompt size.
5. Default chat mode does not hot-reload skill file edits made after session start; use `--reload-skills-each-task` when live skill editing is required.
6. Chat mode remains CLI-only and uses existing orchestrator/MCP/skills mechanisms without introducing server/queue infrastructure.
