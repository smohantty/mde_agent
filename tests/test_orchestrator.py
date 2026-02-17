from __future__ import annotations

import json
from pathlib import Path

from agent.config import AgentConfig
from agent.runtime.orchestrator import Orchestrator


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
    assert '!.venv/**' in normalized
    assert "| head -n 20" in normalized
