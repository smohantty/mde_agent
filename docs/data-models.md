# Data Models and Type System

All shared types are defined in `agent/types.py` as Pydantic models.

## Core Type Literals

```python
ActionType = Literal["call_skill", "run_command", "ask_user", "finish", "mcp_call"]
ResponseKind = Literal["skill_call", "tool_call", "response"]
LlmTranscriptStatus = Literal["success", "request_failed", "decode_failed"]
LlmCallSite = Literal["decision_loop", "final_answer_synthesis", "unspecified"]
ProviderName = Literal["anthropic", "gemini"]
```

## Data Flow Diagram

```mermaid
flowchart LR
    subgraph Input
        TASK["Task (string)"]
        SKILLS["SKILL.md files"]
        CONFIG["agent.yaml"]
        MCP_SRV["MCP Servers"]
    end

    subgraph "Skill Loading"
        SD["SkillDefinition"]
        SM["SkillMetadata"]
        SC["SkillCandidate"]
        DC["DisclosedContext"]
    end

    subgraph "LLM Interaction"
        PBR["PromptBuildResult"]
        TB["TokenBudget"]
        LR2["LlmResult"]
        MD["ModelDecision"]
        AS["ActionStep"]
    end

    subgraph "Execution"
        CE["CommandExecution"]
        MCR["McpCallResult"]
        SER["StepExecutionResult"]
    end

    subgraph "Output"
        RR["RunResult"]
        ER["EventRecord"]
        TR["LlmTranscriptRecord"]
        ART["Artifacts (files)"]
    end

    SKILLS --> SD
    SD --> SM
    SM --> SC
    SD --> DC

    TASK --> PBR
    SC --> PBR
    DC --> PBR
    CONFIG --> TB
    TB --> PBR

    PBR --> LR2
    LR2 --> MD
    MD --> AS

    AS -->|run_command| CE
    AS -->|mcp_call| MCR
    CE --> SER
    MCR --> SER

    SER --> RR
    SER --> ART
    MD --> ER
    LR2 --> TR

    style MD fill:#e1f5fe
    style AS fill:#fff3e0
    style SER fill:#e8f5e9
```

## Model Decision (LLM Output)

```mermaid
classDiagram
    class ModelDecision {
        +str? selected_skill
        +str reasoning_summary
        +list~str~ required_disclosure_paths
        +list~ActionStep~ planned_actions
    }

    class ActionStep {
        +ActionType type
        +dict~str,Any~ params
        +str? expected_output
    }

    ModelDecision *-- ActionStep

    note for ModelDecision "Produced by decode_model_decision()\nfrom raw LLM response"
    note for ActionStep "type is one of:\nrun_command, call_skill,\nmcp_call, ask_user, finish"
```

### ActionStep Params by Type

| ActionType | Required params | Optional params |
|------------|----------------|-----------------|
| `run_command` | `command: str` | — |
| `call_skill` | `skill_name: str` | `instructions: str` |
| `mcp_call` | `tool_name: str`, `arguments: dict` | — |
| `ask_user` | `message: str` | — |
| `finish` | — | `message: str`, `summary: str`, `result: str` |

## Execution Results

```mermaid
classDiagram
    class StepExecutionResult {
        +str step_id
        +int exit_code
        +str stdout_summary
        +str stderr_summary
        +int retry_count
        +Literal~success,failed,skipped~ status
        +str? stdout_artifact
        +str? stderr_artifact
    }

    class CommandExecution {
        +str command
        +int exit_code
        +str stdout
        +str stderr
    }

    class McpCallResult {
        +str server_name
        +str tool_name
        +list~dict~ content
        +bool is_error
        +str raw_text
    }

    class RunResult {
        +str run_id
        +str status
        +str message
        +Path events_path
        +Path? llm_transcript_path
        +Path? final_summary_path
    }

    CommandExecution ..> StepExecutionResult : mapped to
    McpCallResult ..> StepExecutionResult : mapped to
    StepExecutionResult ..> RunResult : aggregated into
```

## Event System

```mermaid
classDiagram
    class EventRecord {
        +str run_id
        +str trace_id
        +str span_id
        +str timestamp
        +str event_type
        +dict payload
        +Literal~full,redacted~ redaction_mode
    }

    class EventBus {
        -JsonlSink _sink
        -EventContext _context
        -bool _redact
        -bool _sanitize
        -Callable? _on_emit
        +emit(event_type, payload) EventRecord
    }

    class EventContext {
        +str run_id
        +str trace_id
    }

    class JsonlSink {
        +Path path
        +write(record)
    }

    EventBus --> JsonlSink : writes to
    EventBus --> EventContext : uses
    EventBus ..> EventRecord : produces
```

### Event Types Reference

