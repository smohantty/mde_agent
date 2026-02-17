# Decision Loop — Orchestrator Runtime

This document describes the orchestrator's main run loop with sequence diagrams showing exact control flow as implemented in `agent/runtime/orchestrator.py`.

## High-Level Run Flow

```mermaid
flowchart TD
    START([CLI: agent run]) --> CONFIG[Load config]
    CONFIG --> SKILLS[Load skills from skills_dir]
    SKILLS --> PREFILTER[SkillRouter.prefilter<br/>rapidfuzz scoring]
    PREFILTER --> DISCLOSE1[DisclosureEngine.stage1<br/>Top candidate sections]
    DISCLOSE1 --> MCP_INIT{MCP servers<br/>configured?}
    MCP_INIT -->|yes| MCP_CONN[McpManager.connect_all<br/>Discover tools]
    MCP_INIT -->|no| DRY{Dry run?}
    MCP_CONN --> DRY
    MCP_CONN -->|failure| MCP_FAIL[Log mcp_connection_failed<br/>Continue without MCP]
    MCP_FAIL --> DRY
    DRY -->|yes| PROMPT_SAVE[Save prompt to artifact<br/>Return success]
    DRY -->|no| KEY_CHECK{Provider key<br/>available?}
    KEY_CHECK -->|no| FAIL_KEY[Return failed:<br/>missing_provider_api_key]
    KEY_CHECK -->|yes| LOOP

    subgraph LOOP ["Turn Loop (1..max_turns)"]
        SIGNAL{Signal<br/>received?}
        SIGNAL -->|yes| SHUTDOWN[Graceful shutdown]
        SIGNAL -->|no| BUILD_PROMPT[build_prompt with<br/>task + skills + context +<br/>step_results + MCP tools]
        BUILD_PROMPT --> LLM_CALL[_invoke_llm_with_logging<br/>with retry]
        LLM_CALL --> FALLBACK{Native tool<br/>failed?}
        FALLBACK -->|json fallback| LLM_CALL2[Retry without tools]
        FALLBACK -->|no| DECODE
        LLM_CALL2 --> DECODE
        DECODE[decode_model_decision<br/>Normalize actions] --> HANDOFF{Self-handoff<br/>loop?}
        HANDOFF -->|yes, count>=2| RECOVER[Inject recovery<br/>actions + finish]
        HANDOFF -->|no| EXECUTE
        RECOVER --> EXECUTE
        EXECUTE[_execute_actions<br/>run_command / mcp_call /<br/>call_skill / finish] --> FINISHED{finish action<br/>present?}
        FINISHED -->|yes| SYNTHESIZE[_synthesize_final_answer<br/>2nd LLM call]
        SYNTHESIZE --> SUCCESS([Return success])
        FINISHED -->|no| STEP_FAIL{Step<br/>failed?}
        STEP_FAIL -->|yes| FAIL([Return failed])
        STEP_FAIL -->|no| DISCLOSE2{LLM requested<br/>disclosure?}
        DISCLOSE2 -->|yes| STAGE2[DisclosureEngine.stage2<br/>Load references]
        DISCLOSE2 -->|no| SIGNAL
        STAGE2 --> SIGNAL
    end

    LOOP --> MAX_TURNS([Return failed:<br/>max_turns_exceeded])

    style LOOP fill:#f5f5f5
    style SUCCESS fill:#c8e6c9
    style FAIL fill:#ffcdd2
    style FAIL_KEY fill:#ffcdd2
    style MAX_TURNS fill:#ffcdd2
    style SHUTDOWN fill:#fff9c4
```

## Detailed Sequence: Successful Run

