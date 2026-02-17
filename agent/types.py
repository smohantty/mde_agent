from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ActionType = Literal["call_skill", "run_command", "ask_user", "finish"]
ResponseKind = Literal["skill_call", "tool_call", "response"]
LlmTranscriptStatus = Literal["success", "request_failed", "decode_failed"]


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


class LlmTranscriptBudget(BaseModel):
    max_context_tokens: int
    response_headroom_tokens: int
    allocated_prompt_tokens: int
    allocated_disclosure_tokens: int


class LlmTranscriptUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


class LlmTranscriptRecord(BaseModel):
    turn_index: int
    attempt: int
    provider: Literal["anthropic", "gemini"]
    model: str
    status: LlmTranscriptStatus
    raw_request_text: str | None = None
    prompt_text: str
    response_text: str | None = None
    prompt_estimated_tokens: int
    budget: LlmTranscriptBudget
    disclosed_paths: list[str] = Field(default_factory=list)
    usage: LlmTranscriptUsage = Field(default_factory=LlmTranscriptUsage)
    decode_success: bool = False
    selected_skill: str | None = None
    raw_action_types: list[str] = Field(default_factory=list)
    planned_action_types: list[ActionType] = Field(default_factory=list)
    required_disclosure_paths: list[str] = Field(default_factory=list)
    response_kind: ResponseKind = "response"
    response_kind_reason: str | None = None
    error: str | None = None
    retryable: bool | None = None


class EventRecord(BaseModel):
    run_id: str
    trace_id: str
    span_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    redaction_mode: Literal["full", "redacted"] = "redacted"
