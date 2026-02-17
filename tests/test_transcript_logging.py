from __future__ import annotations

from pathlib import Path

from agent.config import AgentConfig
from agent.logging.transcript import LlmTranscriptSink
from agent.runtime.orchestrator import Orchestrator
from agent.types import LlmTranscriptBudget, LlmTranscriptRecord, LlmTranscriptUsage


def test_transcript_sink_writes_jsonl(tmp_path: Path) -> None:
    sink = LlmTranscriptSink(tmp_path / "llm_transcript.jsonl")
    record = LlmTranscriptRecord(
        turn_index=1,
        attempt=1,
        provider="anthropic",
        model="claude-sonnet-4-5",
        status="success",
        prompt_text="prompt",
        response_text="response",
        prompt_estimated_tokens=10,
        budget=LlmTranscriptBudget(
            max_context_tokens=32000,
            response_headroom_tokens=2000,
            allocated_prompt_tokens=30000,
            allocated_disclosure_tokens=100,
        ),
        disclosed_paths=["section:Purpose"],
        usage=LlmTranscriptUsage(input_tokens=1, output_tokens=2, latency_ms=3),
        decode_success=True,
        selected_skill="demo",
        planned_action_types=["finish"],
        required_disclosure_paths=[],
        response_kind="response",
        error=None,
        retryable=None,
    )
    sink.write(record)
    rows = sink.replay()
    assert rows[0]["status"] == "success"
    assert rows[0]["provider"] == "anthropic"


def test_transcript_text_is_sanitized_and_redacted() -> None:
    text = "token=abc123\x01 and authorization: bearer secret-token"
    cleaned = Orchestrator._sanitize_and_redact(text)
    assert cleaned is not None
    assert "\x01" not in cleaned
    assert "***REDACTED***" in cleaned


def test_response_kind_classification() -> None:
    orchestrator = Orchestrator(AgentConfig())
    assert orchestrator._classify_response_kind(["call_skill"]) == "skill_call"
    assert orchestrator._classify_response_kind(["run_command"]) == "tool_call"
    assert orchestrator._classify_response_kind(["finish"]) == "response"
