from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent.llm.structured_output import normalize_provider_output
from agent.types import ActionStep, ModelDecision


class DecodeError(RuntimeError):
    pass


def _repair_payload(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(payload)
    if "planned_actions" not in repaired:
        repaired["planned_actions"] = [{"type": "finish", "params": {}, "expected_output": None}]
    if "reasoning_summary" not in repaired:
        repaired["reasoning_summary"] = "No reasoning supplied by model"
    if "required_disclosure_paths" not in repaired:
        repaired["required_disclosure_paths"] = []
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
