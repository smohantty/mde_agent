from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from agent.llm.token_budget import estimate_tokens
from agent.logging.redaction import summarize_text


@dataclass
class SessionTaskRecord:
    task: str
    run_id: str
    status: str
    summary: str
    timestamp: str

    def to_payload(self) -> dict[str, str]:
        return {
            "task": self.task,
            "run_id": self.run_id,
            "status": self.status,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }


class ChatSessionMemory:
    def __init__(
        self,
        *,
        max_entries: int = 12,
        max_summary_chars: int = 1200,
        max_context_tokens: int = 3000,
    ) -> None:
        self.max_entries = max_entries
        self.max_summary_chars = max_summary_chars
        self.max_context_tokens = max_context_tokens
        self._records: list[SessionTaskRecord] = []

    def append(
        self,
        *,
        task: str,
        run_id: str,
        status: str,
        summary: str | None,
    ) -> None:
        summary_text = (summary or "").strip()
        if not summary_text:
            summary_text = "(no summary)"
        summary_text = summarize_text(summary_text, self.max_summary_chars)
        self._records.append(
            SessionTaskRecord(
                task=task.strip(),
                run_id=run_id,
                status=status,
                summary=summary_text,
                timestamp=datetime.now(tz=UTC).isoformat(),
            )
        )
        if len(self._records) > self.max_entries:
            self._records = self._records[-self.max_entries :]

    def build_context(self) -> list[dict[str, str]]:
        payload = [record.to_payload() for record in self._records[-self.max_entries :]]
        if not payload:
            return []

        while payload and self._payload_tokens(payload) > self.max_context_tokens:
            if len(payload) == 1:
                summary = payload[0].get("summary", "")
                clipped = summarize_text(summary, max(32, len(summary) // 2))
                payload[0]["summary"] = clipped
                if clipped == summary:
                    return []
            else:
                payload = payload[1:]

        if payload and self._payload_tokens(payload) > self.max_context_tokens:
            return []
        return payload

    @staticmethod
    def _payload_tokens(payload: list[dict[str, str]]) -> int:
        return estimate_tokens(json.dumps(payload, ensure_ascii=True))
