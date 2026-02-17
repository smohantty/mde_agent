# Architecture Overview

This document describes the system architecture of the Autonomous Skill Agent.

## System Context

```mermaid
C4Context
    title System Context Diagram

    Person(user, "User", "Provides tasks via CLI")
    System(agent, "Autonomous Skill Agent", "Loads skills, routes tasks, executes actions via LLM")
    System_Ext(anthropic, "Anthropic API", "Claude models")
    System_Ext(gemini, "Gemini API", "Google Gemini models")
    System_Ext(mcp, "MCP Servers", "External tool servers via stdio")
    System_Ext(shell, "OS Shell", "bash/pwsh command execution")

    Rel(user, agent, "task + skills_dir")
    Rel(agent, anthropic, "LLM requests")
    Rel(agent, gemini, "LLM requests")
    Rel(agent, mcp, "tool discovery + invocation")
    Rel(agent, shell, "run_command execution")
```

## Module Map

```
agent/
├── cli.py                    # Typer CLI entrypoint
├── config.py                 # Pydantic config models + YAML loading
├── types.py                  # Shared type definitions (ActionType, ModelDecision, etc.)
│
├── llm/                      # LLM abstraction layer
│   ├── base_client.py        # BaseLlmClient ABC + LlmResult
│   ├── anthropic_client.py   # Anthropic provider (Messages API + tool_use)
│   ├── gemini_client.py      # Gemini provider (GenerateContent + function calling)
│   ├── provider_router.py    # ProviderRouter — dispatches to active provider
│   ├── prompt_builder.py     # Builds prompt with task, skills, context, MCP tools
│   ├── structured_output.py  # JSON extraction + agent_decision tool schema
│   ├── decoder.py            # Normalizes raw LLM output → ModelDecision
│   └── token_budget.py       # Token budget allocation
│
├── skills/                   # Skill loading and routing
│   ├── parser.py             # Parses SKILL.md → SkillDefinition
│   ├── registry.py           # SkillRegistry — loads all skills from directory
│   ├── router.py             # SkillRouter — rapidfuzz prefiltering
│   └── disclosure.py         # DisclosureEngine — progressive context stages
│
├── runtime/                  # Orchestration and execution
│   ├── orchestrator.py       # Orchestrator — main run loop (the brain)
│   ├── executor.py           # CommandExecutor — shell subprocess runner
│   ├── retry.py              # Backoff + retryable error classification
│   ├── signals.py            # SIGINT/SIGTERM graceful shutdown
│   ├── policies.py           # Runtime policy definitions
│   ├── state_machine.py      # State machine helpers
│   ├── shell_linux.py        # Linux shell command builder
│   └── shell_windows.py      # Windows shell command builder
│
├── mcp/                      # Model Context Protocol integration
│   └── client.py             # McpManager — sync wrapper over async MCP SDK
│
├── logging/                  # Observability infrastructure
│   ├── events.py             # EventBus — structured JSONL event emission
│   ├── jsonl_sink.py         # JsonlSink — file-backed event writer
│   ├── transcript.py         # LlmTranscriptSink — human-readable LLM logs
│   ├── redaction.py          # Secret redaction + text summarization
│   └── sanitizer.py          # Control character sanitization
│
├── security/                 # Security controls
│   ├── provenance.py         # Path traversal validation for disclosure
│   └── secret_filter.py      # Secret pattern detection
│
└── storage/                  # Run artifact storage
    └── run_store.py          # Run directory creation + artifact writing
```

## Layer Diagram

