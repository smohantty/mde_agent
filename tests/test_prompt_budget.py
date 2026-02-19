from __future__ import annotations

from agent.llm.prompt_builder import build_prompt
from agent.types import SkillCandidate, StepExecutionResult


def test_prompt_builder_includes_execution_results() -> None:
    candidates = [SkillCandidate(skill_name="x", score=90, reason="test")]
    results = [
        StepExecutionResult(
            step_id="step-1",
            exit_code=0,
            stdout_summary="ok",
            stderr_summary="",
            retry_count=0,
            status="success",
        )
    ]
    built = build_prompt(
        task="do x",
        candidates=candidates,
        all_skill_frontmatter=[{"name": "x", "description": "demo"}],
        disclosed_snippets={"section:Purpose": "text"},
        step_results=results,
        max_context_tokens=32000,
        response_headroom_tokens=2000,
    )
    assert "executed_steps" in built.prompt
    assert "ALL_SKILL_FRONTMATTER" in built.prompt
    assert "Skill calls are OPTIONAL." in built.prompt
    assert built.budget.allocated_prompt_tokens > 0


def test_prompt_builder_includes_run_constraints_for_blocked_skill() -> None:
    candidates = [SkillCandidate(skill_name="demo", score=80, reason="test")]
    built = build_prompt(
        task="analyze workspace",
        candidates=candidates,
        all_skill_frontmatter=[{"name": "demo", "description": "demo"}],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
        blocked_skill_name="demo",
    )
    assert "RUN_CONSTRAINTS" in built.prompt
    assert "blocked_call_skill_targets" in built.prompt
    assert "demo" in built.prompt


def test_prompt_builder_includes_session_context_when_present() -> None:
    candidates = [SkillCandidate(skill_name="demo", score=80, reason="test")]
    built = build_prompt(
        task="next task",
        candidates=candidates,
        all_skill_frontmatter=[{"name": "demo", "description": "demo"}],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
        session_context=[
            {
                "task": "previous task",
                "run_id": "run-1",
                "status": "success",
                "summary": "done",
                "timestamp": "2026-02-19T00:00:00+00:00",
            }
        ],
    )
    assert "SESSION_CONTEXT" in built.prompt
    assert "previous task" in built.prompt
