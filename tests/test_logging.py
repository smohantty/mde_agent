from __future__ import annotations

from pathlib import Path

from agent.logging.events import EventBus, EventContext
from agent.logging.jsonl_sink import JsonlSink
from agent.logging.sanitizer import sanitize_text


def test_sanitize_removes_control_chars() -> None:
    assert sanitize_text("ok\x01bad") == "okbad"


def test_event_bus_writes_jsonl(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path / "events.jsonl")
    bus = EventBus(sink, EventContext(run_id="run1", trace_id="trace1"))
    bus.emit("run_started", {"message": "hello"})
    rows = sink.replay()
    assert rows[0]["event_type"] == "run_started"
