from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent.cli import app
from agent.runtime.orchestrator import Orchestrator, PreparedSkillsContext, RunResult


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


def test_chat_reuses_prepared_skills_and_carries_session_context(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_calls: list[Path] = []
    run_calls: list[dict[str, object]] = []

    def _fake_prepare(self, skills_dir: Path) -> PreparedSkillsContext:
        prepare_calls.append(skills_dir)
        return PreparedSkillsContext(
            resolved_skills_dir=skills_dir.resolve(),
            skills=[],
            skill_action_aliases={},
            skill_default_action_params={},
            all_skill_frontmatter=[],
        )

    def _fake_run(self, *args, **kwargs) -> RunResult:
        run_index = len(run_calls) + 1
        run_calls.append(
            {
                "task": kwargs.get("task"),
                "session_context": kwargs.get("session_context"),
                "prepared_skills": kwargs.get("prepared_skills"),
            }
        )
        return RunResult(
            run_id=f"run-{run_index}",
            status="success",
            message=f"done-{run_index}",
            events_path=tmp_path / "runs" / f"run-{run_index}" / "events.jsonl",
            llm_transcript_path=tmp_path / "runs" / f"run-{run_index}" / "llm_transcript.log",
        )

    monkeypatch.setattr(Orchestrator, "prepare_skills", _fake_prepare)
    monkeypatch.setattr(Orchestrator, "run", _fake_run)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["chat", "--skills-dir", "./skills"],
        input="first task\nsecond task\n",
    )
    assert result.exit_code == 0
    assert len(prepare_calls) == 1
    assert len(run_calls) == 2
    assert run_calls[0]["session_context"] == []
    second_context = run_calls[1]["session_context"]
    assert isinstance(second_context, list)
    assert second_context
    assert second_context[0]["task"] == "first task"


def test_chat_reload_skills_each_task(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_calls: list[Path] = []

    def _fake_prepare(self, skills_dir: Path) -> PreparedSkillsContext:
        prepare_calls.append(skills_dir)
        return PreparedSkillsContext(
            resolved_skills_dir=skills_dir.resolve(),
            skills=[],
            skill_action_aliases={},
            skill_default_action_params={},
            all_skill_frontmatter=[],
        )

    def _fake_run(self, *args, **kwargs) -> RunResult:
        run_index = len(prepare_calls)
        return RunResult(
            run_id=f"run-{run_index}",
            status="success",
            message="ok",
            events_path=tmp_path / "runs" / f"run-{run_index}" / "events.jsonl",
        )

    monkeypatch.setattr(Orchestrator, "prepare_skills", _fake_prepare)
    monkeypatch.setattr(Orchestrator, "run", _fake_run)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["chat", "--skills-dir", "./skills", "--reload-skills-each-task"],
        input="task one\ntask two\n",
    )
    assert result.exit_code == 0
    assert len(prepare_calls) == 2
