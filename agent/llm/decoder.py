from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent.llm.structured_output import normalize_provider_output
from agent.types import ActionStep, ModelDecision


class DecodeError(RuntimeError):
    pass


_BASE_ACTION_TYPE_ALIASES: dict[str, str] = {
    "execute_skill": "call_skill",
    "invoke_skill": "call_skill",
    "use_skill": "call_skill",
    "run": "run_command",
    "run_shell": "run_command",
    "execute_command": "run_command",
    "request_disclosure": "ask_user",
    "format_output": "finish",
    "summarize_output": "finish",
    "complete": "finish",
}

def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_skill_aliases(
    skill_action_aliases: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    if not skill_action_aliases:
        return normalized

    for skill_name, aliases in skill_action_aliases.items():
        skill_key = _normalize_token(skill_name)
        if not skill_key:
            continue
        normalized_aliases: dict[str, str] = {}
        for raw_action, canonical_action in aliases.items():
            raw_key = _normalize_token(raw_action)
            canonical_key = _normalize_token(canonical_action)
            if not raw_key or not canonical_key:
                continue
            normalized_aliases[raw_key] = canonical_key
        if normalized_aliases:
            normalized[skill_key] = normalized_aliases
    return normalized


def _normalize_default_action_params(
    skill_default_action_params: dict[str, dict[str, dict[str, Any]]] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    if not skill_default_action_params:
        return normalized

    for skill_name, action_map in skill_default_action_params.items():
        skill_key = _normalize_token(skill_name)
        if not skill_key:
            continue
        normalized_action_map: dict[str, dict[str, Any]] = {}
        for action_name, params in action_map.items():
            action_key = _normalize_token(action_name)
            if not action_key:
                continue
            normalized_action_map[action_key] = {str(key): value for key, value in params.items()}
        if normalized_action_map:
            normalized[skill_key] = normalized_action_map
    return normalized


def _resolve_action_type(
    raw_type: str,
    selected_skill: str | None,
    skill_aliases: dict[str, dict[str, str]],
) -> str:
    raw_key = _normalize_token(raw_type)
    if not raw_key:
        return ""

    selected_skill_key = _normalize_token(selected_skill)
    if selected_skill_key:
        alias = skill_aliases.get(selected_skill_key, {}).get(raw_key)
        if alias:
            return alias

    for alias_map in skill_aliases.values():
        alias = alias_map.get(raw_key)
        if alias:
            return alias

    return _BASE_ACTION_TYPE_ALIASES.get(raw_key, raw_key)


def _resolve_default_params(
    raw_type: str,
    normalized_type: str,
    selected_skill: str | None,
    skill_default_action_params: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    selected_skill_key = _normalize_token(selected_skill)
    candidate_keys = [_normalize_token(raw_type), _normalize_token(normalized_type)]

    if selected_skill_key:
        action_map = skill_default_action_params.get(selected_skill_key, {})
        for action_key in candidate_keys:
            params = action_map.get(action_key)
            if params is not None:
                return dict(params)

    for action_map in skill_default_action_params.values():
        for action_key in candidate_keys:
            params = action_map.get(action_key)
            if params is not None:
                return dict(params)

    return None


def _normalize_action_step(
    step: dict[str, Any],
    selected_skill: str | None,
    skill_aliases: dict[str, dict[str, str]],
    skill_default_action_params: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    raw_type_value = (
        step.get("type")
        or step.get("action")
        or step.get("step_type")
        or step.get("operation")
        or ""
    )
    raw_type = str(raw_type_value).strip()
    normalized_type = _resolve_action_type(raw_type, selected_skill, skill_aliases)
    params = step.get("params")
    if not isinstance(params, dict):
        params = {}
    if step.get("skill_name") and "skill_name" not in params:
        params["skill_name"] = step.get("skill_name")
    for key in ("command", "cmd", "shell_command"):
        value = step.get(key)
        if isinstance(value, str) and value.strip() and "command" not in params:
            params["command"] = value

    if not normalized_type:
        if "command" in params:
            normalized_type = "run_command"
        elif "skill_name" in params:
            normalized_type = "call_skill"
        elif step.get("finish") is True or step.get("done") is True:
            normalized_type = "finish"
    normalized_step: dict[str, Any] = {
        "type": normalized_type,
        "params": params,
        "expected_output": step.get("expected_output", step.get("output")),
    }

    if normalized_type == "call_skill":
        if not normalized_step["params"].get("skill_name") and selected_skill:
            normalized_step["params"]["skill_name"] = selected_skill
    elif normalized_type == "run_command":
        default_params = _resolve_default_params(
            raw_type=raw_type,
            normalized_type=normalized_type,
            selected_skill=selected_skill,
            skill_default_action_params=skill_default_action_params,
        )
        if default_params:
            merged = dict(default_params)
            merged.update(normalized_step["params"])
            normalized_step["params"] = merged
        command = normalized_step["params"].get("command")
        if not command:
            # Unknown command-oriented action without command content is not executable.
            normalized_step["type"] = "ask_user"
            action_label = raw_type or normalized_type or "unknown"
            normalized_step["params"] = {"message": f"Non-executable action: {action_label}"}
    elif normalized_type not in {"ask_user", "finish"}:
        normalized_step["type"] = "ask_user"
        action_label = raw_type or "unknown"
        normalized_step["params"] = {"message": f"Unsupported action type: {action_label}"}

    return normalized_step


def _repair_payload(
    payload: dict[str, Any],
    skill_action_aliases: dict[str, dict[str, str]] | None = None,
    skill_default_action_params: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    normalized_skill_aliases = _normalize_skill_aliases(skill_action_aliases)
    normalized_skill_defaults = _normalize_default_action_params(skill_default_action_params)

    repaired = dict(payload)
    if "planned_actions" not in repaired:
        repaired["planned_actions"] = [{"type": "finish", "params": {}, "expected_output": None}]
    if "reasoning_summary" not in repaired:
        repaired["reasoning_summary"] = "No reasoning supplied by model"
    if "required_disclosure_paths" not in repaired:
        repaired["required_disclosure_paths"] = []

    selected_skill = repaired.get("selected_skill")
    if selected_skill is not None:
        selected_skill = str(selected_skill).strip() or None
        repaired["selected_skill"] = selected_skill

    actions = repaired.get("planned_actions")
    if isinstance(actions, list):
        normalized_actions = [
            _normalize_action_step(
                step,
                selected_skill,
                normalized_skill_aliases,
                normalized_skill_defaults,
            )
            for step in actions
            if isinstance(step, dict)
        ]
        repaired["planned_actions"] = normalized_actions or [
            {"type": "finish", "params": {}, "expected_output": None}
        ]

    return repaired


def decode_model_decision(
    raw: dict[str, Any] | str,
    *,
    skill_action_aliases: dict[str, dict[str, str]] | None = None,
    skill_default_action_params: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> ModelDecision:
    try:
        payload = normalize_provider_output(raw)
    except ValueError as exc:
        raise DecodeError(f"Unable to decode model decision: {exc}") from exc
    payload = _repair_payload(
        payload,
        skill_action_aliases=skill_action_aliases,
        skill_default_action_params=skill_default_action_params,
    )
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
