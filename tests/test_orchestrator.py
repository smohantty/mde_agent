from __future__ import annotations

import json
from pathlib import Path

from agent.config import AgentConfig
from agent.llm.base_client import LlmResult
from agent.llm.provider_router import ProviderRouter
from agent.runtime.orchestrator import Orchestrator
from agent.skills.registry import SkillRegistry
from agent.types import LlmRequestMeta


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
    (skill_dir / "SKILL.md").write_text(
        skill_md,
        encoding="utf-8",
    )


def test_orchestrator_dry_run(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")

    result = Orchestrator(cfg).run(
        task="inventory files",
        skills_dir=skills_dir,
        dry_run=True,
    )
    assert result.status == "success"
    events = (Path(cfg.logging.jsonl_dir) / result.run_id / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "run_finished" in events


def test_orchestrator_uses_prepared_skills_without_registry_reload(
    tmp_path: Path, monkeypatch
) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    orchestrator = Orchestrator(cfg)
    prepared = orchestrator.prepare_skills(skills_dir)

    def _fail_load(self) -> list[object]:
        raise AssertionError(
            "SkillRegistry.load should not be called when prepared_skills is provided"
        )

    monkeypatch.setattr(SkillRegistry, "load", _fail_load)
    result = orchestrator.run(
        task="inventory files",
        skills_dir=skills_dir,
        dry_run=True,
        prepared_skills=prepared,
    )
    assert result.status == "success"


def test_orchestrator_appends_to_shared_run_dir_with_artifact_prefixes(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    orchestrator = Orchestrator(cfg)

    first = orchestrator.run(
        task="task one",
        skills_dir=skills_dir,
        dry_run=True,
        run_id_override="chat-session-run",
        artifact_prefix="task_0001_",
    )
    second = orchestrator.run(
        task="task two",
        skills_dir=skills_dir,
        dry_run=True,
        run_id_override="chat-session-run",
        artifact_prefix="task_0002_",
    )

    assert first.run_id == "chat-session-run"
    assert second.run_id == "chat-session-run"
    run_dir = Path(cfg.logging.jsonl_dir) / "chat-session-run"
    assert (run_dir / "task_0001_dry_run_prompt.txt").exists()
    assert (run_dir / "task_0002_dry_run_prompt.txt").exists()
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert events.count('"event_type": "run_started"') == 2


def test_orchestrator_missing_key_fails_fast(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.chdir(tmp_path)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"

    result = Orchestrator(cfg).run(
        task="inventory files",
        skills_dir=skills_dir,
        dry_run=False,
    )
    assert result.status == "failed"

    lines = (
        (Path(cfg.logging.jsonl_dir) / result.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    payloads = [json.loads(line) for line in lines]
    assert any(
        event["event_type"] == "run_failed"
        and event["payload"].get("reason") == "missing_provider_api_key"
        for event in payloads
    )


def test_orchestrator_accepts_anthropic_auth_token(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.chdir(tmp_path)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "auth-token")

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "done",
                "required_disclosure_paths": [],
                "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=5,
                input_tokens=10,
                output_tokens=10,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"


def test_normalize_find_command_with_rg(monkeypatch) -> None:
    monkeypatch.setattr(Orchestrator, "_rg_available", staticmethod(lambda: True))
    normalized = Orchestrator._normalize_command("find . -type f -name '*.md' | head -20")
    assert 'rg --files -g "*.md"' in normalized
    assert "!.venv/**" in normalized
    assert "| head -n 20" in normalized


def test_normalize_find_command_any_extension(monkeypatch) -> None:
    monkeypatch.setattr(Orchestrator, "_rg_available", staticmethod(lambda: True))
    normalized = Orchestrator._normalize_command("find . -type f -name '*.py' | head -10")
    assert 'rg --files -g "*.py"' in normalized
    assert "!.venv/**" in normalized
    assert "| head -n 10" in normalized


def test_normalize_rg_command_without_rg(monkeypatch) -> None:
    monkeypatch.setattr(Orchestrator, "_rg_available", staticmethod(lambda: False))
    normalized = Orchestrator._normalize_command('rg --files -g "*.md" -g "!.venv/**"')
    assert 'find . -type f -name "*.md"' in normalized
    assert "rg --files" not in normalized


def test_normalize_rg_search_without_rg(monkeypatch) -> None:
    monkeypatch.setattr(Orchestrator, "_rg_available", staticmethod(lambda: False))
    normalized = Orchestrator._normalize_command('rg "TODO" src/')
    assert 'grep -E "TODO"' in normalized
    assert "rg" not in normalized


def test_orchestrator_writes_transcript_success(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": "demo",
                "reasoning_summary": "Done",
                "required_disclosure_paths": [],
                "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=7,
                input_tokens=11,
                output_tokens=13,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"

    transcript_path = (
        Path(cfg.logging.jsonl_dir) / result.run_id / cfg.logging.llm_transcript_filename
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert transcript.count("=== LLM ATTEMPT START ===") == 1
    assert "Status: success" in transcript
    assert "--- Raw Model Request ---" in transcript
    assert "Decode Success: yes" in transcript
    assert "Response Kind: response" in transcript
    assert "Normalized Action Types (decoder output): finish" in transcript
    assert "Response Kind Mapping:" in transcript
    assert "TASK:" in transcript


def test_orchestrator_finish_uses_summary_field(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": "demo",
                "reasoning_summary": "Done",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {
                        "type": "finish",
                        "params": {"summary": "summary text"},
                        "expected_output": None,
                    }
                ],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=7,
                input_tokens=11,
                output_tokens=13,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"
    assert result.final_summary_path is not None
    assert result.final_summary_path.exists()
    assert "summary text" in result.final_summary_path.read_text(encoding="utf-8")

    events = (Path(cfg.logging.jsonl_dir) / result.run_id / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"type": "finish"' in events
    assert '"message": "summary text"' in events
    assert '"event_type": "run_finished"' in events
    assert '"final_summary": "summary text"' in events
    assert '"final_summary_artifact":' in events

    transcript_path = (
        Path(cfg.logging.jsonl_dir) / result.run_id / cfg.logging.llm_transcript_filename
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert "Finish Summary: summary text" in transcript


def test_orchestrator_tool_output_is_reused_before_finish(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = {"count": 0}

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return LlmResult(
                data={
                    "selected_skill": "demo",
                    "reasoning_summary": "collect output first",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "run_command",
                            "params": {"command": "printf 'RESULT_TOKEN\\n'"},
                            "expected_output": None,
                        }
                    ],
                },
                meta=LlmRequestMeta(
                    provider="anthropic",
                    model=model,
                    attempt=attempt,
                    latency_ms=7,
                    input_tokens=11,
                    output_tokens=13,
                ),
            )

        assert "RESULT_TOKEN" in prompt
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "used tool result",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {
                        "type": "finish",
                        "params": {"summary": "Final answer based on RESULT_TOKEN"},
                        "expected_output": None,
                    }
                ],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=8,
                input_tokens=12,
                output_tokens=14,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_turns = 4
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"
    assert calls["count"] == 2
    assert result.final_summary_path is not None

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    artifacts = sorted((run_dir / "artifacts").glob("*_stdout.txt"))
    assert artifacts
    assert "RESULT_TOKEN" in artifacts[0].read_text(encoding="utf-8")

    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert '"stdout_artifact":' in events
    assert '"final_summary": "Final answer based on RESULT_TOKEN"' in events


def test_orchestrator_synthesizes_final_answer_from_tool_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = {"count": 0}

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return LlmResult(
                data={
                    "selected_skill": None,
                    "reasoning_summary": "done in one turn",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "run_command",
                            "params": {"command": "printf 'PROJECT_TOKEN\\n'"},
                            "expected_output": None,
                        },
                        {
                            "type": "finish",
                            "params": {"summary": "task completed"},
                            "expected_output": None,
                        },
                    ],
                },
                meta=LlmRequestMeta(
                    provider="anthropic",
                    model=model,
                    attempt=attempt,
                    latency_ms=7,
                    input_tokens=11,
                    output_tokens=13,
                ),
            )
        assert "TOOL_EVIDENCE" in prompt
        assert "PROJECT_TOKEN" in prompt
        return LlmResult(
            data={"final_answer": "Project summary synthesized from PROJECT_TOKEN evidence."},
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=8,
                input_tokens=12,
                output_tokens=14,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    result = Orchestrator(cfg).run(task="summarize project", skills_dir=skills_dir)
    assert result.status == "success"
    assert calls["count"] == 2
    assert result.final_summary_path is not None
    final_text = result.final_summary_path.read_text(encoding="utf-8")
    assert "Project summary synthesized from PROJECT_TOKEN evidence." in final_text

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert '"event_type": "final_answer_synthesis_completed"' in events
    assert '"final_summary": "Project summary synthesized from PROJECT_TOKEN evidence."' in events


def test_orchestrator_writes_transcript_retry_attempts(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class NetworkError(Exception):
        pass

    call_count = {"value": 0}

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise NetworkError("network down")
        return LlmResult(
            data={
                "selected_skill": "demo",
                "reasoning_summary": "Retry success",
                "required_disclosure_paths": [],
                "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=9,
                input_tokens=12,
                output_tokens=14,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_llm_retries = 1
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"

    transcript_path = (
        Path(cfg.logging.jsonl_dir) / result.run_id / cfg.logging.llm_transcript_filename
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert transcript.count("=== LLM ATTEMPT START ===") == 2
    assert "Status: request_failed" in transcript
    assert "Retryable: True" in transcript
    assert "Status: success" in transcript


def test_orchestrator_writes_transcript_decode_failed(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data="not-json-response",
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=8,
                input_tokens=10,
                output_tokens=4,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "failed"
    assert result.message == "Failed to decode model response"

    transcript_path = (
        Path(cfg.logging.jsonl_dir) / result.run_id / cfg.logging.llm_transcript_filename
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert transcript.count("=== LLM ATTEMPT START ===") == 1
    assert "Status: decode_failed" in transcript
    assert "Decode Success: no" in transcript
    assert "not-json-response" in transcript


def test_orchestrator_recovers_from_repeated_self_handoff_loop(tmp_path: Path, monkeypatch) -> None:
    """Recovery with no default_action_params emits only a finish action."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": "demo",
                "reasoning_summary": "handoff",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {
                        "type": "call_skill",
                        "params": {"skill_name": "demo"},
                        "expected_output": None,
                    }
                ],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=5,
                input_tokens=9,
                output_tokens=7,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_turns = 4
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"
    assert result.message == "Run completed"

    events_path = Path(cfg.logging.jsonl_dir) / result.run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["event_type"] == "self_handoff_detected" for event in events)
    assert any(
        event["event_type"] == "self_handoff_recovery_applied"
        and "finish" in event["payload"].get("recovery_action_types", [])
        for event in events
    )
    # No run_command expected: skill has no default_action_params
    assert any(event["event_type"] == "run_finished" for event in events)


def _create_skill_with_defaults(skills_dir: Path) -> None:
    """Create a skill that has default_action_params for recovery testing."""
    skill_dir = skills_dir / "analyzer"
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    skill_md = "\n".join(
        [
            "---",
            "name: analyzer",
            "description: generic analyzer skill",
            "version: 0.1.0",
            "tags: [analysis]",
            "allowed_tools: [run_command]",
            "default_action_params:",
            "  list_files:",
            '    command: "ls -la"',
            "  check_status:",
            '    command: "echo ok"',
            "---",
            "",
            "# Purpose",
            "Analyze things",
            "",
        ]
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")


def test_self_handoff_recovery_uses_skill_defaults(tmp_path: Path, monkeypatch) -> None:
    """Recovery with default_action_params uses the skill's own commands."""
    skills_dir = tmp_path / "skills"
    _create_skill_with_defaults(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": "analyzer",
                "reasoning_summary": "handoff",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {
                        "type": "call_skill",
                        "params": {"skill_name": "analyzer"},
                        "expected_output": None,
                    }
                ],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=5,
                input_tokens=9,
                output_tokens=7,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_turns = 4
    result = Orchestrator(cfg).run(task="analyze project", skills_dir=skills_dir)
    assert result.status == "success"

    events_path = Path(cfg.logging.jsonl_dir) / result.run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["event_type"] == "self_handoff_recovery_applied" for event in events)
    # Recovery should run commands from the skill's default_action_params
    assert any(
        event["event_type"] == "skill_step_executed"
        and event["payload"].get("type") == "run_command"
        and event["payload"].get("status") == "success"
        for event in events
    )
    assert any(event["event_type"] == "run_finished" for event in events)


def test_all_llm_calls_logged_across_call_sites(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = {"count": 0}

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return LlmResult(
                data={
                    "selected_skill": None,
                    "reasoning_summary": "collect data first",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "run_command",
                            "params": {"command": "printf 'TOKEN_A\\n'"},
                            "expected_output": None,
                        }
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
        if calls["count"] == 2:
            assert "TOKEN_A" in prompt
            return LlmResult(
                data={
                    "selected_skill": None,
                    "reasoning_summary": "finish main loop",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "run_command",
                            "params": {"command": "printf 'TOKEN_B\\n'"},
                            "expected_output": None,
                        },
                        {
                            "type": "finish",
                            "params": {"summary": "Intermediate summary"},
                            "expected_output": None,
                        },
                    ],
                },
                meta=LlmRequestMeta(
                    provider="anthropic",
                    model=model,
                    attempt=attempt,
                    latency_ms=7,
                    input_tokens=12,
                    output_tokens=13,
                ),
            )
        assert "TOOL_EVIDENCE" in prompt
        return LlmResult(
            data={"final_answer": "Final answer from synthesis."},
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=8,
                input_tokens=14,
                output_tokens=15,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_turns = 4
    result = Orchestrator(cfg).run(task="summarize project", skills_dir=skills_dir)
    assert result.status == "success"
    assert calls["count"] == 3

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    request_events = [event for event in events if event["event_type"] == "llm_request_sent"]
    response_events = [event for event in events if event["event_type"] == "llm_response_received"]
    assert len(request_events) == 3
    assert len(response_events) == 3
    assert [event["payload"].get("call_site") for event in request_events] == [
        "decision_loop",
        "decision_loop",
        "final_answer_synthesis",
    ]
    assert [event["payload"].get("call_site") for event in response_events] == [
        "decision_loop",
        "decision_loop",
        "final_answer_synthesis",
    ]

    transcript = (run_dir / cfg.logging.llm_transcript_filename).read_text(encoding="utf-8")
    assert transcript.count("=== LLM ATTEMPT START ===") == 3
    assert transcript.count("Call Site: decision_loop") == 2
    assert transcript.count("Call Site: final_answer_synthesis") == 1

    llm_artifacts_dir = run_dir / "artifacts" / "llm"
    assert len(list(llm_artifacts_dir.glob("*_request.json"))) == 3
    assert len(list(llm_artifacts_dir.glob("*_response.json"))) == 3


def test_synthesis_request_failure_is_logged(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = {"count": 0}

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return LlmResult(
                data={
                    "selected_skill": None,
                    "reasoning_summary": "run then finish",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "run_command",
                            "params": {"command": "printf 'SYNTH_EVIDENCE\\n'"},
                            "expected_output": None,
                        },
                        {
                            "type": "finish",
                            "params": {"summary": "Fallback summary"},
                            "expected_output": None,
                        },
                    ],
                },
                meta=LlmRequestMeta(
                    provider="anthropic",
                    model=model,
                    attempt=attempt,
                    latency_ms=9,
                    input_tokens=10,
                    output_tokens=11,
                ),
            )
        raise RuntimeError("synthesis service unavailable")

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_llm_retries = 0
    result = Orchestrator(cfg).run(task="summarize project", skills_dir=skills_dir)
    assert result.status == "success"
    assert calls["count"] == 2

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    synth_requests = [
        event
        for event in events
        if event["event_type"] == "llm_request_sent"
        and event["payload"].get("call_site") == "final_answer_synthesis"
    ]
    assert len(synth_requests) == 1
    synth_failures = [
        event
        for event in events
        if event["event_type"] == "llm_request_failed"
        and event["payload"].get("call_site") == "final_answer_synthesis"
    ]
    assert len(synth_failures) == 1
    assert any(event["event_type"] == "final_answer_synthesis_failed" for event in events)

    transcript = (run_dir / cfg.logging.llm_transcript_filename).read_text(encoding="utf-8")
    assert "Call Site: final_answer_synthesis" in transcript
    assert "Status: request_failed" in transcript


def test_retry_attempts_logged_with_call_site(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class NetworkError(Exception):
        pass

    call_count = {"value": 0}

    def _mock_complete_structured(
        self,
        provider: str,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        **kwargs: object,
    ) -> LlmResult:
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise NetworkError("network down")
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "retry success",
                "required_disclosure_paths": [],
                "planned_actions": [{"type": "finish", "params": {}, "expected_output": None}],
            },
            meta=LlmRequestMeta(
                provider="anthropic",
                model=model,
                attempt=attempt,
                latency_ms=10,
                input_tokens=11,
                output_tokens=12,
            ),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.runtime.max_llm_retries = 1
    result = Orchestrator(cfg).run(task="inventory files", skills_dir=skills_dir)
    assert result.status == "success"
    assert call_count["value"] == 2

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    request_events = [event for event in events if event["event_type"] == "llm_request_sent"]
    assert len(request_events) == 2
    assert all(event["payload"].get("call_site") == "decision_loop" for event in request_events)

    retry_events = [event for event in events if event["event_type"] == "llm_retry_scheduled"]
    assert len(retry_events) == 1
    assert retry_events[0]["payload"].get("call_site") == "decision_loop"

    failed_events = [event for event in events if event["event_type"] == "llm_request_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["payload"].get("call_site") == "decision_loop"

    transcript = (run_dir / cfg.logging.llm_transcript_filename).read_text(encoding="utf-8")
    assert transcript.count("=== LLM ATTEMPT START ===") == 2
    assert transcript.count("Call Site: decision_loop") == 2
