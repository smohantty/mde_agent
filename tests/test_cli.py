from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent.cli import app
from agent.runtime.orchestrator import Orchestrator, RunResult


def test_run_prints_llm_transcript_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    events_path = tmp_path / "runs" / "run1" / "events.jsonl"
    transcript_path = tmp_path / "runs" / "run1" / "llm_transcript.jsonl"

    def _fake_run(self, *args, **kwargs) -> RunResult:
        return RunResult(
            run_id="run1",
            status="success",
            message="ok",
            events_path=events_path,
            llm_transcript_path=transcript_path,
        )

    monkeypatch.setattr(Orchestrator, "run", _fake_run)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "demo task", "--skills-dir", "./skills", "--dry-run"])
    assert result.exit_code == 0
    assert "LLM Transcript:" in result.output


def test_replay_with_llm_transcript(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    run_id = "run1"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_data = {"logging": {"jsonl_dir": str(tmp_path / "runs")}}
    Path("agent.yaml").write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")

    events_row = {
        "run_id": run_id,
        "trace_id": "trace1",
        "span_id": "span1",
        "timestamp": "2026-02-17T00:00:00+00:00",
        "event_type": "run_started",
        "payload": {"task": "demo"},
        "redaction_mode": "redacted",
    }
    (run_dir / "events.jsonl").write_text(json.dumps(events_row) + "\n", encoding="utf-8")

    transcript_row = {
        "run_id": run_id,
        "trace_id": "trace1",
        "span_id": "span2",
        "timestamp": "2026-02-17T00:00:01+00:00",
        "turn_index": 1,
        "attempt": 1,
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "status": "success",
        "prompt_hash": "abc",
        "response_hash": "def",
        "prompt_text": "prompt",
        "response_text": "response",
        "prompt_estimated_tokens": 100,
        "budget": {
            "max_context_tokens": 32000,
            "response_headroom_tokens": 2000,
            "allocated_prompt_tokens": 30000,
            "allocated_disclosure_tokens": 200,
        },
        "disclosed_paths": [],
        "usage": {"input_tokens": 10, "output_tokens": 11, "latency_ms": 12},
        "decode_success": True,
        "selected_skill": "demo",
        "planned_action_types": ["run_command"],
        "required_disclosure_paths": [],
        "response_kind": "tool_call",
        "error": None,
        "retryable": None,
    }
    (run_dir / "llm_transcript.jsonl").write_text(
        json.dumps(transcript_row) + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["replay", run_id, "--llm-transcript"])
    assert result.exit_code == 0
    assert "llm turn=1 attempt=1" in result.output
    assert "kind=tool_call" in result.output
