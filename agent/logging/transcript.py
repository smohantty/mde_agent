from __future__ import annotations

import threading
from pathlib import Path

from agent.types import LlmTranscriptRecord


class LlmTranscriptSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: LlmTranscriptRecord) -> None:
        payload = record.model_dump(mode="json")
        raw_action_types = self._join_list(payload.get("raw_action_types", []))
        planned_actions = self._join_list(payload.get("planned_action_types", []))
        disclosed_paths = self._join_list(payload.get("disclosed_paths", []))
        required_disclosure = self._join_list(payload.get("required_disclosure_paths", []))
        usage = payload.get("usage", {}) or {}
        budget = payload.get("budget", {}) or {}
        retryable = payload.get("retryable")

        block = [
            "=== LLM ATTEMPT START ===",
            f"Turn: {payload['turn_index']}",
            f"Attempt: {payload['attempt']}",
            f"Provider: {payload['provider']}",
            f"Model: {payload['model']}",
            f"Status: {payload['status']}",
            f"Response Kind: {payload['response_kind']}",
            f"Decode Success: {'yes' if payload['decode_success'] else 'no'}",
            f"Selected Skill: {payload.get('selected_skill') or 'none'}",
            f"Raw Action Types (from model response): {raw_action_types}",
            f"Normalized Action Types (decoder output): {planned_actions}",
            f"Disclosed Paths: {disclosed_paths}",
            f"Required Disclosure Paths: {required_disclosure}",
            f"Prompt Estimated Tokens: {payload['prompt_estimated_tokens']}",
            (
                "Budget: "
                f"max_context_tokens={budget.get('max_context_tokens')}, "
                f"response_headroom_tokens={budget.get('response_headroom_tokens')}, "
                f"allocated_prompt_tokens={budget.get('allocated_prompt_tokens')}, "
                f"allocated_disclosure_tokens={budget.get('allocated_disclosure_tokens')}"
            ),
            (
                "Usage: "
                f"input_tokens={usage.get('input_tokens')}, "
                f"output_tokens={usage.get('output_tokens')}, "
                f"latency_ms={usage.get('latency_ms')}"
            ),
            f"Retryable: {retryable if retryable is not None else 'n/a'}",
            f"Error: {payload.get('error') or 'none'}",
            f"Response Kind Mapping: {payload.get('response_kind_reason') or 'n/a'}",
            "",
            "--- Request Prompt ---",
            str(payload["prompt_text"]),
            "--- Raw Model Response ---",
            str(payload.get("response_text") or ""),
            "--- Decode Summary ---",
            f"selected_skill={payload.get('selected_skill') or 'none'}",
            f"response_kind={payload.get('response_kind')}",
            f"normalized_actions={planned_actions}",
            "=== LLM ATTEMPT END ===",
            "",
        ]
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(block))

    def replay(self) -> list[str]:
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        chunks = text.split("=== LLM ATTEMPT END ===")
        attempts: list[str] = []
        for chunk in chunks:
            cleaned = chunk.strip()
            if not cleaned:
                continue
            attempts.append(cleaned + "\n=== LLM ATTEMPT END ===")
        return attempts

    @staticmethod
    def _join_list(items: object) -> str:
        if not isinstance(items, list):
            return "none"
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if not cleaned:
            return "none"
        return ", ".join(cleaned)
