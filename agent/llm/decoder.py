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
    "list_files": "run_command",
    "find_markdown_files": "run_command",
    "identify_markdown_files": "run_command",
    "read_file": "run_command",
    "read_file_content": "run_command",
    "extract_sections": "run_command",
    "extract_key_sections": "run_command",
    "generate_summary": "run_command",
    "aggregate_summaries": "run_command",
    "request_disclosure": "ask_user",
    "format_output": "finish",
    "summarize_output": "finish",
    "complete": "finish",
}

_LIST_MARKDOWN_COMMAND = (
    'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**"'
)

_DEFAULT_COMMAND_BY_ACTION: dict[str, str] = {
    "list_files": _LIST_MARKDOWN_COMMAND,
    "find_markdown_files": _LIST_MARKDOWN_COMMAND,
    "identify_markdown_files": _LIST_MARKDOWN_COMMAND,
    "read_file": (
        f'f=$({_LIST_MARKDOWN_COMMAND} | head -n 1); '
        'if [ -n "$f" ]; then echo "## $f"; sed -n "1,120p" "$f"; '
        'else echo "no markdown files found"; fi'
    ),
    "read_file_content": (
        f'f=$({_LIST_MARKDOWN_COMMAND} | head -n 1); '
        'if [ -n "$f" ]; then echo "## $f"; sed -n "1,120p" "$f"; '
        'else echo "no markdown files found"; fi'
    ),
    "extract_sections": (
        f'f=$({_LIST_MARKDOWN_COMMAND} | head -n 1); '
        'if [ -n "$f" ]; then echo "## $f"; echo "-- START --"; sed -n "1,40p" "$f"; '
        'echo "-- END --"; tail -n 40 "$f"; else echo "no markdown files found"; fi'
    ),
    "extract_key_sections": (
        f'f=$({_LIST_MARKDOWN_COMMAND} | head -n 1); '
        'if [ -n "$f" ]; then echo "## $f"; echo "-- START --"; sed -n "1,40p" "$f"; '
        'echo "-- END --"; tail -n 40 "$f"; else echo "no markdown files found"; fi'
    ),
    "generate_summary": (
        f'for f in $({_LIST_MARKDOWN_COMMAND} | head -n 10); do '
        'echo "## $f"; '
        'echo "line_count: $(wc -l < "$f")"; '
        'echo "headings:"; rg "^#" "$f" | head -n 5; '
        'echo; '
        "done"
    ),
    "aggregate_summaries": (
        f'for f in $({_LIST_MARKDOWN_COMMAND} | head -n 10); do '
        'echo "## $f"; '
        'echo "line_count: $(wc -l < "$f")"; '
        'echo "headings:"; rg "^#" "$f" | head -n 5; '
        'echo; '
        "done"
    ),
}


def _normalize_action_step(step: dict[str, Any], selected_skill: str | None) -> dict[str, Any]:
    raw_type_value = (
        step.get("type")
        or step.get("action")
        or step.get("step_type")
        or step.get("operation")
        or ""
    )
    raw_type = str(raw_type_value).strip()
    normalized_type = _ACTION_TYPE_ALIASES.get(raw_type, raw_type)
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
        command = normalized_step["params"].get("command")
        if not command and raw_type in _DEFAULT_COMMAND_BY_ACTION:
            normalized_step["params"]["command"] = _DEFAULT_COMMAND_BY_ACTION[raw_type]
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
