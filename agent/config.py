from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

ProviderName = Literal["anthropic", "gemini"]


class ProviderConfig(BaseModel):
    api_key_env: str
    auth_token_env: str | None = None


class ModelConfig(BaseModel):
    provider: ProviderName = "anthropic"
    name: str = "claude-sonnet-4-5"
    max_tokens: int = 4096
    max_context_tokens: int = 32000
    response_headroom_tokens: int = 2000
    structured_output_mode: Literal[
        "json_only", "native_with_json_fallback", "native_only"
    ] = "native_with_json_fallback"
    providers: dict[ProviderName, ProviderConfig] = Field(
        default_factory=lambda: {
            "anthropic": ProviderConfig(
                api_key_env="ANTHROPIC_API_KEY",
                auth_token_env="ANTHROPIC_AUTH_TOKEN",
            ),
            "gemini": ProviderConfig(api_key_env="GEMINI_API_KEY"),
        }
    )


class RuntimeConfig(BaseModel):
    profile: str = "permissive"
    shell_linux: str = "/bin/bash"
    shell_windows: str = "pwsh"
    timeout_seconds: int = 120
    max_turns: int = 8
    max_llm_retries: int = 3
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 8.0
    on_step_failure: str = "retry_once_then_fallback_then_abort"
    signal_grace_seconds: int = 10


class SkillsConfig(BaseModel):
    dir: str = "./skills"
    prefilter_top_k: int = 8
    prefilter_min_score: int = 55
    prefilter_zero_candidate_strategy: Literal["fallback_all_skills", "fail_fast"] = (
        "fallback_all_skills"
    )
    disclosure_max_reference_bytes: int = 120000
    disclosure_max_reference_tokens: int = 4000


class LoggingConfig(BaseModel):
    level: str = "info"
    jsonl_dir: str = "./runs"
    run_id_pattern: str = "YYYYMMDD-HHMMSS-<short-uuid>"
    debug_llm_bodies: bool = False
    sanitize_control_chars: bool = True
    redact_secrets: bool = True
    llm_transcript_enabled: bool = True
    llm_transcript_filename: str = "llm_transcript.log"


class McpServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 30


class McpConfig(BaseModel):
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    enabled: bool = True
    tool_call_timeout_seconds: int = 60


class AgentConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)


class ConfigError(RuntimeError):
    pass


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].strip()
    if "=" not in text:
        return None

    key, raw_value = text.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = raw_value.strip()
    if value and value[0] in {"'", '"'} and value[-1:] == value[0]:
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()

    return key, value.strip()


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def discover_config_path(config_override: Path | None = None) -> Path | None:
    if config_override is not None:
        return config_override.resolve()

    candidates = [
        Path("./agent.yaml"),
        Path("~/.config/agent/agent.yaml").expanduser(),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file must contain a mapping: {path}")
    return raw


def load_config(config_override: Path | None = None) -> AgentConfig:
    path = discover_config_path(config_override)
    if path is None:
        return AgentConfig()
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    data = _load_yaml(path)
    try:
        return AgentConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config at {path}: {exc}") from exc


def write_default_config(path: Path, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise ConfigError(f"Config file already exists: {path}")

    config = AgentConfig()
    serialized = yaml.safe_dump(config.model_dump(mode="python"), sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")


def get_provider_api_key(config: AgentConfig, provider: ProviderName) -> str | None:
    env_name = config.model.providers[provider].api_key_env
    return _get_env_or_dotenv(env_name)


def _get_env_or_dotenv(env_name: str | None) -> str | None:
    if not env_name:
        return None
    value = os.getenv(env_name)
    if value is None:
        dotenv_values = _read_dotenv(Path(".env"))
        value = dotenv_values.get(env_name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def get_provider_auth_token(config: AgentConfig, provider: ProviderName) -> str | None:
    env_name = config.model.providers[provider].auth_token_env
    return _get_env_or_dotenv(env_name)
