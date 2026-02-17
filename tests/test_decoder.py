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


def test_decode_uses_skill_action_aliases_and_defaults() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "find files",
            "required_disclosure_paths": [],
            "planned_actions": [{"type": "list_files", "params": {}, "expected_output": None}],
        },
        skill_action_aliases={
            "content-summarizer": {
                "list_files": "run_command",
            }
        },
        skill_default_action_params={
            "content-summarizer": {
                "list_files": {
                    "command": 'rg --files -g "*.md"',
                }
            }
        },
    )
    assert decision.planned_actions[0].type == "run_command"
    assert decision.planned_actions[0].params.get("command") == 'rg --files -g "*.md"'


def test_decode_uses_action_key_when_type_missing() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "use action key",
            "required_disclosure_paths": [],
            "planned_actions": [{"action": "list_files", "params": {}}],
        },
        skill_action_aliases={
            "content-summarizer": {
                "list_files": "run_command",
            }
        },
        skill_default_action_params={
            "content-summarizer": {
                "list_files": {
                    "command": "echo listed",
                }
            },
        },
    )
    assert decision.planned_actions[0].type == "run_command"
    assert decision.planned_actions[0].params.get("command") == "echo listed"


def test_decode_unknown_action_without_defaults_demotes_to_ask_user() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": "content-summarizer",
            "reasoning_summary": "unsupported action",
            "required_disclosure_paths": [],
            "planned_actions": [{"type": "list_files", "params": {}, "expected_output": None}],
        }
    )
    assert decision.planned_actions[0].type == "ask_user"
    assert "Unsupported action type" in str(decision.planned_actions[0].params.get("message"))


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


def test_decode_action_type_finish_preserved() -> None:
    decision = decode_model_decision(
        {
            "selected_skill": None,
            "reasoning_summary": "direct tool path",
            "required_disclosure_paths": [],
            "planned_actions": [
                {
                    "action_type": "run_command",
                    "params": {"command": 'rg --files -g "*.md"'},
                },
                {
                    "action_type": "run_command",
                    "params": {"command": "echo summarize"},
                },
                {
                    "action_type": "finish",
                    "params": {"message": "done"},
                },
            ],
        }
    )
    assert [action.type for action in decision.planned_actions] == [
        "run_command",
        "run_command",
        "finish",
    ]
