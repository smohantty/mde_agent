from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal

from agent.logging.jsonl_sink import JsonlSink
from agent.logging.redaction import redact_secrets
from agent.logging.sanitizer import sanitize_text
from agent.types import EventRecord


@dataclass
class EventContext:
    run_id: str
    trace_id: str


class EventBus:
    def __init__(
        self,
        sink: JsonlSink,
        context: EventContext,
        redact: bool = True,
        sanitize: bool = True,
        on_emit: Callable[[EventRecord], None] | None = None,
    ) -> None:
        self._sink = sink
        self._context = context
        self._redact = redact
        self._sanitize = sanitize
        self._on_emit = on_emit

    def _clean_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                text = value
                if self._sanitize:
                    text = sanitize_text(text)
                if self._redact:
                    text = redact_secrets(text)
                cleaned[key] = text
            else:
                cleaned[key] = value
        return cleaned

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        redaction_mode: Literal["full", "redacted"] = "redacted",
    ) -> EventRecord:
        event = EventRecord(
            run_id=self._context.run_id,
            trace_id=self._context.trace_id,
            span_id=uuid.uuid4().hex[:12],
            event_type=event_type,
            payload=self._clean_payload(payload or {}),
            redaction_mode=redaction_mode,
        )
        self._sink.write(event)
        if self._on_emit is not None:
            with suppress(Exception):
                self._on_emit(event)
        return event
