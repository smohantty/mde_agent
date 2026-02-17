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
    transcript_path = tmp_path / "runs" / "run1" / "llm_transcript.log"

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

    transcript_text = "\n".join(
        [
            "=== LLM ATTEMPT START ===",
            "Turn: 1",
            "Attempt: 1",
            "Provider: anthropic",
            "Model: claude-sonnet-4-5",
            "Status: success",
            "Response Kind: tool_call",
            "--- Prompt ---",
            "prompt",
            "--- Response ---",
            "response",
            "=== LLM ATTEMPT END ===",
        ]
    )
    (run_dir / "llm_transcript.log").write_text(transcript_text, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["replay", run_id, "--llm-transcript"])
    assert result.exit_code == 0
    assert "=== LLM ATTEMPT START ===" in result.output
    assert "Response Kind: tool_call" in result.output
