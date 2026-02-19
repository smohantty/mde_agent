from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.llm.token_budget import compute_budget, estimate_tokens
from agent.types import SkillCandidate, StepExecutionResult, TokenBudget


@dataclass
class PromptBuildResult:
    prompt: str
    budget: TokenBudget
    estimated_input_tokens: int


def build_prompt(
    task: str,
    candidates: list[SkillCandidate],
    all_skill_frontmatter: list[dict[str, Any]],
    disclosed_snippets: dict[str, str],
    step_results: list[StepExecutionResult],
    max_context_tokens: int,
    response_headroom_tokens: int,
    session_context: list[dict[str, Any]] | None = None,
    blocked_skill_name: str | None = None,
    use_native_tools: bool = False,
    mcp_tools: list[dict[str, Any]] | None = None,
) -> PromptBuildResult:
    run_state = {
        "executed_steps": [item.model_dump() for item in step_results],
        "executed_step_count": len(step_results),
    }
    candidates_payload = [item.model_dump() for item in candidates]
    disclosed_payload = disclosed_snippets

    _shared_rules = (
        "Use ALL_SKILL_FRONTMATTER as the authoritative skill catalog. "
        "selected_skill MUST be either null or one of the listed skill names. "
        "Skill calls are OPTIONAL. "
        "Do not use call_skill unless delegation to a skill is required. "
        "If the task can be completed directly with run_command and/or finish, "
        "set selected_skill to null and do not emit call_skill. "
        "Avoid repetitive self-handoffs (calling the same selected skill "
        "repeatedly without new work). "
        "Allowed action types are EXACTLY: "
        "run_command, call_skill, ask_user, finish, mcp_call. "
        "Do not invent action types. "
        "For run_command, params MUST include a shell command in params.command. "
        "For mcp_call, params MUST include tool_name (string) and "
        "arguments (object matching the tool input_schema). "
        "Use mcp_call ONLY for tools listed in MCP_TOOLS. "
        "If the task is file-analysis, prefer run_command with rg/sed/head/tail commands. "
        "When searching files, exclude noisy directories like .venv, runs, and .git. "
        "Use ask_user only when truly blocked by missing required input. "
        "Respect RUN_CONSTRAINTS when present; they are mandatory."
    )

    if use_native_tools:
        instruction = (
            "You are an autonomous agent. "
            "Use the agent_decision tool to return your decision. "
            + _shared_rules
        )
    else:
        instruction = (
            "You are an autonomous agent. "
            "Return ONLY a JSON object (no markdown fences) with keys: "
            "selected_skill, reasoning_summary, required_disclosure_paths, "
            "planned_actions. "
            + _shared_rules
        )

    run_constraints: dict[str, Any] = {}
    if blocked_skill_name:
        run_constraints = {
            "blocked_call_skill_targets": [blocked_skill_name],
            "reason": (
                "This skill was already handed off in a previous turn without new executable work. "
                "Do not emit call_skill to this blocked target in this turn."
            ),
            "required_behavior": (
                "Return executable run_command and/or finish actions, "
                "or choose a different skill only if truly necessary."
            ),
        }

    prompt = "\n\n".join(
        [
            section
            for section in [
                instruction,
                f"TASK:\n{task}",
                f"RUN_STATE:\n{json.dumps(run_state, ensure_ascii=True)}",
                (
                    f"SESSION_CONTEXT:\n{json.dumps(session_context, ensure_ascii=True)}"
                    if session_context
                    else ""
                ),
                (
                    f"RUN_CONSTRAINTS:\n{json.dumps(run_constraints, ensure_ascii=True)}"
                    if run_constraints
                    else ""
                ),
                f"ALL_SKILL_FRONTMATTER:\n{json.dumps(all_skill_frontmatter, ensure_ascii=True)}",
                f"CANDIDATE_SKILLS:\n{json.dumps(candidates_payload, ensure_ascii=True)}",
                f"DISCLOSED_CONTEXT:\n{json.dumps(disclosed_payload, ensure_ascii=True)}",
                (
                    f"MCP_TOOLS:\n{json.dumps(mcp_tools, ensure_ascii=True)}"
                    if mcp_tools
                    else ""
                ),
            ]
            if section
        ]
    )

    budget = compute_budget(
        max_context_tokens=max_context_tokens,
        response_headroom_tokens=response_headroom_tokens,
        disclosed_text=json.dumps(disclosed_payload, ensure_ascii=True),
    )

    return PromptBuildResult(
        prompt=prompt,
        budget=budget,
        estimated_input_tokens=estimate_tokens(prompt),
    )
