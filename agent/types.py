from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ActionType = Literal["call_skill", "run_command", "ask_user", "finish"]


class SkillMetadata(BaseModel):
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    version: str = "0.1.0"
    allowed_tools: list[str] = Field(default_factory=list)
    references_index: list[str] = Field(default_factory=list)
    action_aliases: dict[str, str] = Field(default_factory=dict)
    default_action_params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SkillCandidate(BaseModel):
    skill_name: str
    score: float
    reason: str


class TokenBudget(BaseModel):
    max_context_tokens: int
    response_headroom_tokens: int
    allocated_prompt_tokens: int
    allocated_disclosure_tokens: int


class ActionStep(BaseModel):
    type: ActionType
    params: dict[str, Any] = Field(default_factory=dict)
    expected_output: str | None = None


class ModelDecision(BaseModel):
    selected_skill: str | None = None
    reasoning_summary: str
    required_disclosure_paths: list[str] = Field(default_factory=list)
    planned_actions: list[ActionStep] = Field(default_factory=list)


class StepExecutionResult(BaseModel):
    step_id: str
    exit_code: int
    stdout_summary: str = ""
    stderr_summary: str = ""
    retry_count: int = 0
    status: Literal["success", "failed", "skipped"]


class LlmRequestMeta(BaseModel):
    provider: Literal["anthropic", "gemini"]
    model: str
    attempt: int
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class EventRecord(BaseModel):
    run_id: str
    trace_id: str
    span_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    redaction_mode: Literal["full", "redacted"] = "redacted"
