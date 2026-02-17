from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4


def generate_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:8]
    return f"{stamp}-{suffix}"


def create_run_dir(base_dir: Path, run_id: str) -> Path:
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_artifact(run_dir: Path, filename: str, content: str) -> Path:
    path = run_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