```mermaid
sequenceDiagram
    participant CLI as CLI
    participant ORCH as Orchestrator
    participant REG as SkillRegistry
    participant RTR as SkillRouter
    participant DISC as DisclosureEngine
    participant MCP as McpManager
    participant PB as PromptBuilder
    participant PR as ProviderRouter
    participant DEC as Decoder
    participant EXEC as CommandExecutor
    participant BUS as EventBus
    participant STORE as RunStore

    CLI->>ORCH: run(task, skills_dir)
    ORCH->>STORE: create_run_dir()
    ORCH->>BUS: emit("run_started")

    rect rgb(230, 245, 255)
    Note over ORCH,DISC: Phase 1: Skill Loading & Routing
    ORCH->>REG: load()
    REG-->>ORCH: list[SkillDefinition]
    ORCH->>RTR: prefilter(task, skills, top_k)
    RTR-->>ORCH: list[SkillCandidate]
    ORCH->>DISC: stage1(primary_skill)
    DISC-->>ORCH: DisclosedContext (sections)
    end

    rect rgb(243, 229, 245)
    Note over ORCH,MCP: Phase 2: MCP Connection (if configured)
    ORCH->>MCP: connect_all(servers)
    MCP-->>ORCH: list[McpToolInfo]
    ORCH->>BUS: emit("mcp_servers_connected")
    end

    rect rgb(255, 243, 224)
    Note over ORCH,DEC: Phase 3: Decision Loop (Turn 1)
    ORCH->>PB: build_prompt(task, candidates, context, mcp_tools)
    PB-->>ORCH: PromptBuildResult
    ORCH->>PR: complete_structured(prompt, model, tools)
    PR-->>ORCH: LlmResult
    ORCH->>BUS: emit("llm_response_received")
    ORCH->>DEC: decode_model_decision(raw_data)
    DEC-->>ORCH: ModelDecision
    ORCH->>BUS: emit("llm_decision_decoded")
    end

    rect rgb(232, 245, 233)
    Note over ORCH,EXEC: Phase 4: Action Execution
    ORCH->>EXEC: run(command) [for run_command actions]
    EXEC-->>ORCH: CommandExecution
    ORCH->>STORE: write_artifact(stdout)
    ORCH->>BUS: emit("skill_step_executed")
    end

    rect rgb(255, 253, 231)
    Note over ORCH,PR: Phase 5: Final Answer Synthesis
    ORCH->>PR: complete_structured(synthesis_prompt)
    PR-->>ORCH: LlmResult (final_answer)
    ORCH->>STORE: write_artifact("final_summary.md")
    ORCH->>BUS: emit("run_finished")
    end

    rect rgb(243, 229, 245)
    Note over ORCH,MCP: Phase 6: Cleanup
    ORCH->>MCP: close_all()
    ORCH->>BUS: emit("mcp_servers_disconnected")
    end

    ORCH-->>CLI: RunResult(status="success")
```

## LLM Invocation with Retry

Every LLM call goes through `_invoke_llm_with_logging()`:

```mermaid
sequenceDiagram
    participant ORCH as Orchestrator
    participant PR as ProviderRouter
    participant BUS as EventBus
    participant STORE as RunStore
    participant TRANS as TranscriptSink

    loop attempt = 1..max_llm_retries+1
        ORCH->>STORE: write request artifact
        ORCH->>BUS: emit("llm_request_sent")
        ORCH->>PR: complete_structured(prompt, model, attempt)
        alt success
            PR-->>ORCH: LlmResult
            ORCH->>BUS: emit("llm_response_received")
            ORCH->>STORE: write response artifact
            Note over ORCH: Return LlmInvocationResult
        else failure
            PR--xORCH: Exception
            ORCH->>TRANS: write(request_failed record)
            ORCH->>BUS: emit("llm_request_failed")
            alt retryable AND attempts remaining
                ORCH->>BUS: emit("llm_retry_scheduled")
                Note over ORCH: sleep(backoff)
            else not retryable OR no attempts left
                Note over ORCH: Return with llm_error set
            end
        end
    end
```

Retryable status codes: `429, 500, 502, 503, 529`.
Non-retryable (fail fast): `400, 401, 403, 404`.

## Native Tool Use Fallback

```mermaid
flowchart TD
    MODE{structured_output_mode}
    MODE -->|json_only| JSON_CALL[LLM call without tools<br/>Parse JSON from text]
    MODE -->|native_with_json_fallback| NATIVE[LLM call with<br/>agent_decision tool]
    MODE -->|native_only| FORCED[LLM call with<br/>forced tool_use]

    NATIVE -->|success| DECODE[Decode response]
    NATIVE -->|failure| FALLBACK[Rebuild prompt<br/>without tools]
    FALLBACK --> JSON_RETRY[LLM call as JSON<br/>emit native_tool_fallback]
    JSON_RETRY --> DECODE

    FORCED -->|success| DECODE
    FORCED -->|failure| FAIL[Run fails]

    style FALLBACK fill:#fff3e0
    style FAIL fill:#ffcdd2
```

## Self-Handoff Detection & Recovery

When the LLM repeatedly emits `call_skill` to the same skill without producing new executable work:

```mermaid
sequenceDiagram
    participant LLM as LLM
    participant ORCH as Orchestrator

    Note over LLM,ORCH: Turn N: LLM selects skill X, emits call_skill(X)
    ORCH->>ORCH: _is_self_handoff_only() → true
    ORCH->>ORCH: consecutive_self_handoff_turns = 1
    ORCH->>ORCH: blocked_self_handoff_skill = X

    Note over LLM,ORCH: Turn N+1: Prompt includes RUN_CONSTRAINTS blocking X
    LLM->>ORCH: Still emits call_skill(X)
    ORCH->>ORCH: consecutive_self_handoff_turns = 2
    ORCH->>ORCH: _build_self_handoff_recovery_actions(skill)
    Note over ORCH: Recovery: run skill's default_action_params commands + finish
    ORCH->>ORCH: Execute recovery actions
```

Recovery uses the skill's own `default_action_params` (from SKILL.md frontmatter) to extract up to 2 runnable commands. If the skill has no defaults, recovery is just a `finish` action.

## Action Execution Flow

