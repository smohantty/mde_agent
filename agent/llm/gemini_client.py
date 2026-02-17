from __future__ import annotations

import json
import time
from typing import Any

from agent.llm.base_client import BaseLlmClient, LlmResult
from agent.types import LlmRequestMeta


class GeminiClient(BaseLlmClient):
    provider = "gemini"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete_structured(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        attempt: int,
        tools: list[dict[str, Any]] | None = None,
        force_tool_use: bool = False,
    ) -> LlmResult:
        start = time.perf_counter()
        try:
            from google import genai  # type: ignore
            from google.genai import types as genai_types  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("google-genai package is not installed") from exc

        client = genai.Client(api_key=self.api_key)

        config: dict[str, Any] = {"max_output_tokens": max_tokens}

        if tools:
            gemini_decls = [
                genai_types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("input_schema"),
                )
                for t in tools
            ]
            config["tools"] = [genai_types.Tool(function_declarations=gemini_decls)]
            fc_mode = "ANY" if force_tool_use else "AUTO"
            config["tool_config"] = genai_types.ToolConfig(
                function_calling_config=genai_types.FunctionCallingConfig(
                    mode=fc_mode  # type: ignore[arg-type]
                )
            )
        else:
            config["response_mime_type"] = "application/json"

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,  # type: ignore[arg-type]
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage_metadata", None)

        meta = LlmRequestMeta(
            provider="gemini",
            model=model,
            attempt=attempt,
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=(
                getattr(usage, "candidates_token_count", None) if usage else None
            ),
        )

        # When tools were provided, try to extract a matching function_call.
        expected_names = {t["name"] for t in tools} if tools else set()
        if tools:
            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if content is None:
                    continue
                for part in getattr(content, "parts", None) or []:
                    fc = getattr(part, "function_call", None)
                    if fc is not None:
                        fc_name = getattr(fc, "name", None)
                        if fc_name in expected_names:
                            return LlmResult(data=dict(fc.args), meta=meta)
            if force_tool_use:
                raise RuntimeError(
                    "native_only: model did not return a function_call"
                )

        # Fallback: extract text content and parse as JSON.
        text_data = (getattr(response, "text", "") or "").strip()

        if not text_data:
            return LlmResult(data={}, meta=meta)

        try:
            return LlmResult(data=json.loads(text_data), meta=meta)
        except json.JSONDecodeError:
            return LlmResult(data=text_data, meta=meta)
