from __future__ import annotations

from dataclasses import dataclass

from agent.types import TokenBudget


@dataclass
class PromptChunks:
    system_prompt: str
    task: str
    run_state_summary: str
    skill_metadata: str
    disclosed_content: str


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def compute_budget(
    max_context_tokens: int, response_headroom_tokens: int, disclosed_text: str
) -> TokenBudget:
    available = max(max_context_tokens - response_headroom_tokens, 0)
    disclosed_tokens = estimate_tokens(disclosed_text)
    disclosed_tokens = min(disclosed_tokens, max(available // 2, 0))

    return TokenBudget(
        max_context_tokens=max_context_tokens,
        response_headroom_tokens=response_headroom_tokens,
        allocated_prompt_tokens=available,
        allocated_disclosure_tokens=disclosed_tokens,
    )