```mermaid
graph TB
    subgraph "Interface Layer"
        CLI["cli.py<br/>Typer CLI"]
    end

    subgraph "Orchestration Layer"
        ORCH["orchestrator.py<br/>Orchestrator.run()"]
        SIG["signals.py<br/>Graceful shutdown"]
    end

    subgraph "Skill Layer"
        REG["registry.py<br/>SkillRegistry"]
        RTR["router.py<br/>SkillRouter"]
        DISC["disclosure.py<br/>DisclosureEngine"]
        PARSE["parser.py<br/>SKILL.md parser"]
    end

    subgraph "LLM Layer"
        PR["provider_router.py<br/>ProviderRouter"]
        PB["prompt_builder.py<br/>build_prompt()"]
        DEC["decoder.py<br/>decode_model_decision()"]
        SO["structured_output.py<br/>agent_decision schema"]
        AC["anthropic_client.py"]
        GC["gemini_client.py"]
    end

    subgraph "Execution Layer"
        EXEC["executor.py<br/>CommandExecutor"]
        MCP["mcp/client.py<br/>McpManager"]
    end

    subgraph "Observability Layer"
        BUS["events.py<br/>EventBus"]
        SINK["jsonl_sink.py<br/>JsonlSink"]
        TRANS["transcript.py<br/>LlmTranscriptSink"]
        RED["redaction.py"]
    end

    subgraph "Storage Layer"
        STORE["run_store.py"]
    end

    CLI --> ORCH
    ORCH --> REG
    ORCH --> RTR
    ORCH --> DISC
    ORCH --> PB
    ORCH --> PR
    ORCH --> DEC
    ORCH --> EXEC
    ORCH --> MCP
    ORCH --> BUS
    ORCH --> STORE
    ORCH --> SIG

    REG --> PARSE
    PR --> AC
    PR --> GC
    PB --> SO
    BUS --> SINK
    BUS --> RED
    ORCH --> TRANS

    style ORCH fill:#e1f5fe
    style PR fill:#fff3e0
    style MCP fill:#f3e5f5
    style BUS fill:#e8f5e9
```

## Configuration Model

```mermaid
classDiagram
    class AgentConfig {
        +ModelConfig model
        +RuntimeConfig runtime
        +SkillsConfig skills
        +LoggingConfig logging
        +McpConfig mcp
    }

    class ModelConfig {
        +ProviderName provider = "anthropic"
        +str name = "claude-sonnet-4-5"
        +int max_tokens = 4096
        +int max_context_tokens = 32000
        +int response_headroom_tokens = 2000
        +str structured_output_mode
        +dict providers
    }

    class RuntimeConfig {
        +str profile = "permissive"
        +str shell_linux = "/bin/bash"
        +int timeout_seconds = 120
        +int max_turns = 8
        +int max_llm_retries = 3
        +str on_step_failure
    }

    class SkillsConfig {
        +int prefilter_top_k = 8
        +int prefilter_min_score = 55
        +str prefilter_zero_candidate_strategy
        +int disclosure_max_reference_bytes
        +int disclosure_max_reference_tokens
    }

    class LoggingConfig {
        +str jsonl_dir = "./runs"
        +bool redact_secrets = true
        +bool llm_transcript_enabled = true
        +str llm_transcript_filename
    }

    class McpConfig {
        +bool enabled = true
        +int tool_call_timeout_seconds = 60
        +dict~str,McpServerConfig~ servers
    }

    class McpServerConfig {
        +str command
        +list~str~ args
        +dict~str,str~ env
        +int timeout_seconds = 30
    }

    AgentConfig *-- ModelConfig
    AgentConfig *-- RuntimeConfig
    AgentConfig *-- SkillsConfig
    AgentConfig *-- LoggingConfig
    AgentConfig *-- McpConfig
    McpConfig *-- McpServerConfig
```

Config is loaded from `agent.yaml` with discovery precedence:
1. `--config <path>` CLI flag
2. `./agent.yaml` (working directory)
3. `~/.config/agent/agent.yaml` (user home)
4. Built-in defaults (all fields have defaults)

## Provider Abstraction

```mermaid
classDiagram
    class BaseLlmClient {
        <<abstract>>
        +str provider
        +complete_structured(prompt, model, max_tokens, attempt, tools, force_tool_use) LlmResult
    }

    class AnthropicClient {
        +str provider = "anthropic"
        +complete_structured() LlmResult
    }

    class GeminiClient {
        +str provider = "gemini"
        +complete_structured() LlmResult
    }

    class ProviderRouter {
        -dict~str,BaseLlmClient~ _clients
        +has_provider(provider) bool
        +complete_structured(provider, prompt, model, ...) LlmResult
    }

    class LlmResult {
        +dict|str data
        +LlmRequestMeta meta
    }

    BaseLlmClient <|-- AnthropicClient
    BaseLlmClient <|-- GeminiClient
    ProviderRouter o-- BaseLlmClient
    BaseLlmClient ..> LlmResult
```

### Structured Output Modes

