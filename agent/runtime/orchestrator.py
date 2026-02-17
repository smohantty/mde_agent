from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent.config import AgentConfig, ProviderName, get_provider_api_key
from agent.llm.decoder import DecodeError, decode_model_decision, make_finish_decision
from agent.llm.prompt_builder import build_prompt
from agent.llm.provider_router import ProviderRouter
from agent.llm.structured_output import normalize_provider_output
from agent.logging.events import EventBus, EventContext
from agent.logging.jsonl_sink import JsonlSink
from agent.logging.redaction import redact_secrets, summarize_text
from agent.logging.sanitizer import sanitize_text
from agent.logging.transcript import LlmTranscriptSink
from agent.runtime.executor import CommandExecutor
from agent.runtime.retry import compute_backoff_delay, is_retryable_error
from agent.runtime.signals import install_signal_handlers
from agent.skills.disclosure import DisclosureEngine
from agent.skills.registry import SkillRegistry
from agent.skills.router import SkillRouter
from agent.storage.run_store import create_run_dir, generate_run_id, write_artifact
from agent.types import (
    ActionStep,
    ActionType,
    EventRecord,
    LlmTranscriptBudget,
    LlmTranscriptRecord,
    LlmTranscriptUsage,
    ModelDecision,
    ResponseKind,
    SkillCandidate,
    StepExecutionResult,
)


@dataclass
class RunResult:
    run_id: str
    status: str
    message: str
    events_path: Path
    llm_transcript_path: Path | None = None


