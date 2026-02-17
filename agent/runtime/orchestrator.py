from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import AgentConfig, get_provider_api_key
from agent.llm.decoder import DecodeError, decode_model_decision, make_finish_decision
from agent.llm.prompt_builder import build_prompt
from agent.llm.provider_router import ProviderRouter
from agent.logging.events import EventBus, EventContext
from agent.logging.jsonl_sink import JsonlSink
from agent.logging.redaction import summarize_text
from agent.runtime.executor import CommandExecutor
from agent.runtime.retry import compute_backoff_delay, is_retryable_error
from agent.runtime.signals import install_signal_handlers
from agent.skills.disclosure import DisclosureEngine
from agent.skills.registry import SkillRegistry
from agent.skills.router import SkillRouter
from agent.storage.run_store import create_run_dir, generate_run_id, write_artifact
from agent.types import ActionStep, EventRecord, ModelDecision, SkillCandidate, StepExecutionResult


@dataclass
class RunResult:
    run_id: str
    status: str
    message: str
    events_path: Path


class Orchestrator:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    @staticmethod
    def _normalize_command(command: str) -> str:
        """Rewrite noisy markdown discovery commands to safer workspace-scoped rg forms."""
        normalized = command.strip()
        pattern = r"""find\s+\.\s+-type\s+f\s+-name\s+['"]\*\.md['"]"""
        if re.search(pattern, normalized):
            head_match = re.search(r"head\s+-(?:n\s*)?(\d+)", normalized)
            limit = int(head_match.group(1)) if head_match else 20
            return (
                'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" '
                f"| head -n {limit}"
            )
        return normalized

    def _emit_disclosure(
        self,
        bus: EventBus,
        stage: int,
        snippets: dict[str, str],
        total_bytes: int,
        total_tokens: int,
    ) -> None:
        bus.emit(
            "skill_disclosure_loaded",
            {
                "stage": stage,
                "paths": list(snippets.keys()),
                "total_bytes": total_bytes,
                "total_tokens": total_tokens,
            },
        )

    def _execute_actions(
        self,
        actions: list[ActionStep],
        bus: EventBus,
        executor: CommandExecutor,
        retry_policy: str,
    ) -> tuple[list[StepExecutionResult], bool]:
        step_results: list[StepExecutionResult] = []
        should_finish = False

        for idx, action in enumerate(actions, start=1):
            step_id = f"step-{idx}"
            if action.type == "finish":
                step_results.append(
                    StepExecutionResult(
                        step_id=step_id,
                        exit_code=0,
                        stdout_summary="",
                        stderr_summary="",
                        retry_count=0,
                        status="success",
                    )
                )
                should_finish = True
                bus.emit(
                    "skill_step_executed",
                    {"step_id": step_id, "type": action.type, "status": "success"},
                )
                continue

            if action.type == "run_command":
                command = str(action.params.get("command", "")).strip()
                if not command:
                    step_results.append(
                        StepExecutionResult(
                            step_id=step_id,
                            exit_code=1,
                            stdout_summary="",
                            stderr_summary="Missing command",
                            retry_count=0,
                            status="failed",
                        )
                    )
                    bus.emit(
                        "skill_step_executed",
                        {
                            "step_id": step_id,
                            "type": action.type,
                            "status": "failed",
                            "reason": "missing_command",
                        },
                    )
                    return step_results, False

                normalized_command = self._normalize_command(command)
                execution = executor.run(normalized_command)
                retry_count = 0
                if (
                    execution.exit_code != 0
                    and retry_policy == "retry_once_then_fallback_then_abort"
                ):
                    retry_count = 1
                    bus.emit(
                        "step_retry_scheduled",
                        {
                            "step_id": step_id,
                            "command": normalized_command,
                            "retry_count": retry_count,
                        },
                    )
                    execution = executor.run(normalized_command)

                status = "success" if execution.exit_code == 0 else "failed"
                result = StepExecutionResult(
                    step_id=step_id,
                    exit_code=execution.exit_code,
                    stdout_summary=summarize_text(execution.stdout),
                    stderr_summary=summarize_text(execution.stderr),
                    retry_count=retry_count,
                    status=status,
                )
                step_results.append(result)
                bus.emit(
                    "skill_step_executed",
                    {
                        "step_id": step_id,
                        "type": action.type,
                        "command": normalized_command,
                        "status": status,
                        "exit_code": execution.exit_code,
                        "stdout": result.stdout_summary,
                        "stderr": result.stderr_summary,
                        "retry_count": retry_count,
                    },
                )
                if status == "failed":
                    return step_results, False
                continue

            if action.type == "call_skill":
                target = str(action.params.get("skill_name", "")).strip()
                step_results.append(
                    StepExecutionResult(
                        step_id=step_id,
                        exit_code=0 if target else 1,
                        stdout_summary=f"Requested handoff to {target}" if target else "",
                        stderr_summary="" if target else "Missing skill_name",
                        retry_count=0,
                        status="success" if target else "failed",
                    )
                )
                bus.emit(
                    "skill_step_executed",
                    {
                        "step_id": step_id,
                        "type": action.type,
                        "status": "success" if target else "failed",
                        "target_skill": target,
                    },
                )
                if not target:
                    return step_results, False
                continue

            step_results.append(
                StepExecutionResult(
                    step_id=step_id,
                    exit_code=0,
                    stdout_summary="Skipped ask_user in non-interactive mode",
                    stderr_summary="",
                    retry_count=0,
                    status="skipped",
                )
            )
            bus.emit(
                "skill_step_executed",
                {"step_id": step_id, "type": action.type, "status": "skipped"},
            )

        return step_results, should_finish

    def run(
        self,
        task: str,
        skills_dir: Path,
        provider_override: str | None = None,
        dry_run: bool = False,
        max_turns_override: int | None = None,
        on_event: Callable[[EventRecord], None] | None = None,
    ) -> RunResult:
        run_id = generate_run_id()
        trace_id = uuid.uuid4().hex
        run_dir = create_run_dir(Path(self.config.logging.jsonl_dir), run_id)
        sink = JsonlSink(run_dir / "events.jsonl")
        bus = EventBus(
            sink=sink,
            context=EventContext(run_id=run_id, trace_id=trace_id),
            redact=self.config.logging.redact_secrets,
            sanitize=self.config.logging.sanitize_control_chars,
            on_emit=on_event,
        )

        provider_name = provider_override or self.config.model.provider
        max_turns = (
            max_turns_override if max_turns_override is not None else self.config.runtime.max_turns
        )

        bus.emit(
            "run_started",
            {
                "task": task,
                "provider": provider_name,
                "dry_run": dry_run,
                "max_turns": max_turns,
            },
        )

        registry = SkillRegistry(skills_dir)
        skills = registry.load()
        bus.emit(
            "skill_catalog_loaded", {"skills_count": len(skills), "skills_dir": str(skills_dir)}
        )
        if not skills:
            bus.emit("run_failed", {"reason": "no_skills_found"})
            return RunResult(
                run_id=run_id, status="failed", message="No skills found", events_path=sink.path
            )

        router = SkillRouter(min_score=self.config.skills.prefilter_min_score)
        candidates = router.prefilter(
            task=task,
            skills=skills,
            top_k=self.config.skills.prefilter_top_k,
            min_score=self.config.skills.prefilter_min_score,
        )

        if not candidates:
            if self.config.skills.prefilter_zero_candidate_strategy == "fallback_all_skills":
                candidates = [
                    SkillCandidate(
                        skill_name=item.metadata.name,
                        score=0.0,
                        reason="Fallback zero-candidate strategy",
                    )
                    for item in skills
                ][: self.config.skills.prefilter_top_k]
            else:
                bus.emit("run_failed", {"reason": "prefilter_zero_candidates"})
                return RunResult(
                    run_id=run_id,
                    status="failed",
                    message="No candidate skills matched",
                    events_path=sink.path,
                )

        bus.emit(
            "skill_prefilter_completed",
            {
                "candidates": [item.model_dump() for item in candidates],
                "candidate_count": len(candidates),
            },
        )

        primary_skill = registry.by_name(skills, candidates[0].skill_name)
        disclosed_snippets: dict[str, str] = {}
        disclosure_engine = DisclosureEngine(
            max_bytes=self.config.skills.disclosure_max_reference_bytes,
            max_tokens=self.config.skills.disclosure_max_reference_tokens,
        )
        if primary_skill is not None:
            stage1 = disclosure_engine.stage1(primary_skill)
            disclosed_snippets.update(stage1.snippets)
            self._emit_disclosure(
                bus, stage1.stage, stage1.snippets, stage1.total_bytes, stage1.total_tokens
            )

        if dry_run:
            prompt_data = build_prompt(
                task=task,
                candidates=candidates,
                disclosed_snippets=disclosed_snippets,
                step_results=[],
                max_context_tokens=self.config.model.max_context_tokens,
                response_headroom_tokens=self.config.model.response_headroom_tokens,
            )
            bus.emit(
                "prompt_budget_computed",
                {
                    "max_context_tokens": prompt_data.budget.max_context_tokens,
                    "response_headroom_tokens": prompt_data.budget.response_headroom_tokens,
                    "allocated_prompt_tokens": prompt_data.budget.allocated_prompt_tokens,
                    "allocated_disclosure_tokens": prompt_data.budget.allocated_disclosure_tokens,
                },
            )
            prompt_hash = hashlib.sha256(prompt_data.prompt.encode("utf-8")).hexdigest()
            bus.emit(
                "prompt_composed",
                {
                    "prompt_hash": prompt_hash,
                    "estimated_input_tokens": prompt_data.estimated_input_tokens,
                },
            )
            write_artifact(run_dir, "dry_run_prompt.txt", prompt_data.prompt)
            bus.emit("run_finished", {"mode": "dry_run"})
            return RunResult(
                run_id=run_id, status="success", message="Dry run complete", events_path=sink.path
            )

        anthropic_key = get_provider_api_key(self.config, "anthropic")
        gemini_key = get_provider_api_key(self.config, "gemini")
        selected_provider_key = anthropic_key if provider_name == "anthropic" else gemini_key
        if selected_provider_key is None:
            bus.emit(
                "run_failed",
                {
                    "reason": "missing_provider_api_key",
                    "provider": provider_name,
                },
            )
            return RunResult(
                run_id=run_id,
                status="failed",
                message="Missing provider API key",
                events_path=sink.path,
            )

        provider_router = ProviderRouter(anthropic_api_key=anthropic_key, gemini_api_key=gemini_key)
        executor = CommandExecutor(
            linux_shell=self.config.runtime.shell_linux,
            windows_shell=self.config.runtime.shell_windows,
            timeout_seconds=self.config.runtime.timeout_seconds,
        )

        accumulated_results: list[StepExecutionResult] = []
        with install_signal_handlers() as signal_state:
            for turn_index in range(1, max_turns + 1):
                if signal_state.stop_requested:
                    bus.emit("signal_received", {"signal": signal_state.signal_name})
                    bus.emit("graceful_shutdown_started", {"reason": "signal"})
                    bus.emit("run_failed", {"reason": "interrupted"})
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="Interrupted by signal",
                        events_path=sink.path,
                    )

                prompt_data = build_prompt(
                    task=task,
                    candidates=candidates,
                    disclosed_snippets=disclosed_snippets,
                    step_results=accumulated_results,
                    max_context_tokens=self.config.model.max_context_tokens,
                    response_headroom_tokens=self.config.model.response_headroom_tokens,
                )
                bus.emit(
                    "prompt_budget_computed",
                    {
                        "turn_index": turn_index,
                        "max_context_tokens": prompt_data.budget.max_context_tokens,
                        "response_headroom_tokens": prompt_data.budget.response_headroom_tokens,
                        "allocated_prompt_tokens": prompt_data.budget.allocated_prompt_tokens,
                        "allocated_disclosure_tokens": (
                            prompt_data.budget.allocated_disclosure_tokens
                        ),
                    },
                )
                prompt_hash = hashlib.sha256(prompt_data.prompt.encode("utf-8")).hexdigest()
                bus.emit(
                    "prompt_composed",
                    {
                        "turn_index": turn_index,
                        "prompt_hash": prompt_hash,
                        "estimated_input_tokens": prompt_data.estimated_input_tokens,
                    },
                )

                llm_response_data: dict[str, Any] | str | None = None
                llm_meta: dict[str, Any] | None = None
                llm_error: Exception | None = None

                for attempt in range(1, self.config.runtime.max_llm_retries + 2):
                    bus.emit(
                        "llm_request_sent",
                        {
                            "provider": provider_name,
                            "model": self.config.model.name,
                            "attempt": attempt,
                            "turn_index": turn_index,
                        },
                    )
                    try:
                        result = provider_router.complete_structured(
                            provider=provider_name,
                            prompt=prompt_data.prompt,
                            model=self.config.model.name,
                            max_tokens=self.config.model.max_tokens,
                            attempt=attempt,
                        )
                        llm_response_data = result.data
                        llm_meta = result.meta.model_dump()
                        break
                    except Exception as exc:
                        llm_error = exc
                        retryable = is_retryable_error(exc)
                        if retryable and attempt <= self.config.runtime.max_llm_retries:
                            delay = compute_backoff_delay(
                                attempt=attempt,
                                base_delay=self.config.runtime.retry_base_delay_seconds,
                                max_delay=self.config.runtime.retry_max_delay_seconds,
                            )
                            bus.emit(
                                "llm_retry_scheduled",
                                {
                                    "provider": provider_name,
                                    "attempt": attempt,
                                    "delay_seconds": delay,
                                    "error": str(exc),
                                    "retryable": True,
                                },
                            )
                            time.sleep(min(delay, 0.25))
                            continue
                        bus.emit(
                            "llm_request_failed",
                            {
                                "provider": provider_name,
                                "attempt": attempt,
                                "error": str(exc),
                                "retryable": retryable,
                            },
                        )
                        break

                if llm_response_data is None:
                    bus.emit(
                        "run_failed", {"reason": "llm_request_failed", "error": str(llm_error)}
                    )
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="LLM request failed",
                        events_path=sink.path,
                    )

                bus.emit(
                    "llm_response_received",
                    {
                        "turn_index": turn_index,
                        "meta": llm_meta or {},
                        "response_preview": summarize_text(str(llm_response_data)),
                    },
                )

                decision: ModelDecision
                try:
                    decision = decode_model_decision(llm_response_data)
                except DecodeError as exc:
                    bus.emit("run_failed", {"reason": "decode_failed", "error": str(exc)})
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="Failed to decode model response",
                        events_path=sink.path,
                    )

                bus.emit(
                    "llm_decision_decoded",
                    {
                        "turn_index": turn_index,
                        "selected_skill": decision.selected_skill,
                        "planned_actions": [item.model_dump() for item in decision.planned_actions],
                        "required_disclosure_paths": decision.required_disclosure_paths,
                    },
                )

                if not decision.planned_actions:
                    decision = make_finish_decision("No actions returned; ending run")

                bus.emit(
                    "skill_invocation_started",
                    {"turn_index": turn_index, "selected_skill": decision.selected_skill},
                )
                step_results, should_finish = self._execute_actions(
                    actions=decision.planned_actions,
                    bus=bus,
                    executor=executor,
                    retry_policy=self.config.runtime.on_step_failure,
                )
                accumulated_results.extend(step_results)
                bus.emit(
                    "skill_invocation_finished",
                    {
                        "turn_index": turn_index,
                        "step_results": [item.model_dump() for item in step_results],
                    },
                )

                if decision.selected_skill:
                    target_skill = registry.by_name(skills, decision.selected_skill)
                    if target_skill and decision.required_disclosure_paths:
                        stage2 = disclosure_engine.stage2(
                            target_skill, decision.required_disclosure_paths
                        )
                        disclosed_snippets.update(stage2.snippets)
                        self._emit_disclosure(
                            bus,
                            stage2.stage,
                            stage2.snippets,
                            stage2.total_bytes,
                            stage2.total_tokens,
                        )

                if should_finish:
                    bus.emit("run_finished", {"turn_index": turn_index})
                    return RunResult(
                        run_id=run_id,
                        status="success",
                        message="Run completed",
                        events_path=sink.path,
                    )

                if any(item.status == "failed" for item in step_results):
                    bus.emit(
                        "run_failed", {"reason": "step_execution_failed", "turn_index": turn_index}
                    )
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="Action execution failed",
                        events_path=sink.path,
                    )

        bus.emit("run_failed", {"reason": "max_turns_exceeded", "max_turns": max_turns})
        return RunResult(
            run_id=run_id,
            status="failed",
            message="Max turns exceeded",
            events_path=sink.path,
        )