| Mode | Behavior |
|------|----------|
| `json_only` | LLM returns raw JSON text, parsed by `extract_json_payload()` |
| `native_with_json_fallback` | Uses provider tool_use/function_calling; falls back to JSON on failure |
| `native_only` | Requires tool_use/function_calling; fails if not returned |

Both providers use the same `agent_decision` tool schema (defined in `structured_output.py`).
The orchestrator never sees provider-specific formats — `ProviderRouter` normalizes everything to `LlmResult`.

## Skill System

```mermaid
classDiagram
    class SkillDefinition {
        +SkillMetadata metadata
        +dict frontmatter
        +Path skill_dir
        +str body
        +dict~str,str~ sections
        +list~str~ references
        +list~str~ scripts
    }

    class SkillMetadata {
        +str name
        +str description
        +list~str~ tags
        +str version
        +list~str~ allowed_tools
        +list~str~ references_index
        +dict~str,str~ action_aliases
        +dict~str,dict~ default_action_params
    }

    class SkillRegistry {
        +Path skills_dir
        +load() list~SkillDefinition~
        +by_name(skills, name) SkillDefinition?
    }

    class SkillRouter {
        +int min_score
        +prefilter(task, skills, top_k) list~SkillCandidate~
    }

    class DisclosureEngine {
        +int max_bytes
        +int max_tokens
        +stage1(skill) DisclosedContext
        +stage2(skill, paths) DisclosedContext
        +stage3(skill) DisclosedContext
    }

    SkillDefinition *-- SkillMetadata
    SkillRegistry ..> SkillDefinition : loads
    SkillRouter ..> SkillDefinition : scores
    DisclosureEngine ..> SkillDefinition : discloses
```

### Progressive Disclosure Stages

| Stage | What is disclosed | When |
|-------|-------------------|------|
| **0** | Metadata catalog only (name, description, tags, allowed_tools) | Always — `ALL_SKILL_FRONTMATTER` in every prompt |
| **1** | First 2 body sections from SKILL.md | Before first LLM call, for the top candidate |
| **2** | Requested reference files (path-validated) | When LLM requests `required_disclosure_paths` |
| **3** | Script descriptors | On demand |

Stage 2 enforces **provenance validation** — paths must resolve within the skill directory (no path traversal).

## Action System

```mermaid
classDiagram
    class ActionStep {
        +ActionType type
        +dict params
        +str? expected_output
    }

    class ModelDecision {
        +str? selected_skill
        +str reasoning_summary
        +list~str~ required_disclosure_paths
        +list~ActionStep~ planned_actions
    }

    class StepExecutionResult {
        +str step_id
        +int exit_code
        +str stdout_summary
        +str stderr_summary
        +int retry_count
        +str status
        +str? stdout_artifact
    }
```

### Canonical Action Types

| Action | `params` schema | Executed by |
|--------|----------------|-------------|
| `run_command` | `{"command": "shell command"}` | `CommandExecutor.run()` |
| `call_skill` | `{"skill_name": "target-skill"}` | Orchestrator (disclosure + re-prompt) |
| `mcp_call` | `{"tool_name": "name", "arguments": {...}}` | `McpManager.call_tool()` |
| `ask_user` | `{"message": "question"}` | Skipped in non-interactive mode |
| `finish` | `{"message": "summary"}` | Triggers final answer synthesis |

### Decoder Normalization

The decoder (`decoder.py`) normalizes raw LLM output to canonical action types:

```mermaid
flowchart LR
    RAW["Raw LLM output<br/>(varied key names)"] --> NORM["normalize_provider_output()<br/>JSON extraction"]
    NORM --> REPAIR["_repair_payload()<br/>Add missing fields"]
    REPAIR --> RESOLVE["_resolve_action_type()<br/>Alias resolution"]
    RESOLVE --> VALIDATE["_normalize_action_step()<br/>Param validation"]
    VALIDATE --> MD["ModelDecision<br/>Pydantic validated"]

    subgraph "Alias Resolution Order"
        A1["1. Selected skill aliases"]
        A2["2. All skill aliases"]
        A3["3. Base aliases"]
    end
```

Base aliases include:
- `execute_skill` / `invoke_skill` / `use_skill` → `call_skill`
- `run` / `run_shell` / `execute_command` → `run_command`
- `mcp_tool` / `mcp_invoke` / `call_mcp` / `use_mcp_tool` / `mcp` → `mcp_call`
- `complete` / `format_output` / `summarize_output` → `finish`
