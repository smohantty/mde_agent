from __future__ import annotations

import json
import re
from typing import Any


def extract_json_payload(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    candidate = match.group(0)
    try:
        loaded = json.loads(candidate)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        return None
    return None


def normalize_provider_output(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    payload = extract_json_payload(raw)
    if payload is not None:
        return payload
    raise ValueError("Could not normalize provider output to JSON object")


def build_agent_decision_tool_schema() -> dict[str, Any]:
    """Return a tool definition whose input schema matches ModelDecision."""
    return {
        "name": "agent_decision",
        "description": (
            "Return the agent's decision including skill selection, "
            "reasoning, disclosure requests, and planned actions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selected_skill": {
                    "type": ["string", "null"],
                    "description": "Skill name from catalog, or null if no skill needed",
                },
                "reasoning_summary": {
                    "type": "string",
                    "description": "Brief reasoning for the decision",
                },
                "required_disclosure_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths to request for deeper context",
                },
                "planned_actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "run_command",
                                    "call_skill",
                                    "ask_user",
                                    "finish",
                                    "mcp_call",
                                ],
                            },
                            "params": {"type": "object"},
                            "expected_output": {"type": ["string", "null"]},
                        },
                        "required": ["type", "params"],
                    },
                },
            },
            "required": ["reasoning_summary", "planned_actions"],
        },
    }
