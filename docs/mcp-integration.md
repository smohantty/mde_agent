# MCP (Model Context Protocol) Integration

MCP enables the agent to connect to external tool servers and invoke their tools during task execution.

## Architecture

```mermaid
graph TB
    subgraph "Agent Process (sync)"
        ORCH["Orchestrator"]
        MGR["McpManager<br/>(sync API)"]
    end

    subgraph "Background Thread"
        LOOP["asyncio event loop<br/>(daemon thread)"]
        STACK["AsyncExitStack<br/>(connection lifetime)"]
    end

    subgraph "MCP Servers (stdio)"
        S1["Server 1<br/>e.g. filesystem"]
        S2["Server 2<br/>e.g. github"]
    end

    ORCH -->|"connect_all()"| MGR
    ORCH -->|"call_tool()"| MGR
    ORCH -->|"close_all()"| MGR
    MGR -->|"run_coroutine_threadsafe()"| LOOP
    LOOP --> STACK
    STACK -->|"stdio_client()"| S1
    STACK -->|"stdio_client()"| S2

    style MGR fill:#f3e5f5
    style LOOP fill:#e8eaf6
```

## Async Bridging Pattern

The MCP Python SDK is async; the orchestrator is sync. `McpManager` bridges this gap:

```mermaid
sequenceDiagram
    participant ORCH as Orchestrator (sync)
    participant MGR as McpManager
    participant LOOP as Background asyncio loop
    participant SDK as MCP SDK (async)

    Note over MGR,LOOP: _start_loop(): creates event loop in daemon thread

    ORCH->>MGR: connect_all(servers)
    MGR->>LOOP: run_coroutine_threadsafe(_async_connect_all)
    LOOP->>SDK: stdio_client(params)
    SDK-->>LOOP: (read_stream, write_stream)
    LOOP->>SDK: ClientSession(streams)
    SDK-->>LOOP: session
    LOOP->>SDK: session.initialize()
    LOOP->>SDK: session.list_tools()
    SDK-->>LOOP: tools list
    LOOP-->>MGR: list[McpToolInfo]
    MGR-->>ORCH: list[McpToolInfo]

    ORCH->>MGR: call_tool("read_file", {path: "/tmp/x"})
    MGR->>MGR: _tool_server_map["read_file"] → "filesystem"
    MGR->>LOOP: run_coroutine_threadsafe(_async_call_tool)
    LOOP->>SDK: session.call_tool("read_file", arguments)
    SDK-->>LOOP: result
    LOOP-->>MGR: McpCallResult
    MGR-->>ORCH: McpCallResult

    ORCH->>MGR: close_all()
    MGR->>LOOP: run_coroutine_threadsafe(_async_close_all)
    LOOP->>SDK: exit_stack.aclose()
    MGR->>MGR: _stop_loop()
```

## McpManager Class

```mermaid
classDiagram
    class McpManager {
        -dict~str,_ServerSession~ _sessions
        -list~McpToolInfo~ _tools
        -dict~str,str~ _tool_server_map
        -asyncio.AbstractEventLoop? _loop
        -threading.Thread? _thread
        -AsyncExitStack? _exit_stack
        +tools: list~McpToolInfo~
        +connect_all(servers) list~McpToolInfo~
        +call_tool(tool_name, arguments, timeout) McpCallResult
        +close_all() void
    }

    class McpToolInfo {
        +str server_name
        +str name
        +str description
        +dict input_schema
    }

    class McpCallResult {
        +str server_name
        +str tool_name
        +list~dict~ content
        +bool is_error
        +str raw_text
    }

    class _ServerSession {
        +str server_name
        +Any session
    }

    McpManager o-- _ServerSession
    McpManager ..> McpToolInfo : discovers
    McpManager ..> McpCallResult : produces
```

## Configuration

