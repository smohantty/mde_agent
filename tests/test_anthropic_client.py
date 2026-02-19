from __future__ import annotations

import sys
import types

from agent.llm.anthropic_client import AnthropicClient


def _install_fake_anthropic_module(monkeypatch, captured: dict[str, object]) -> None:
    class FakeMessages:
        def create(self, **kwargs: object) -> object:
            captured["request_kwargs"] = kwargs
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text='{"ok": true}')],
                usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
            )

    class FakeAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs
            self.messages = FakeMessages()

    fake_module = types.ModuleType("anthropic")
    fake_module.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)


def test_anthropic_client_prefers_auth_token_when_both_credentials_present(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _install_fake_anthropic_module(monkeypatch, captured)

    client = AnthropicClient(api_key="api-key", auth_token="auth-token")
    client.complete_structured(
        prompt="hello",
        model="claude-sonnet-4-5",
        max_tokens=128,
        attempt=1,
    )

    assert captured["client_kwargs"] == {"auth_token": "auth-token"}


def test_anthropic_client_uses_api_key_when_auth_token_missing(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _install_fake_anthropic_module(monkeypatch, captured)

    client = AnthropicClient(api_key="api-key", auth_token=None)
    client.complete_structured(
        prompt="hello",
        model="claude-sonnet-4-5",
        max_tokens=128,
        attempt=1,
    )

    assert captured["client_kwargs"] == {"api_key": "api-key"}
