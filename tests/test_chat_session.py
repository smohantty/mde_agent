from __future__ import annotations

import json

from agent.llm.token_budget import estimate_tokens
from agent.runtime.chat_session import ChatSessionMemory


def test_chat_session_memory_keeps_recent_entries() -> None:
    memory = ChatSessionMemory(max_entries=2, max_summary_chars=120, max_context_tokens=1000)
    memory.append(task="task-1", run_id="run-1", status="success", summary="summary-1")
    memory.append(task="task-2", run_id="run-2", status="success", summary="summary-2")
    memory.append(task="task-3", run_id="run-3", status="failed", summary="summary-3")

    context = memory.build_context()
    assert len(context) == 2
    assert context[0]["task"] == "task-2"
    assert context[1]["task"] == "task-3"


def test_chat_session_memory_respects_context_token_budget() -> None:
    memory = ChatSessionMemory(max_entries=5, max_summary_chars=1000, max_context_tokens=40)
    long_summary = "x" * 800
    memory.append(task="task-1", run_id="run-1", status="success", summary=long_summary)
    memory.append(task="task-2", run_id="run-2", status="success", summary=long_summary)

    context = memory.build_context()
    assert context
    payload_tokens = estimate_tokens(json.dumps(context, ensure_ascii=True))
    assert payload_tokens <= 40