```yaml
# agent.yaml
mcp:
  enabled: true
  tool_call_timeout_seconds: 60
  servers:
    filesystem:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
      timeout_seconds: 15
    github:
      command: "uvx"
      args: ["mcp-server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

## MCP in the Prompt

When MCP servers are connected, discovered tools appear in the `MCP_TOOLS` prompt section:

```json
MCP_TOOLS:
[
  {
    "name": "read_file",
    "description": "Read a file from the filesystem",
    "server": "filesystem",
    "input_schema": {
      "type": "object",
      "properties": {
        "path": {"type": "string"}
      },
      "required": ["path"]
    }
  }
]
```

The LLM uses `mcp_call` actions to invoke these tools:

```json
{
  "type": "mcp_call",
  "params": {
    "tool_name": "read_file",
    "arguments": {"path": "/tmp/test.txt"}
  }
}
```

## MCP Lifecycle in the Orchestrator

```mermaid
flowchart TD
    START["Orchestrator.run()"] --> CHECK{MCP enabled<br/>AND servers configured?}
    CHECK -->|no| SKIP["No MCP<br/>(mcp_tool_catalog = [])"]
    CHECK -->|yes| CONNECT["McpManager().connect_all(servers)"]

    CONNECT -->|success| CATALOG["Build mcp_tool_catalog<br/>emit mcp_servers_connected"]
    CONNECT -->|exception| FAIL_CONN["emit mcp_connection_failed<br/>mcp_manager = None<br/>Continue without MCP"]

    CATALOG --> PROMPT["Pass mcp_tools to build_prompt()"]
    SKIP --> PROMPT
    FAIL_CONN --> PROMPT

    PROMPT --> TURN_LOOP["Decision loop turns"]
    TURN_LOOP --> ACTIONS{Action type?}

    ACTIONS -->|mcp_call| VALIDATE{tool_name present<br/>AND manager != None?}
    VALIDATE -->|yes| INVOKE["emit mcp_tool_call_started<br/>McpManager.call_tool()"]
    VALIDATE -->|no| MCP_ERR["emit mcp_tool_call_failed<br/>Return failed"]
    INVOKE -->|success| MCP_OK["Write result artifact<br/>emit mcp_tool_call_completed"]
    INVOKE -->|exception| MCP_EXC["emit mcp_tool_call_failed<br/>Return failed"]
    INVOKE -->|is_error=true| MCP_TOOL_ERR["emit mcp_tool_call_completed<br/>status=failed<br/>Return failed"]

    TURN_LOOP --> CLEANUP

    subgraph CLEANUP ["finally block (always runs)"]
        CL_CHECK{mcp_manager<br/>!= None?}
        CL_CHECK -->|yes| CLOSE["McpManager.close_all()<br/>emit mcp_servers_disconnected"]
        CL_CHECK -->|no| DONE["Done"]
    end

    style MCP_ERR fill:#ffcdd2
    style MCP_EXC fill:#ffcdd2
    style MCP_TOOL_ERR fill:#ffcdd2
    style FAIL_CONN fill:#fff9c4
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `mcp` package not installed | `connect_all()` raises ImportError; caught, run continues without MCP |
| Server connection failure | `mcp_connection_failed` event; `mcp_manager = None`; no MCP tools in prompt |
| Tool call returns `is_error=true` | `StepExecutionResult` with `status="failed"`; follows `on_step_failure` policy |
| Tool call raises exception | Caught; `mcp_tool_call_failed` event; step fails |
| Unknown tool name | `McpManager.call_tool()` returns error result (no matching server) |
| Server crash mid-run | `call_tool()` raises; caught by executor try/except |
| Cleanup failure | Suppressed via `try/except` in `finally` block |

## Tool Name Routing

`McpManager` maintains an internal `_tool_server_map: dict[str, str]` that maps tool names to server names. When `connect_all()` discovers tools from each server, it populates this map. If two servers expose a tool with the same name, the last-connected server wins (documented limitation).

```mermaid
flowchart LR
    CALL["call_tool('read_file', args)"] --> LOOKUP["_tool_server_map['read_file']"]
    LOOKUP -->|found| ROUTE["Route to server 'filesystem'"]
    LOOKUP -->|not found| ERROR["Return error:<br/>Unknown MCP tool"]
    ROUTE --> SESSION["_sessions['filesystem'].session"]
    SESSION --> INVOKE["session.call_tool('read_file', args)"]
```

## Installation

MCP is an optional dependency:

```bash
# Install with MCP support
pip install 'autonomous-skill-agent[mcp]'

# Or via uv
uv sync --extra mcp
```

The `mcp` SDK import is lazy (inside `_async_connect_all()`), so the agent works without it installed when MCP is not configured.
