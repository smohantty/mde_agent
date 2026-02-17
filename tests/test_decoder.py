from __future__ import annotations

from agent.llm.decoder import decode_model_decision


def test_decode_valid_dict() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "workspace-inventory",
            "reasoning_summary": "Need to inspect files",
            "required_disclosure_paths": [],
            "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
        }
    )
    assert decision.planned_actions[0].type == "finish"


def test_decode_embedded_json_string() -> None:
    raw = (
        'prefix {"selected_skill":"x","reasoning_summary":"ok","required_disclosure_paths":[],'
        '"planned_actions":[{"type":"finish","params":{},"expected_output":null}]}'
    )
    decision = decode_model_decision(raw)
    assert decision.reasoning_summary == "ok"


def test_decode_repair_adds_actions() -> None:
    decision = decode_model_decision({"selected_skill": "x", "reasoning_summary": "r"})
    assert decision.planned_actions


def test_decode_normalizes_execute_skill_action() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "run selected skill",
            "required_disclosure_paths": [],
            "planned_actions": [{"type": "execute_skill", "params": {}, "expected_output": None}],
        }
    )
    assert decision.planned_actions[0].type == "call_skill"
    assert decision.planned_actions[0].params.get("skill_name") == "content-summarizer"


def test_decode_normalizes_identify_markdown_files_to_command() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "find markdown",
            "required_disclosure_paths": [],
            "planned_actions": [
                {"type": "identify_markdown_files", "params": {}, "expected_output": None}
            ],
        }
    )
    assert decision.planned_actions[0].type == "run_command"
    command = str(decision.planned_actions[0].params.get("command"))
    assert 'rg --files -g "*.md"' in command
    assert '!.venv/**' in command


def test_decode_normalizes_list_files_to_command() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "find files",
            "required_disclosure_paths": [],
            "planned_actions": [{"type": "list_files", "params": {}, "expected_output": None}],
        }
    )
    assert decision.planned_actions[0].type == "run_command"
    command = str(decision.planned_actions[0].params.get("command"))
    assert 'rg --files -g "*.md"' in command
    assert '!.venv/**' in command


def test_decode_normalizes_read_file_to_command() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "read markdown file",
            "required_disclosure_paths": [],
            "planned_actions": [{"type": "read_file", "params": {}, "expected_output": None}],
        }
    )
    assert decision.planned_actions[0].type == "run_command"
    assert "sed -n" in str(decision.planned_actions[0].params.get("command"))


def test_decode_uses_action_key_when_type_missing() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "use action key",
            "required_disclosure_paths": [],
            "planned_actions": [{"action": "list_files", "params": {}}],
        }
    )
    assert decision.planned_actions[0].type == "run_command"


def test_decode_infers_run_command_when_type_missing_but_command_present() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "infer command type",
            "required_disclosure_paths": [],
            "planned_actions": [{"command": "echo hello"}],
        }
    )
    assert decision.planned_actions[0].type == "run_command"
    assert decision.planned_actions[0].params.get("command") == "echo hello"
