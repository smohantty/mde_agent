from __future__ import annotations

from agent.llm.anthropic_client import AnthropicClient
from agent.llm.base_client import BaseLlmClient, LlmResult
from agent.llm.gemini_client import GeminiClient


class ProviderRouter:
    def __init__(self, anthropic_api_key: str | None, gemini_api_key: str | None) -> None:
        self._clients: dict[str, BaseLlmClient] = {}
        if anthropic_api_key:
            self._clients["anthropic"] = AnthropicClient(anthropic_api_key)
        if gemini_api_key:
            self._clients["gemini"] = GeminiClient(gemini_api_key)

    def has_provider(self, provider: str) -> bool:
        return provider in self._clients

    def complete_structured(
        self, provider: str, prompt: str, model: str, max_tokens: int, attempt: int
    ) -> LlmResult:
        if provider not in self._clients:
            raise RuntimeError(f"Provider is not configured: {provider}")
        return self._clients[provider].complete_structured(prompt, model, max_tokens, attempt)
