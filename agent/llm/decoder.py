from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent.llm.structured_output import normalize_provider_output
from agent.types import ActionStep, ModelDecision


class DecodeError(RuntimeError):
    pass


_ACTION_TYPE_ALIASES: dict[str, str] = {
    "execute_skill": "call_skill",
    "invoke_skill": "call_skill",
    "use_skill": "call_skill",
    "run": "run_command",
    "run_shell": "run_command",
    "execute_command": "run_command",
    "identify_markdown_files": "run_command",
    "request_disclosure": "ask_user",
    "format_output": "finish",
    "summarize_output": "finish",
    "complete": "finish",
}


def _normalize_action_step(step: dict[str, Any], selected_skill: str | None) -> dict[str, Any]:
    raw_type = str(step.get("type", "")).strip()
    normalized_type = _ACTION_TYPE_ALIASES.get(raw_type, raw_type)
    params = step.get("params")
    if not isinstance(params, dict):
        params = {}
    normalized_step: dict[str, Any] = {
        "type": normalized_type,
        "params": params,
        "expected_output": step.get("expected_output"),
    }

    if normalized_type == "call_skill":
        if not normalized_step["params"].get("skill_name") and selected_skill:
            normalized_step["params"]["skill_name"] = selected_skill
    elif normalized_type == "run_command":
        command = normalized_step["params"].get("command")
        if not command and raw_type == "identify_markdown_files":
            normalized_step["params"]["command"] = 'rg --files -g "*.md"'
        elif not command:
            # Unknown command-oriented action without command content is not executable.
            normalized_step["type"] = "ask_user"
            normalized_step["params"] = {"message": f"Non-executable action: {raw_type}"}
    elif normalized_type not in {"ask_user", "finish"}:
        normalized_step["type"] = "ask_user"
        normalized_step["params"] = {"message": f"Unsupported action type: {raw_type}"}

    return normalized_step


def _repair_payload(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(payload)
    if "planned_actions" not in repaired:
        repaired["planned_actions"] = [{"type": "finish", "params": {}, "expected_output": None}]
    if "reasoning_summary" not in repaired:
        repaired["reasoning_summary"] = "No reasoning supplied by model"
    if "required_disclosure_paths" not in repaired:
        repaired["required_disclosure_paths"] = []

    selected_skill = repaired.get("selected_skill")
    actions = repaired.get("planned_actions")
    if isinstance(actions, list):
        normalized_actions = [
            _normalize_action_step(step, selected_skill)
            for step in actions
            if isinstance(step, dict)
        ]
        repaired["planned_actions"] = normalized_actions or [
            {"type": "finish", "params": {}, "expected_output": None}
        ]

    return repaired


def decode_model_decision(raw: dict[str, Any] | str) -> ModelDecision:
    payload = normalize_provider_output(raw)
    payload = _repair_payload(payload)
    try:
        return ModelDecision.model_validate(payload)
    except ValidationError as exc:
        raise DecodeError(f"Unable to decode model decision: {exc}") from exc


def make_finish_decision(reason: str) -> ModelDecision:
    return ModelDecision(
        selected_skill=None,
        reasoning_summary=reason,
        required_disclosure_paths=[],
        planned_actions=[ActionStep(type="finish", params={}, expected_output=None)],
    )
