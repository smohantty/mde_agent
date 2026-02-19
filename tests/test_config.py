from __future__ import annotations

from pathlib import Path

from agent.config import (
    AgentConfig,
    discover_config_path,
    get_provider_api_key,
    get_provider_auth_token,
    load_config,
    provider_has_credentials,
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
    assert config.logging.llm_transcript_enabled is True
    assert config.logging.llm_transcript_filename == "llm_transcript.log"


def test_provider_api_key_lookup(monkeypatch) -> None:
    config = AgentConfig()
    monkeypatch.setenv("ANTHROPIC_API_KEY", " abc ")
    assert get_provider_api_key(config, "anthropic") == "abc"


def test_provider_api_key_lookup_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n", encoding="utf-8")

    config = AgentConfig()
    assert get_provider_api_key(config, "anthropic") == "from-dotenv"


def test_provider_api_key_env_overrides_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

    config = AgentConfig()
    assert get_provider_api_key(config, "anthropic") == "from-env"


def test_provider_auth_token_lookup(monkeypatch) -> None:
    config = AgentConfig()
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", " token-value ")
    assert get_provider_auth_token(config, "anthropic") == "token-value"


def test_provider_auth_token_lookup_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_AUTH_TOKEN=from-dotenv-token\n", encoding="utf-8")

    config = AgentConfig()
    assert get_provider_auth_token(config, "anthropic") == "from-dotenv-token"


def test_provider_auth_token_env_overrides_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_AUTH_TOKEN=from-dotenv-token\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "from-env-token")

    config = AgentConfig()
    assert get_provider_auth_token(config, "anthropic") == "from-env-token"


def test_provider_has_credentials_with_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert provider_has_credentials(AgentConfig(), "anthropic") is True


def test_provider_has_credentials_with_auth_token_only(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    assert provider_has_credentials(AgentConfig(), "anthropic") is True


def test_provider_has_credentials_with_neither(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert provider_has_credentials(AgentConfig(), "anthropic") is False
