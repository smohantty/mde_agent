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
