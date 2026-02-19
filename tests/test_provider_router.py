from __future__ import annotations

import agent.llm.provider_router as provider_router_module
from agent.llm.provider_router import ProviderRouter


def test_provider_router_prefers_auth_token_over_api_key(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeAnthropicClient:
        def __init__(self, api_key: str | None = None, auth_token: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["auth_token"] = auth_token

        def complete_structured(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("complete_structured should not be called in this test")

    monkeypatch.setattr(provider_router_module, "AnthropicClient", FakeAnthropicClient)
    router = ProviderRouter(
        anthropic_api_key="api-key",
        anthropic_auth_token="auth-token",
        gemini_api_key=None,
    )

    assert router.has_provider("anthropic")
    assert captured == {"api_key": None, "auth_token": "auth-token"}


def test_provider_router_uses_api_key_when_auth_token_missing(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeAnthropicClient:
        def __init__(self, api_key: str | None = None, auth_token: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["auth_token"] = auth_token

        def complete_structured(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("complete_structured should not be called in this test")

    monkeypatch.setattr(provider_router_module, "AnthropicClient", FakeAnthropicClient)
    router = ProviderRouter(
        anthropic_api_key="api-key",
        anthropic_auth_token=None,
        gemini_api_key=None,
    )

    assert router.has_provider("anthropic")
    assert captured == {"api_key": "api-key", "auth_token": None}
