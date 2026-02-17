from __future__ import annotations

import json
from pathlib import Path

from agent.config import AgentConfig
from agent.llm.base_client import LlmResult
from agent.llm.provider_router import ProviderRouter
from agent.runtime.orchestrator import Orchestrator
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


def test_orchestrator_missing_key_fails_fast(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)

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


def test_normalize_markdown_find_command() -> None:
    normalized = Orchestrator._normalize_command("find . -type f -name '*.md' | head -20")
    assert 'rg --files -g "*.md"' in normalized
    assert "!.venv/**" in normalized
    assert "| head -n 20" in normalized


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
    assert any(event["event_type"] == "run_finished" for event in events)
