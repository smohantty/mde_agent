from __future__ import annotations

import hashlib
import json
import re
import shutil
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
from agent.llm.token_budget import estimate_tokens
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
    LlmCallSite,
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
    final_summary_path: Path | None = None


@dataclass
class LlmInvocationContext:
    turn_index: int
    call_site: LlmCallSite
    prompt_estimated_tokens: int
    transcript_budget: LlmTranscriptBudget
    transcript_prompt_text: str
    transcript_disclosed_paths: list[str]


@dataclass
class LlmInvocationResult:
    response_data: dict[str, Any] | str | None
    llm_meta: dict[str, Any] | None
    last_attempt: int
    raw_request_text: str
    llm_error: Exception | None


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
    def _extract_finish_summary(actions: list[ActionStep]) -> str | None:
        for action in actions:
            if action.type != "finish":
                continue
            for key in ("message", "summary", "result", "result_summary"):
                value = action.params.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

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
    def _build_prompt_skill_catalog(skills: list[Any]) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for skill in skills:
            catalog.append(
                {
                    "name": skill.metadata.name,
                    "description": skill.metadata.description,
                    "version": skill.metadata.version,
                    "tags": list(skill.metadata.tags),
                    "allowed_tools": list(skill.metadata.allowed_tools),
                    "references_index": list(skill.metadata.references_index),
                    "scripts_index": list(skill.scripts),
                }
            )
        return catalog

    @staticmethod
    def _normalize_command(command: str) -> str:
        """Rewrite noisy markdown discovery commands to safer workspace-scoped rg forms."""
        normalized = command.strip()
        pattern = r"""find\s+\.\s+-type\s+f\s+-name\s+['"]\*\.md['"]"""
        if re.search(pattern, normalized) and Orchestrator._rg_available():
            head_match = re.search(r"head\s+-(?:n\s*)?(\d+)", normalized)
            limit = int(head_match.group(1)) if head_match else 20
            return (
                f'rg --files -g "*.md" -g "!.venv/**" -g "!runs/**" -g "!.git/**" | head -n {limit}'
            )
        if not Orchestrator._rg_available():
            normalized = Orchestrator._rewrite_rg_commands_without_rg(normalized)
        return normalized

    @staticmethod
    def _rg_available() -> bool:
        return shutil.which("rg") is not None

    @staticmethod
    def _md_find_command(*, limit: int | None = None) -> str:
        command = (
            'find . -type f -name "*.md" '
            '-not -path "./.venv/*" -not -path "./runs/*" -not -path "./.git/*"'
        )
        if limit is not None:
            command = f"{command} | head -n {limit}"
        return command

    @staticmethod
    def _rewrite_rg_commands_without_rg(command: str) -> str:
        rewritten = command
        rg_files_pattern = r"""rg\s+--files(?:\s+-g\s+["'][^"']+["'])+"""
        rewritten = re.sub(rg_files_pattern, Orchestrator._md_find_command(), rewritten)
        rewritten = rewritten.replace('rg "^#"', 'grep -E "^#"')
        rewritten = rewritten.replace('rg "^#{1,3} "', 'grep -E "^#{1,3} "')
        return rewritten

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

    @staticmethod
    def _is_self_handoff_only(
        *,
        selected_skill: str | None,
        actions: list[ActionStep],
    ) -> bool:
        selected = (selected_skill or "").strip()
        if not selected or not actions:
            return False
        for action in actions:
            if action.type != "call_skill":
                return False
            target = str(action.params.get("skill_name", selected) or "").strip()
            if target != selected:
                return False
        return True

    def _build_self_handoff_recovery_actions(
        self,
        skill: Any | None,
    ) -> list[ActionStep]:
        commands: list[str] = []
        if not self._rg_available():
            commands = [
                self._md_find_command(limit=50),
                (
                    f"f=$({self._md_find_command(limit=1)}); "
                    'if [ -n "$f" ]; then echo "## $f"; sed -n "1,120p" "$f"; '
                    'else echo "no markdown files found"; fi'
                ),
            ]

        if not commands and skill is not None:
            defaults = getattr(skill.metadata, "default_action_params", {})
            if isinstance(defaults, dict):
                preferred = [
                    "generate_summary",
                    "aggregate_summaries",
                    "extract_sections",
                    "extract_key_sections",
                    "read_file",
                    "read_file_content",
                    "list_files",
                    "find_markdown_files",
                    "identify_markdown_files",
                ]
                ordered = [key for key in preferred if key in defaults]
                ordered.extend(key for key in defaults if key not in ordered)
                seen: set[str] = set()
                for key in ordered:
                    params = defaults.get(key, {})
                    if not isinstance(params, dict):
                        continue
                    command = params.get("command")
                    if not isinstance(command, str) or not command.strip():
                        continue
                    normalized = command.strip()
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    commands.append(normalized)
                    if len(commands) >= 2:
                        break

        if commands:
            commands = [self._normalize_command(command) for command in commands]

        actions = [
            ActionStep(
                type="run_command",
                params={"command": command},
                expected_output=f"Recovery command {idx + 1}",
            )
            for idx, command in enumerate(commands)
        ]
        actions.append(
            ActionStep(
                type="finish",
                params={"message": "Recovered from repeated self-handoff loop."},
                expected_output=None,
            )
        )
        return actions

    @staticmethod
    def _collect_tool_evidence(step_results: list[StepExecutionResult]) -> list[dict[str, str]]:
        evidence: list[dict[str, str]] = []
        for result in step_results:
            if result.status != "success" or not result.stdout_artifact:
                continue
            path = Path(result.stdout_artifact)
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            evidence.append({"step_id": result.step_id, "stdout": text[:7000]})
        return evidence

    @staticmethod
    def _extract_final_answer(raw: dict[str, Any] | str) -> str | None:
        try:
            payload = normalize_provider_output(raw)
        except ValueError:
            text = str(raw).strip()
            return text if text else None
        for key in ("final_answer", "answer", "summary", "final_summary"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _synthesize_final_answer(
        self,
        *,
        task: str,
        preliminary_summary: str | None,
        step_results: list[StepExecutionResult],
        provider_router: ProviderRouter,
        provider_name: str,
        run_dir: Path,
        turn_index: int,
        bus: EventBus,
        transcript_sink: LlmTranscriptSink | None,
    ) -> str | None:
        evidence = self._collect_tool_evidence(step_results)
        if not evidence:
            return None

        prompt = "\n\n".join(
            [
                (
                    "You are generating the final answer for an autonomous agent run. "
                    "Return ONLY a JSON object with key final_answer."
                ),
                (
                    "final_answer must directly satisfy TASK using TOOL_EVIDENCE. "
                    "Do not write process/status text like 'completed'."
                ),
                f"TASK:\n{task}",
                (
                    f"PRELIMINARY_SUMMARY:\n{preliminary_summary}"
                    if preliminary_summary
                    else "PRELIMINARY_SUMMARY:\n(none)"
                ),
                f"TOOL_EVIDENCE:\n{json.dumps(evidence, ensure_ascii=True)}",
            ]
        )
        write_artifact(
            run_dir,
            f"artifacts/final_answer_prompt_turn_{turn_index}.txt",
            prompt,
        )
        estimated_input_tokens = estimate_tokens(prompt)
        max_tokens = min(1400, self.config.model.max_tokens)
        bus.emit(
            "final_answer_synthesis_started",
            {
                "turn_index": turn_index,
                "estimated_input_tokens": estimated_input_tokens,
                "evidence_items": len(evidence),
            },
        )

        transcript_budget = LlmTranscriptBudget(
            max_context_tokens=self.config.model.max_context_tokens,
            response_headroom_tokens=self.config.model.response_headroom_tokens,
            allocated_prompt_tokens=max(
                0,
                self.config.model.max_context_tokens - self.config.model.response_headroom_tokens,
            ),
            allocated_disclosure_tokens=0,
        )
        invocation_context = LlmInvocationContext(
            turn_index=turn_index,
            call_site="final_answer_synthesis",
            prompt_estimated_tokens=estimated_input_tokens,
            transcript_budget=transcript_budget,
            transcript_prompt_text=self._sanitize_and_redact(prompt) or "",
            transcript_disclosed_paths=[],
        )
        invocation_result = self._invoke_llm_with_logging(
            provider_router=provider_router,
            provider_name=provider_name,
            prompt=prompt,
            model=self.config.model.name,
            max_tokens=max_tokens,
            run_dir=run_dir,
            context=invocation_context,
            bus=bus,
            transcript_sink=transcript_sink,
        )
        response_data = invocation_result.response_data

        if response_data is None:
            bus.emit(
                "final_answer_synthesis_failed",
                {
                    "turn_index": turn_index,
                    "reason": (
                        str(invocation_result.llm_error)
                        if invocation_result.llm_error
                        else "unknown"
                    ),
                },
            )
            return None

        response_text = self._serialize_response_payload(response_data) or ""
        write_artifact(
            run_dir,
            f"artifacts/final_answer_response_turn_{turn_index}.txt",
            response_text,
        )
        transcript_response_text = self._sanitize_and_redact(response_text)
        llm_meta = invocation_result.llm_meta or {}
        usage = LlmTranscriptUsage(
            input_tokens=llm_meta.get("input_tokens"),
            output_tokens=llm_meta.get("output_tokens"),
            latency_ms=llm_meta.get("latency_ms"),
        )
        raw_action_types = self._extract_raw_action_types(response_data)
        final_answer = self._extract_final_answer(response_data)
        if not final_answer:
            decode_failed_record = LlmTranscriptRecord(
                turn_index=turn_index,
                attempt=int(llm_meta.get("attempt", invocation_result.last_attempt)),
                call_site="final_answer_synthesis",
                provider=self._provider_name_for_transcript(provider_name),
                model=self.config.model.name,
                status="decode_failed",
                raw_request_text=invocation_result.raw_request_text,
                prompt_text=invocation_context.transcript_prompt_text,
                response_text=transcript_response_text,
                prompt_estimated_tokens=estimated_input_tokens,
                budget=transcript_budget,
                disclosed_paths=[],
                usage=usage,
                decode_success=False,
                selected_skill=None,
                raw_action_types=raw_action_types,
                planned_action_types=[],
                required_disclosure_paths=[],
                response_kind="response",
                response_kind_reason=(
                    "Mapped to response because final answer synthesis response "
                    "did not contain a final answer field."
                ),
                error="missing_final_answer",
                retryable=None,
            )
            self._write_transcript(
                bus=bus,
                sink=transcript_sink,
                record=decode_failed_record,
            )
            bus.emit(
                "final_answer_synthesis_failed",
                {"turn_index": turn_index, "reason": "missing_final_answer"},
            )
            return None
        redacted_answer = self._sanitize_and_redact(final_answer) or final_answer
        success_record = LlmTranscriptRecord(
            turn_index=turn_index,
            attempt=int(llm_meta.get("attempt", invocation_result.last_attempt)),
            call_site="final_answer_synthesis",
            provider=self._provider_name_for_transcript(provider_name),
            model=self.config.model.name,
            status="success",
            raw_request_text=invocation_result.raw_request_text,
            prompt_text=invocation_context.transcript_prompt_text,
            response_text=transcript_response_text,
            prompt_estimated_tokens=estimated_input_tokens,
            budget=transcript_budget,
            disclosed_paths=[],
            usage=usage,
            decode_success=True,
            selected_skill=None,
            raw_action_types=raw_action_types,
            planned_action_types=[],
            required_disclosure_paths=[],
            response_kind="response",
            response_kind_reason=(
                "Mapped to response because final answer synthesis returns a direct final answer."
            ),
            finish_summary=redacted_answer,
            error=None,
            retryable=None,
        )
        self._write_transcript(
            bus=bus,
            sink=transcript_sink,
            record=success_record,
        )
        bus.emit(
            "final_answer_synthesis_completed",
            {
                "turn_index": turn_index,
                "summary_preview": summarize_text(redacted_answer, 250),
            },
        )
        return redacted_answer

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

    def _write_llm_attempt_artifact(
        self,
        *,
        run_dir: Path,
        call_site: LlmCallSite,
        turn_index: int,
        attempt: int,
        kind: str,
        content: str,
    ) -> None:
        write_artifact(
            run_dir,
            f"artifacts/llm/{call_site}_turn_{turn_index}_attempt_{attempt}_{kind}.txt",
            content,
        )

    def _invoke_llm_with_logging(
        self,
        *,
        provider_router: ProviderRouter,
        provider_name: str,
        prompt: str,
        model: str,
        max_tokens: int,
        run_dir: Path,
        context: LlmInvocationContext,
        bus: EventBus,
        transcript_sink: LlmTranscriptSink | None,
    ) -> LlmInvocationResult:
        response_data: dict[str, Any] | str | None = None
        llm_meta: dict[str, Any] | None = None
        llm_error: Exception | None = None
        last_attempt = 0
        raw_request_text = ""

        for attempt in range(1, self.config.runtime.max_llm_retries + 2):
            last_attempt = attempt
            request_payload = self._build_raw_model_request(
                provider=provider_name,
                model=model,
                max_tokens=max_tokens,
                prompt=prompt,
                attempt=attempt,
            )
            raw_request_text = (
                self._sanitize_and_redact(json.dumps(request_payload, ensure_ascii=True)) or ""
            )
            self._write_llm_attempt_artifact(
                run_dir=run_dir,
                call_site=context.call_site,
                turn_index=context.turn_index,
                attempt=attempt,
                kind="request",
                content=raw_request_text,
            )
            bus.emit(
                "llm_request_sent",
                {
                    "provider": provider_name,
                    "model": model,
                    "attempt": attempt,
                    "turn_index": context.turn_index,
                    "call_site": context.call_site,
                },
            )
            try:
                result = provider_router.complete_structured(
                    provider=provider_name,
                    prompt=prompt,
                    model=model,
                    max_tokens=max_tokens,
                    attempt=attempt,
                )
                response_data = result.data
                llm_meta = result.meta.model_dump()
                bus.emit(
                    "llm_response_received",
                    {
                        "turn_index": context.turn_index,
                        "call_site": context.call_site,
                        "meta": llm_meta,
                        "response_preview": summarize_text(str(response_data)),
                    },
                )
                response_text = self._sanitize_and_redact(
                    self._serialize_response_payload(response_data)
                )
                self._write_llm_attempt_artifact(
                    run_dir=run_dir,
                    call_site=context.call_site,
                    turn_index=context.turn_index,
                    attempt=attempt,
                    kind="response",
                    content=response_text or "",
                )
                return LlmInvocationResult(
                    response_data=response_data,
                    llm_meta=llm_meta,
                    last_attempt=last_attempt,
                    raw_request_text=raw_request_text,
                    llm_error=None,
                )
            except Exception as exc:
                llm_error = exc
                retryable = is_retryable_error(exc)
                request_failed_record = LlmTranscriptRecord(
                    turn_index=context.turn_index,
                    attempt=attempt,
                    call_site=context.call_site,
                    provider=self._provider_name_for_transcript(provider_name),
                    model=model,
                    status="request_failed",
                    raw_request_text=raw_request_text,
                    prompt_text=context.transcript_prompt_text,
                    response_text=None,
                    prompt_estimated_tokens=context.prompt_estimated_tokens,
                    budget=context.transcript_budget,
                    disclosed_paths=context.transcript_disclosed_paths,
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
                bus.emit(
                    "llm_request_failed",
                    {
                        "provider": provider_name,
                        "attempt": attempt,
                        "turn_index": context.turn_index,
                        "call_site": context.call_site,
                        "error": str(exc),
                        "retryable": retryable,
                    },
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
                            "turn_index": context.turn_index,
                            "call_site": context.call_site,
                            "delay_seconds": delay,
                            "error": str(exc),
                            "retryable": True,
                        },
                    )
                    time.sleep(min(delay, 0.25))
                    continue
                break

        return LlmInvocationResult(
            response_data=response_data,
            llm_meta=llm_meta,
            last_attempt=last_attempt,
            raw_request_text=raw_request_text,
            llm_error=llm_error,
        )

    def _execute_actions(
        self,
        actions: list[ActionStep],
        bus: EventBus,
        executor: CommandExecutor,
        retry_policy: str,
        run_dir: Path,
        turn_index: int,
    ) -> tuple[list[StepExecutionResult], bool]:
        step_results: list[StepExecutionResult] = []
        should_finish = False

        for idx, action in enumerate(actions, start=1):
            step_id = f"step-{idx}"
            if action.type == "finish":
                finish_message = ""
                for key in ("message", "summary", "result", "result_summary"):
                    value = action.params.get(key)
                    if isinstance(value, str) and value.strip():
                        finish_message = value.strip()
                        break
                step_results.append(
                    StepExecutionResult(
                        step_id=step_id,
                        exit_code=0,
                        stdout_summary=summarize_text(finish_message) if finish_message else "",
                        stderr_summary="",
                        retry_count=0,
                        status="success",
                    )
                )
                should_finish = True
                payload: dict[str, Any] = {
                    "step_id": step_id,
                    "type": action.type,
                    "status": "success",
                }
                if finish_message:
                    payload["message"] = finish_message
                bus.emit(
                    "skill_step_executed",
                    payload,
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
                stdout_artifact = write_artifact(
                    run_dir,
                    f"artifacts/turn_{turn_index}_{step_id}_stdout.txt",
                    execution.stdout,
                )
                stderr_artifact: Path | None = None
                if execution.stderr:
                    stderr_artifact = write_artifact(
                        run_dir,
                        f"artifacts/turn_{turn_index}_{step_id}_stderr.txt",
                        execution.stderr,
                    )
                result = StepExecutionResult(
                    step_id=step_id,
                    exit_code=execution.exit_code,
                    stdout_summary=summarize_text(execution.stdout),
                    stderr_summary=summarize_text(execution.stderr),
                    retry_count=retry_count,
                    status=status,
                    stdout_artifact=str(stdout_artifact),
                    stderr_artifact=str(stderr_artifact) if stderr_artifact else None,
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
                        "stdout_artifact": str(stdout_artifact),
                        "stderr_artifact": str(stderr_artifact) if stderr_artifact else None,
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
        all_skill_frontmatter = self._build_prompt_skill_catalog(skills)
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
        blocked_self_handoff_skill: str | None = None
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
                    blocked_skill_name=blocked_self_handoff_skill,
                    max_context_tokens=self.config.model.max_context_tokens,
                    response_headroom_tokens=self.config.model.response_headroom_tokens,
                )
                if blocked_self_handoff_skill:
                    bus.emit(
                        "self_handoff_constraint_applied",
                        {
                            "turn_index": turn_index,
                            "blocked_skill": blocked_self_handoff_skill,
                        },
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
                invocation_context = LlmInvocationContext(
                    turn_index=turn_index,
                    call_site="decision_loop",
                    prompt_estimated_tokens=prompt_data.estimated_input_tokens,
                    transcript_budget=transcript_budget,
                    transcript_prompt_text=self._sanitize_and_redact(prompt_data.prompt) or "",
                    transcript_disclosed_paths=list(disclosed_snippets.keys()),
                )
                invocation_result = self._invoke_llm_with_logging(
                    provider_router=provider_router,
                    provider_name=provider_name,
                    prompt=prompt_data.prompt,
                    model=self.config.model.name,
                    max_tokens=self.config.model.max_tokens,
                    run_dir=run_dir,
                    context=invocation_context,
                    bus=bus,
                    transcript_sink=transcript_sink,
                )
                llm_response_data = invocation_result.response_data
                if llm_response_data is None:
                    bus.emit(
                        "run_failed",
                        {
                            "reason": "llm_request_failed",
                            "error": str(invocation_result.llm_error),
                        },
                    )
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        message="LLM request failed",
                        events_path=sink.path,
                        llm_transcript_path=llm_transcript_path,
                    )

                llm_meta = invocation_result.llm_meta or {}
                response_text_raw = self._serialize_response_payload(llm_response_data)
                response_text = self._sanitize_and_redact(response_text_raw)
                usage = LlmTranscriptUsage(
                    input_tokens=llm_meta.get("input_tokens"),
                    output_tokens=llm_meta.get("output_tokens"),
                    latency_ms=llm_meta.get("latency_ms"),
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
                        attempt=int(llm_meta.get("attempt", invocation_result.last_attempt)),
                        call_site="decision_loop",
                        provider=self._provider_name_for_transcript(provider_name),
                        model=self.config.model.name,
                        status="decode_failed",
                        raw_request_text=invocation_result.raw_request_text,
                        prompt_text=invocation_context.transcript_prompt_text,
                        response_text=response_text,
                        prompt_estimated_tokens=prompt_data.estimated_input_tokens,
                        budget=transcript_budget,
                        disclosed_paths=invocation_context.transcript_disclosed_paths,
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

                decoded_self_handoff = self._is_self_handoff_only(
                    selected_skill=decision.selected_skill,
                    actions=decision.planned_actions,
                )
                if decoded_self_handoff and consecutive_self_handoff_turns >= 1:
                    target_skill = (
                        registry.by_name(skills, decision.selected_skill)
                        if decision.selected_skill
                        else None
                    )
                    recovery_actions = self._build_self_handoff_recovery_actions(target_skill)
                    decision = decision.model_copy(
                        update={
                            "planned_actions": recovery_actions,
                            "required_disclosure_paths": [],
                        }
                    )
                    bus.emit(
                        "self_handoff_recovery_applied",
                        {
                            "turn_index": turn_index,
                            "selected_skill": decision.selected_skill,
                            "recovery_action_types": [item.type for item in recovery_actions],
                        },
                    )

                planned_action_types = cast(
                    list[ActionType],
                    [action.type for action in decision.planned_actions],
                )
                finish_summary = self._extract_finish_summary(decision.planned_actions)
                response_kind = self._classify_response_kind(planned_action_types)
                success_record = LlmTranscriptRecord(
                    turn_index=turn_index,
                    attempt=int(llm_meta.get("attempt", invocation_result.last_attempt)),
                    call_site="decision_loop",
                    provider=self._provider_name_for_transcript(provider_name),
                    model=self.config.model.name,
                    status="success",
                    raw_request_text=invocation_result.raw_request_text,
                    prompt_text=invocation_context.transcript_prompt_text,
                    response_text=response_text,
                    prompt_estimated_tokens=prompt_data.estimated_input_tokens,
                    budget=transcript_budget,
                    disclosed_paths=invocation_context.transcript_disclosed_paths,
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
                    finish_summary=self._sanitize_and_redact(finish_summary),
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
                    run_dir=run_dir,
                    turn_index=turn_index,
                )
                accumulated_results.extend(step_results)
                bus.emit(
                    "skill_invocation_finished",
                    {
                        "turn_index": turn_index,
                        "step_results": [item.model_dump() for item in step_results],
                    },
                )

                is_self_handoff_only = self._is_self_handoff_only(
                    selected_skill=decision.selected_skill,
                    actions=decision.planned_actions,
                )
                if is_self_handoff_only:
                    consecutive_self_handoff_turns += 1
                    blocked_self_handoff_skill = decision.selected_skill
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
                    blocked_self_handoff_skill = None

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
                    final_summary = finish_summary
                    synthesized_summary = self._synthesize_final_answer(
                        task=task,
                        preliminary_summary=finish_summary,
                        step_results=step_results,
                        provider_router=provider_router,
                        provider_name=provider_name,
                        run_dir=run_dir,
                        turn_index=turn_index,
                        bus=bus,
                        transcript_sink=transcript_sink,
                    )
                    if synthesized_summary:
                        final_summary = synthesized_summary

                    final_summary_path: Path | None = None
                    run_finished_payload: dict[str, Any] = {"turn_index": turn_index}
                    if final_summary:
                        run_finished_payload["final_summary"] = summarize_text(final_summary, 1000)
                        final_summary_path = write_artifact(
                            run_dir,
                            "final_summary.md",
                            f"# Final Summary\n\n{final_summary.strip()}\n",
                        )
                        run_finished_payload["final_summary_artifact"] = str(final_summary_path)
                    bus.emit("run_finished", run_finished_payload)
                    return RunResult(
                        run_id=run_id,
                        status="success",
                        message="Run completed",
                        events_path=sink.path,
                        llm_transcript_path=llm_transcript_path,
                        final_summary_path=final_summary_path,
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
