from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.llm.base_client import LlmResult
from agent.llm.prompt_builder import build_prompt
from agent.llm.provider_router import ProviderRouter
from agent.llm.structured_output import build_agent_decision_tool_schema
from agent.runtime.orchestrator import Orchestrator
from agent.types import LlmRequestMeta

# ---------- schema tests ----------


def test_tool_schema_has_required_keys() -> None:
    schema = build_agent_decision_tool_schema()
    assert schema["name"] == "agent_decision"
    assert "input_schema" in schema
    props = schema["input_schema"]["properties"]
    assert "selected_skill" in props
    assert "reasoning_summary" in props
    assert "required_disclosure_paths" in props
    assert "planned_actions" in props
    assert set(schema["input_schema"]["required"]) == {
        "reasoning_summary",
        "planned_actions",
    }


def test_planned_actions_schema_enumerates_canonical_types() -> None:
    schema = build_agent_decision_tool_schema()
    items = schema["input_schema"]["properties"]["planned_actions"]["items"]
    action_enum = items["properties"]["type"]["enum"]
    assert set(action_enum) == {"run_command", "call_skill", "ask_user", "finish"}


# ---------- prompt builder tests ----------


def test_prompt_uses_tool_instruction_when_native() -> None:
    result = build_prompt(
        task="test task",
        candidates=[],
        all_skill_frontmatter=[],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
        use_native_tools=True,
    )
    assert "agent_decision tool" in result.prompt
    assert "Return ONLY a JSON object" not in result.prompt


def test_prompt_uses_json_instruction_when_not_native() -> None:
    result = build_prompt(
        task="test task",
        candidates=[],
        all_skill_frontmatter=[],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
        use_native_tools=False,
    )
    assert "Return ONLY a JSON object" in result.prompt
    assert "agent_decision tool" not in result.prompt


# ---------- orchestrator integration tests ----------


