from __future__ import annotations

import json
import time

from agent.llm.base_client import BaseLlmClient, LlmResult
from agent.types import LlmRequestMeta


class GeminiClient(BaseLlmClient):
    provider = "gemini"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete_structured(
        self, prompt: str, model: str, max_tokens: int, attempt: int
    ) -> LlmResult:
        start = time.perf_counter()
        try:
            from google import genai  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("google-genai package is not installed") from exc

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "max_output_tokens": max_tokens,
            },
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        text_data = (getattr(response, "text", "") or "").strip()
        usage = getattr(response, "usage_metadata", None)

        meta = LlmRequestMeta(
            provider="gemini",
            model=model,
            attempt=attempt,
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
        )

        if not text_data:
            return LlmResult(data={}, meta=meta)

        try:
            return LlmResult(data=json.loads(text_data), meta=meta)
        except json.JSONDecodeError:
            return LlmResult(data=text_data, meta=meta)
