from __future__ import annotations

from pathlib import Path

from agent.config import (
    AgentConfig,
    discover_config_path,
    get_provider_api_key,
    load_config,
    write_default_config,
)


def test_load_default_config_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config(None)
    assert isinstance(config, AgentConfig)
    assert config.model.provider in {"anthropic", "gemini"}


def test_config_discovery_prefers_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "agent.yaml"
    local.write_text("model:\n  provider: anthropic\n", encoding="utf-8")
    discovered = discover_config_path(None)
    assert discovered == local


def test_write_default_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "agent.yaml"
    write_default_config(path)
    config = load_config(path)
    assert config.logging.jsonl_dir == "./runs"


def test_provider_api_key_lookup(monkeypatch) -> None:
    config = AgentConfig()
    monkeypatch.setenv("ANTHROPIC_API_KEY", " abc ")
    assert get_provider_api_key(config, "anthropic") == "abc"
