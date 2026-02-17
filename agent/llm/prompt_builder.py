from __future__ import annotations

import json
from dataclasses import dataclass

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
    disclosed_snippets: dict[str, str],
    step_results: list[StepExecutionResult],
    max_context_tokens: int,
    response_headroom_tokens: int,
) -> PromptBuildResult:
    run_state = {
        "executed_steps": [item.model_dump() for item in step_results],
        "executed_step_count": len(step_results),
    }
    candidates_payload = [item.model_dump() for item in candidates]
    disclosed_payload = disclosed_snippets

    instruction = (
        "You are an autonomous agent. Return a JSON object with keys: "
        "selected_skill, reasoning_summary, required_disclosure_paths, planned_actions. "
        "Each planned action must include type, params, expected_output."
    )

    prompt = "\n\n".join(
        [
            instruction,
            f"TASK:\n{task}",
            f"RUN_STATE:\n{json.dumps(run_state, ensure_ascii=True)}",
            f"CANDIDATE_SKILLS:\n{json.dumps(candidates_payload, ensure_ascii=True)}",
            f"DISCLOSED_CONTEXT:\n{json.dumps(disclosed_payload, ensure_ascii=True)}",
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