def _create_demo_skill(skills_dir: Path) -> None:
    skill_dir = skills_dir / "demo"
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    skill_md = "\n".join(
        [
            "---",
            "name: demo",
            "description: demo skill",
            "version: 0.1.0",
            "tags: [demo]",
            "allowed_tools: [run_command]",
            "---",
            "",
            "# Purpose",
            "Do demo",
            "",
        ]
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")


def test_native_mode_passes_tools_to_provider(tmp_path: Path, monkeypatch: Any) -> None:
    """When structured_output_mode is native_with_json_fallback, tools should be passed."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    received_tools: list[list[dict[str, Any]] | None] = []

    def _mock_complete_structured(
        self: object,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        received_tools.append(kwargs.get("tools"))  # type: ignore[arg-type]
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "Done",
                "required_disclosure_paths": [],
                "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=5,
                input_tokens=10,
                output_tokens=8,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.model.structured_output_mode = "native_with_json_fallback"

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir)
    assert result.status == "success"
    assert len(received_tools) >= 1
    # Decision loop call should have tools
    tools = received_tools[0]
    assert tools is not None
    assert tools[0]["name"] == "agent_decision"


def test_json_only_mode_does_not_pass_tools(tmp_path: Path, monkeypatch: Any) -> None:
    """When structured_output_mode is json_only, tools should be None."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    received_tools: list[list[dict[str, Any]] | None] = []

    def _mock_complete_structured(
        self: object,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        received_tools.append(kwargs.get("tools"))  # type: ignore[arg-type]
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "Done",
                "required_disclosure_paths": [],
                "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=5,
                input_tokens=10,
                output_tokens=8,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.model.structured_output_mode = "json_only"

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir)
    assert result.status == "success"
    assert len(received_tools) >= 1
    # Decision loop call should NOT have tools
    assert received_tools[0] is None


def test_dry_run_prompt_reflects_native_tool_mode(tmp_path: Path) -> None:
    """Dry run with native tool mode should produce a prompt mentioning the tool."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.structured_output_mode = "native_with_json_fallback"

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir, dry_run=True)
    assert result.status == "success"

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    prompt_artifact = run_dir / "dry_run_prompt.txt"
    assert prompt_artifact.exists()
    prompt_text = prompt_artifact.read_text(encoding="utf-8")
    assert "agent_decision tool" in prompt_text


def test_synthesis_call_does_not_use_tools(tmp_path: Path, monkeypatch: Any) -> None:
    """Final answer synthesis should always use json mode, not tool use."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls: list[dict[str, Any]] = []

    def _mock_complete_structured(
        self: object,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        calls.append({"prompt": prompt, "tools": kwargs.get("tools")})
        call_index = len(calls)
        if call_index == 1:
            return LlmResult(
                data={
                    "selected_skill": None,
                    "reasoning_summary": "run then finish",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "run_command",
                            "params": {"command": "printf 'EVIDENCE\\n'"},
                            "expected_output": None,
                        },
                        {
                            "type": "finish",
                            "params": {"summary": "task done"},
                            "expected_output": None,
                        },
                    ],
                },
                meta=LlmRequestMeta(
                    provider="anthropic",
                    model=model,
                    attempt=attempt,
                    latency_ms=6,
                    input_tokens=10,
                    output_tokens=11,
                ),
            )
        # Synthesis call
        return LlmResult(
            data={"final_answer": "Synthesized result."},
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=7,
                input_tokens=12,
                output_tokens=13,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.model.structured_output_mode = "native_with_json_fallback"

    result = Orchestrator(cfg).run(task="summarize", skills_dir=skills_dir)
    assert result.status == "success"
    assert len(calls) == 2
    # Decision loop call: tools should be present
    assert calls[0]["tools"] is not None
    # Synthesis call: tools should be None
    assert calls[1]["tools"] is None


def test_build_raw_model_request_forced_anthropic() -> None:
    """Forced tool use should set tool_choice type=tool."""
    tools = [build_agent_decision_tool_schema()]
    req = Orchestrator._build_raw_model_request(
        provider="anthropic",
        model="test-model",
        max_tokens=100,
        prompt="test",
        attempt=1,
        tools=tools,
        force_tool_use=True,
    )
    assert req["tools"] == ["agent_decision"]
    assert req["tool_choice"] == {"type": "tool", "name": "agent_decision"}


def test_build_raw_model_request_auto_anthropic() -> None:
    """Non-forced tool use should set tool_choice type=auto."""
    tools = [build_agent_decision_tool_schema()]
    req = Orchestrator._build_raw_model_request(
        provider="anthropic",
        model="test-model",
        max_tokens=100,
        prompt="test",
        attempt=1,
        tools=tools,
        force_tool_use=False,
    )
    assert req["tools"] == ["agent_decision"]
    assert req["tool_choice"] == {"type": "auto"}


def test_build_raw_model_request_forced_gemini() -> None:
    """Forced Gemini tool use should use ANY mode."""
    tools = [build_agent_decision_tool_schema()]
    req = Orchestrator._build_raw_model_request(
        provider="gemini",
        model="test-model",
        max_tokens=100,
        prompt="test",
        attempt=1,
        tools=tools,
        force_tool_use=True,
    )
    assert req["config"]["tool_config"] == {"function_calling_mode": "ANY"}
    assert "response_mime_type" not in req["config"]


def test_build_raw_model_request_auto_gemini() -> None:
    """Non-forced Gemini tool use should use AUTO mode."""
    tools = [build_agent_decision_tool_schema()]
    req = Orchestrator._build_raw_model_request(
        provider="gemini",
        model="test-model",
        max_tokens=100,
        prompt="test",
        attempt=1,
        tools=tools,
        force_tool_use=False,
    )
    assert req["config"]["tool_config"] == {"function_calling_mode": "AUTO"}


def test_build_raw_model_request_no_tools() -> None:
    """Without tools, request payload should use json mode."""
    req = Orchestrator._build_raw_model_request(
        provider="gemini",
        model="test-model",
        max_tokens=100,
        prompt="test",
        attempt=1,
    )
    assert "tools" not in req["config"]
    assert req["config"]["response_mime_type"] == "application/json"


# ---------- request-level fallback test ----------


def test_native_fallback_retries_without_tools_on_failure(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """native_with_json_fallback should retry without tools if native fails."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls: list[dict[str, Any]] = []

    def _mock_complete_structured(
        self: object,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        calls.append({"tools": kwargs.get("tools"), "prompt": prompt})
        # First call (with tools): simulate tool schema rejection
        if len(calls) == 1 and kwargs.get("tools") is not None:
            raise RuntimeError("tool schema rejected by provider")
        # Fallback call (no tools): succeed with JSON
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "Done via fallback",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {"type": "finish", "params": {}, "expected_output": None}
                ],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=5,
                input_tokens=10,
                output_tokens=8,
            ),
        )

    monkeypatch.setattr(
        ProviderRouter, "complete_structured", _mock_complete_structured
    )

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.model.structured_output_mode = "native_with_json_fallback"
    cfg.runtime.max_llm_retries = 0  # No retries, only fallback

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir)
    assert result.status == "success"
    # First call had tools, fallback call should not
    assert calls[0]["tools"] is not None
    assert calls[1]["tools"] is None
    # Fallback prompt should use JSON instruction, not tool instruction
    assert "agent_decision tool" not in calls[1]["prompt"]
    assert "Return ONLY a JSON object" in calls[1]["prompt"]

    # Verify fallback event was emitted
    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events_text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "native_tool_fallback" in events_text
