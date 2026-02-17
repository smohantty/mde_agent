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