class Orchestrator:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    @staticmethod
    def _sanitize_and_redact(text: str | None) -> str | None:
        if text is None:
            return None
        sanitized = sanitize_text(text)
        return redact_secrets(sanitized)

    @staticmethod
    def _serialize_response_payload(payload: dict[str, Any] | str | None) -> str | None:
        if payload is None:
            return None
        if isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=True)
        return str(payload)

    @staticmethod
    def _classify_response_kind(action_types: list[ActionType]) -> ResponseKind:
        if any(action == "call_skill" for action in action_types):
            return "skill_call"
        if any(action == "run_command" for action in action_types):
            return "tool_call"
        return "response"

    @staticmethod
    def _response_kind_reason(kind: ResponseKind, action_types: list[ActionType]) -> str:
        if kind == "skill_call":
            return "Mapped to skill_call because normalized actions include call_skill."
        if kind == "tool_call":
            return "Mapped to tool_call because normalized actions include run_command."
        if action_types:
            return "Mapped to response because normalized actions have no call_skill/run_command."
        return "Mapped to response because no normalized actions were decoded."

    @staticmethod
    def _provider_name_for_transcript(provider_name: str) -> ProviderName:
        if provider_name == "gemini":
            return "gemini"
        return "anthropic"

    @staticmethod
    def _build_decoder_overrides(
        skills: list[Any],
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, Any]]]]:
        skill_action_aliases: dict[str, dict[str, str]] = {}
        skill_default_action_params: dict[str, dict[str, dict[str, Any]]] = {}
        for skill in skills:
            metadata = skill.metadata
            skill_name = metadata.name
            if metadata.action_aliases:
                skill_action_aliases[skill_name] = dict(metadata.action_aliases)
            if metadata.default_action_params:
                skill_default_action_params[skill_name] = {
                    action: dict(params)
                    for action, params in metadata.default_action_params.items()
                    if isinstance(params, dict)
                }
        return skill_action_aliases, skill_default_action_params

    @staticmethod
    def _normalize_command(command: str) -> str:
        """Rewrite noisy markdown discovery commands to safer workspace-scoped rg forms."""
        normalized = command.strip()
        pattern = r"""find\s+\.\s+-type\s+f\s+-name\s+['"]\*\.md['"]"""
        if re.search(pattern, normalized):
            head_match = re.search(r"head\s+-(?:n\s*)?(\d+)", normalized)
            limit = int(head_match.group(1)) if head_match else 20
            return (
                f'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n {limit}'
            )
        return normalized

    @staticmethod
    def _build_raw_model_request(
        *,
        provider: str,
        model: str,
        max_tokens: int,
        prompt: str,
        attempt: int,
    ) -> dict[str, Any]:
        if provider == "anthropic":
            return {
                "attempt": attempt,
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        if provider == "gemini":
            return {
                "attempt": attempt,
                "model": model,
                "contents": prompt,
                "config": {
                    "response_mime_type": "application/json",
                    "max_output_tokens": max_tokens,
                },
            }
        return {
            "attempt": attempt,
            "model": model,
            "max_tokens": max_tokens,
            "prompt": prompt,
        }

    @staticmethod
    def _extract_raw_action_types(raw_response: dict[str, Any] | str | None) -> list[str]:
        if raw_response is None:
            return []
        try:
            payload = normalize_provider_output(raw_response)
        except ValueError:
            return []

        planned = payload.get("planned_actions")
        if not isinstance(planned, list):
            return []

        action_types: list[str] = []
        for step in planned:
            if not isinstance(step, dict):
                continue
            for key in ("type", "action_type", "action", "step_type", "operation"):
                value = step.get(key)
                if isinstance(value, str) and value.strip():
                    action_types.append(value.strip())
                    break
        return action_types

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

    def _write_transcript(
        self,
        *,
        bus: EventBus,
        sink: LlmTranscriptSink | None,
        record: LlmTranscriptRecord,
    ) -> None:
        if sink is None:
            return
        try:
            sink.write(record)
        except Exception as exc:
            bus.emit(
                "llm_transcript_write_failed",
                {
                    "turn_index": record.turn_index,
                    "attempt": record.attempt,
                    "error": str(exc),
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
        llm_transcript_path: Path | None = None
        transcript_sink: LlmTranscriptSink | None = None
        bus = EventBus(
            sink=sink,
            context=EventContext(run_id=run_id, trace_id=trace_id),
            redact=self.config.logging.redact_secrets,
            sanitize=self.config.logging.sanitize_control_chars,
            on_emit=on_event,
        )
        if self.config.logging.llm_transcript_enabled:
            llm_transcript_path = run_dir / self.config.logging.llm_transcript_filename
            try:
                transcript_sink = LlmTranscriptSink(llm_transcript_path)
            except Exception as exc:
                bus.emit(
                    "llm_transcript_write_failed",
                    {
                        "turn_index": 0,
                        "attempt": 0,
                        "error": str(exc),
                    },
                )
                transcript_sink = None

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
        skill_action_aliases, skill_default_action_params = self._build_decoder_overrides(skills)
        all_skill_frontmatter = [dict(skill.frontmatter) for skill in skills]
        bus.emit(
            "skill_catalog_loaded", {"skills_count": len(skills), "skills_dir": str(skills_dir)}
        )
        if not skills:
            bus.emit("run_failed", {"reason": "no_skills_found"})
            return RunResult(
                run_id=run_id,
                status="failed",
                message="No skills found",
                events_path=sink.path,
                llm_transcript_path=llm_transcript_path,
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
                    llm_transcript_path=llm_transcript_path,
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
                all_skill_frontmatter=all_skill_frontmatter,
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
                run_id=run_id,
                status="success",
                message="Dry run complete",
                events_path=sink.path,
                llm_transcript_path=llm_transcript_path,
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
                llm_transcript_path=llm_transcript_path,
            )

        provider_router = ProviderRouter(anthropic_api_key=anthropic_key, gemini_api_key=gemini_key)
        executor = CommandExecutor(
            linux_shell=self.config.runtime.shell_linux,
            windows_shell=self.config.runtime.shell_windows,
            timeout_seconds=self.config.runtime.timeout_seconds,
        )

        accumulated_results: list[StepExecutionResult] = []
        consecutive_self_handoff_turns = 0
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
                        llm_transcript_path=llm_transcript_path,
                    )

                prompt_data = build_prompt(
                    task=task,
                    candidates=candidates,
                    all_skill_frontmatter=all_skill_frontmatter,
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
                transcript_budget = LlmTranscriptBudget(
                    max_context_tokens=prompt_data.budget.max_context_tokens,
                    response_headroom_tokens=prompt_data.budget.response_headroom_tokens,
                    allocated_prompt_tokens=prompt_data.budget.allocated_prompt_tokens,
                    allocated_disclosure_tokens=prompt_data.budget.allocated_disclosure_tokens,
                )
                transcript_prompt_text = self._sanitize_and_redact(prompt_data.prompt) or ""
                transcript_disclosed_paths = list(disclosed_snippets.keys())

                llm_response_data: dict[str, Any] | str | None = None
                llm_meta: dict[str, Any] | None = None
                llm_error: Exception | None = None
                last_attempt = 0
                transcript_raw_request_text = ""

                for attempt in range(1, self.config.runtime.max_llm_retries + 2):
                    last_attempt = attempt
                    request_payload = self._build_raw_model_request(
                        provider=provider_name,
                        model=self.config.model.name,
                        max_tokens=self.config.model.max_tokens,
                        prompt=prompt_data.prompt,
                        attempt=attempt,
                    )
                    transcript_raw_request_text = (
                        self._sanitize_and_redact(json.dumps(request_payload, ensure_ascii=True))
                        or ""
                    )
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
                        request_failed_record = LlmTranscriptRecord(
                            turn_index=turn_index,
                            attempt=attempt,
                            provider=self._provider_name_for_transcript(provider_name),
                            model=self.config.model.name,
                            status="request_failed",
                            raw_request_text=transcript_raw_request_text,
                            prompt_text=transcript_prompt_text,
                            response_text=None,
                            prompt_estimated_tokens=prompt_data.estimated_input_tokens,
                            budget=transcript_budget,
                            disclosed_paths=transcript_disclosed_paths,
                            usage=LlmTranscriptUsage(),
                            decode_success=False,
                            selected_skill=None,
                            raw_action_types=[],
                            planned_action_types=[],
                            required_disclosure_paths=[],
                            response_kind="response",
                            response_kind_reason=(
                                "Mapped to response because the LLM request failed before decoding."
                            ),
                            error=self._sanitize_and_redact(str(exc)),
                            retryable=retryable,
                        )
                        self._write_transcript(
                            bus=bus,
                            sink=transcript_sink,
                            record=request_failed_record,
                        )
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
                        llm_transcript_path=llm_transcript_path,
                    )

                bus.emit(
                    "llm_response_received",
                    {
                        "turn_index": turn_index,
                        "meta": llm_meta or {},
                        "response_preview": summarize_text(str(llm_response_data)),
                    },
                )
                response_text_raw = self._serialize_response_payload(llm_response_data)
                response_text = self._sanitize_and_redact(response_text_raw)
                usage = LlmTranscriptUsage(
                    input_tokens=(llm_meta or {}).get("input_tokens"),
                    output_tokens=(llm_meta or {}).get("output_tokens"),
                    latency_ms=(llm_meta or {}).get("latency_ms"),
                )
                raw_action_types = self._extract_raw_action_types(llm_response_data)

                decision: ModelDecision
                try:
                    decision = decode_model_decision(
                        llm_response_data,
                        skill_action_aliases=skill_action_aliases,
                        skill_default_action_params=skill_default_action_params,
                    )
                except DecodeError as exc:
                    decode_failed_record = LlmTranscriptRecord(
                        turn_index=turn_index,
                        attempt=int((llm_meta or {}).get("attempt", last_attempt)),
                        provider=self._provider_name_for_transcript(provider_name),
                        model=self.config.model.name,
                        status="decode_failed",
                        raw_request_text=transcript_raw_request_text,
                        prompt_text=transcript_prompt_text,
                        response_text=response_text,
                        prompt_estimated_tokens=prompt_data.estimated_input_tokens,
                        budget=transcript_budget,
                        disclosed_paths=transcript_disclosed_paths,
                        usage=usage,
                        decode_success=False,
                        selected_skill=None,
                        raw_action_types=raw_action_types,
                        planned_action_types=[],
                        required_disclosure_paths=[],
                        response_kind="response",
                        response_kind_reason=(
                            "Mapped to response because decoding failed "
                            "before action normalization."
                        ),
                        error=self._sanitize_and_redact(str(exc)),
                        retryable=None,
                    )
                    self._write_transcript(
                        bus=bus,
                        sink=transcript_sink,
                        record=decode_failed_record,
                    )
                    bus.emit("run_failed", {"reason": "decode_failed", "error": str(exc)})
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="Failed to decode model response",
                        events_path=sink.path,
                        llm_transcript_path=llm_transcript_path,
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

                planned_action_types = cast(
                    list[ActionType],
                    [action.type for action in decision.planned_actions],
                )
                response_kind = self._classify_response_kind(planned_action_types)
                success_record = LlmTranscriptRecord(
                    turn_index=turn_index,
                    attempt=int((llm_meta or {}).get("attempt", last_attempt)),
                    provider=self._provider_name_for_transcript(provider_name),
                    model=self.config.model.name,
                    status="success",
                    raw_request_text=transcript_raw_request_text,
                    prompt_text=transcript_prompt_text,
                    response_text=response_text,
                    prompt_estimated_tokens=prompt_data.estimated_input_tokens,
                    budget=transcript_budget,
                    disclosed_paths=transcript_disclosed_paths,
                    usage=usage,
                    decode_success=True,
                    selected_skill=decision.selected_skill,
                    raw_action_types=raw_action_types,
                    planned_action_types=planned_action_types,
                    required_disclosure_paths=decision.required_disclosure_paths,
                    response_kind=response_kind,
                    response_kind_reason=self._response_kind_reason(
                        response_kind, planned_action_types
                    ),
                    error=None,
                    retryable=None,
                )
                self._write_transcript(
                    bus=bus,
                    sink=transcript_sink,
                    record=success_record,
                )

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

                is_self_handoff_only = (
                    bool(decision.planned_actions)
                    and all(action.type == "call_skill" for action in decision.planned_actions)
                    and all(
                        str(action.params.get("skill_name", decision.selected_skill) or "").strip()
                        == (decision.selected_skill or "")
                        for action in decision.planned_actions
                    )
                )
                if is_self_handoff_only:
                    consecutive_self_handoff_turns += 1
                    bus.emit(
                        "self_handoff_detected",
                        {
                            "turn_index": turn_index,
                            "selected_skill": decision.selected_skill,
                            "count": consecutive_self_handoff_turns,
                        },
                    )
                else:
                    consecutive_self_handoff_turns = 0

                if consecutive_self_handoff_turns >= 2:
                    bus.emit(
                        "run_failed",
                        {
                            "reason": "self_handoff_loop",
                            "turn_index": turn_index,
                            "selected_skill": decision.selected_skill,
                        },
                    )
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="Detected repeated self-handoff loop",
                        events_path=sink.path,
                        llm_transcript_path=llm_transcript_path,
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
                        llm_transcript_path=llm_transcript_path,
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
                        llm_transcript_path=llm_transcript_path,
                    )

        bus.emit("run_failed", {"reason": "max_turns_exceeded", "max_turns": max_turns})
        return RunResult(
            run_id=run_id,
            status="failed",
            message="Max turns exceeded",
            events_path=sink.path,
            llm_transcript_path=llm_transcript_path,
        )
