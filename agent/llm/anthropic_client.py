from __future__ import annotations

import json
import time

from agent.llm.base_client import BaseLlmClient, LlmResult
from agent.types import LlmRequestMeta


class AnthropicClient(BaseLlmClient):
    provider = "anthropic"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete_structured(
        self, prompt: str, model: str, max_tokens: int, attempt: int
    ) -> LlmResult:
        start = time.perf_counter()
        try:
            import anthropic  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("anthropic package is not installed") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        content_parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                content_parts.append(text)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage", None)
        meta = LlmRequestMeta(
            provider="anthropic",
            model=model,
            attempt=attempt,
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
        )

        text_data = "\n".join(content_parts).strip()
        if not text_data:
            return LlmResult(data={}, meta=meta)

        try:
            return LlmResult(data=json.loads(text_data), meta=meta)
        except json.JSONDecodeError:
            return LlmResult(data=text_data, meta=meta)
