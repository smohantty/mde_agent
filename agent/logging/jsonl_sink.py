from __future__ import annotations

import json
import threading
from pathlib import Path

from agent.types import EventRecord


class JsonlSink:
    def __init__(self, events_path: Path) -> None:
        self._path = events_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, event: EventRecord) -> None:
        payload = event.model_dump(mode="json")
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def replay(self) -> list[dict[str, object]]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