| Event | Phase | Payload |
|-------|-------|---------|
| `run_started` | Start | task, provider, dry_run, max_turns |
| `skill_catalog_loaded` | Load | skills_count, skills_dir |
| `skill_prefilter_completed` | Route | candidates, candidate_count |
| `skill_disclosure_loaded` | Disclose | stage, paths, total_bytes, total_tokens |
| `mcp_servers_connected` | MCP | server_count, tool_count, tools |
| `mcp_connection_failed` | MCP | error |
| `prompt_budget_computed` | Prompt | token budget breakdown |
| `prompt_composed` | Prompt | prompt_hash, estimated_input_tokens |
| `llm_request_sent` | LLM | provider, model, attempt, turn_index, call_site |
| `llm_response_received` | LLM | turn_index, call_site, meta, response_preview |
| `llm_request_failed` | LLM | error, retryable, call_site |
| `llm_retry_scheduled` | LLM | delay_seconds, attempt |
| `native_tool_fallback` | LLM | turn_index, reason |
| `llm_decision_decoded` | Decode | turn_index, selected_skill, planned_actions |
| `self_handoff_detected` | Loop | selected_skill, count |
| `self_handoff_constraint_applied` | Loop | blocked_skill |
| `self_handoff_recovery_applied` | Loop | recovery_action_types |
| `skill_invocation_started` | Execute | turn_index, selected_skill |
| `skill_step_executed` | Execute | step_id, type, status, command |
| `step_retry_scheduled` | Execute | step_id, retry_count |
| `mcp_tool_call_started` | MCP | step_id, tool_name |
| `mcp_tool_call_completed` | MCP | step_id, tool_name, server, status |
| `mcp_tool_call_failed` | MCP | step_id, tool_name, error |
| `skill_invocation_finished` | Execute | step_results |
| `final_answer_synthesis_started` | Synth | evidence_items |
| `final_answer_synthesis_completed` | Synth | summary_preview |
| `final_answer_synthesis_failed` | Synth | reason |
| `mcp_servers_disconnected` | Cleanup | — |
| `run_finished` | End | turn_index, final_summary |
| `run_failed` | End | reason |

## LLM Transcript Record

```mermaid
classDiagram
    class LlmTranscriptRecord {
        +int turn_index
        +int attempt
        +LlmCallSite call_site
        +ProviderName provider
        +str model
        +LlmTranscriptStatus status
        +str? raw_request_text
        +str prompt_text
        +str? response_text
        +int prompt_estimated_tokens
        +LlmTranscriptBudget budget
        +list~str~ disclosed_paths
        +LlmTranscriptUsage usage
        +bool decode_success
        +str? selected_skill
        +list~str~ raw_action_types
        +list~ActionType~ planned_action_types
        +list~str~ required_disclosure_paths
        +ResponseKind response_kind
        +str? response_kind_reason
        +str? finish_summary
        +str? error
        +bool? retryable
    }

    class LlmTranscriptBudget {
        +int max_context_tokens
        +int response_headroom_tokens
        +int allocated_prompt_tokens
        +int allocated_disclosure_tokens
    }

    class LlmTranscriptUsage {
        +int? input_tokens
        +int? output_tokens
        +int? latency_ms
    }

    LlmTranscriptRecord *-- LlmTranscriptBudget
    LlmTranscriptRecord *-- LlmTranscriptUsage
```

## Response Kind Classification

```mermaid
flowchart TD
    ACTIONS["Normalized action types"] --> CHECK_SKILL{Contains<br/>call_skill?}
    CHECK_SKILL -->|yes| SKILL_CALL["skill_call"]
    CHECK_SKILL -->|no| CHECK_TOOL{Contains<br/>run_command<br/>or mcp_call?}
    CHECK_TOOL -->|yes| TOOL_CALL["tool_call"]
    CHECK_TOOL -->|no| RESPONSE["response"]

    style SKILL_CALL fill:#e1f5fe
    style TOOL_CALL fill:#fff3e0
    style RESPONSE fill:#e8f5e9
```

## Run Directory Structure

```
runs/<run_id>/
├── events.jsonl                  # All EventRecord entries
├── llm_transcript.log            # Human-readable LLM attempt logs
├── dry_run_prompt.txt            # (dry-run only) Full prompt text
├── final_summary.md              # Synthesized final answer
└── artifacts/
    ├── llm/
    │   ├── decision_loop_turn_1_attempt_1_request.txt
    │   ├── decision_loop_turn_1_attempt_1_response.txt
    │   ├── final_answer_synthesis_turn_3_attempt_1_request.txt
    │   └── final_answer_synthesis_turn_3_attempt_1_response.txt
    ├── turn_1_step-1_stdout.txt
    ├── turn_1_step-1_stderr.txt
    ├── turn_2_step-1_mcp_stdout.txt
    └── final_answer_prompt_turn_3.txt
```