```mermaid
flowchart TD
    START[planned_actions list] --> LOOP{Next action}

    LOOP --> FINISH_ACT["type: finish"]
    LOOP --> RUN_CMD["type: run_command"]
    LOOP --> CALL_SKILL["type: call_skill"]
    LOOP --> MCP_CALL["type: mcp_call"]
    LOOP --> ASK_USER["type: ask_user"]

    FINISH_ACT --> SET_FINISH[Set should_finish=true<br/>Record StepExecutionResult]
    SET_FINISH --> LOOP

    RUN_CMD --> NORMALIZE[_normalize_command<br/>Add workspace exclusions]
    NORMALIZE --> SHELL[CommandExecutor.run]
    SHELL --> CMD_OK{exit_code == 0?}
    CMD_OK -->|yes| ARTIFACT[Write stdout/stderr artifacts]
    CMD_OK -->|no & retry policy| RETRY_CMD[Retry once]
    RETRY_CMD --> CMD_OK2{exit_code == 0?}
    CMD_OK2 -->|yes| ARTIFACT
    CMD_OK2 -->|no| FAIL_EARLY[Return partial results, should_finish=false]
    ARTIFACT --> LOOP

    CALL_SKILL --> RECORD_HANDOFF[Record handoff in results]
    RECORD_HANDOFF --> LOOP

    MCP_CALL --> VALIDATE_MCP{tool_name present<br/>AND manager available?}
    VALIDATE_MCP -->|no| MCP_FAIL[Return failed]
    VALIDATE_MCP -->|yes| MCP_INVOKE[McpManager.call_tool]
    MCP_INVOKE --> MCP_OK{is_error?}
    MCP_OK -->|no| MCP_ARTIFACT[Write MCP result artifact]
    MCP_OK -->|yes| MCP_FAIL
    MCP_ARTIFACT --> LOOP

    ASK_USER --> SKIP[Record as skipped<br/>Non-interactive mode]
    SKIP --> LOOP

    style FAIL_EARLY fill:#ffcdd2
    style MCP_FAIL fill:#ffcdd2
```

## Final Answer Synthesis

After the LLM emits a `finish` action, the orchestrator optionally makes a second LLM call to synthesize a better answer from tool evidence:

```mermaid
flowchart TD
    FINISH["finish action executed"] --> COLLECT["_collect_tool_evidence()<br/>Gather stdout from successful steps"]
    COLLECT --> HAS_EVIDENCE{Evidence<br/>found?}
    HAS_EVIDENCE -->|no| USE_PRELIMINARY["Use LLM's preliminary<br/>finish summary as-is"]
    HAS_EVIDENCE -->|yes| BUILD_SYNTH["Build synthesis prompt<br/>TASK + PRELIMINARY_SUMMARY +<br/>TOOL_EVIDENCE"]
    BUILD_SYNTH --> LLM2["2nd LLM call<br/>call_site=final_answer_synthesis"]
    LLM2 --> EXTRACT["_extract_final_answer()<br/>Parse final_answer from JSON"]
    EXTRACT --> HAS_ANSWER{Extracted?}
    HAS_ANSWER -->|yes| USE_SYNTH["Use synthesized answer"]
    HAS_ANSWER -->|no| USE_PRELIMINARY

    USE_SYNTH --> WRITE["write_artifact('final_summary.md')"]
    USE_PRELIMINARY --> WRITE
    WRITE --> DONE["emit('run_finished')"]
```

## Prompt Structure

Each decision loop prompt contains these sections in order:

```
┌─────────────────────────────────────────────┐
│ INSTRUCTION                                  │
│ (Rules for action types, tool usage, etc.)   │
├─────────────────────────────────────────────┤
│ TASK                                         │
│ (User's original task text)                  │
├─────────────────────────────────────────────┤
│ RUN_STATE                                    │
│ (executed_steps with stdout/stderr summaries)│
├─────────────────────────────────────────────┤
│ RUN_CONSTRAINTS (if any)                     │
│ (blocked_call_skill_targets for self-handoff)│
├─────────────────────────────────────────────┤
│ ALL_SKILL_FRONTMATTER                        │
│ (Lightweight catalog: name, desc, tags, etc.)│
├─────────────────────────────────────────────┤
│ CANDIDATE_SKILLS                             │
│ (Prefilter results with scores)              │
├─────────────────────────────────────────────┤
│ DISCLOSED_CONTEXT                            │
│ (Stage 1/2 skill content loaded so far)      │
├─────────────────────────────────────────────┤
│ MCP_TOOLS (if MCP servers connected)         │
│ (Tool name, description, server, schema)     │
└─────────────────────────────────────────────┘
```

The LLM returns a `ModelDecision`:
```json
{
  "selected_skill": "skill-name or null",
  "reasoning_summary": "why",
  "required_disclosure_paths": ["references/file.md"],
  "planned_actions": [
    {"type": "run_command", "params": {"command": "ls -la"}},
    {"type": "finish", "params": {"message": "Done"}}
  ]
}
```
