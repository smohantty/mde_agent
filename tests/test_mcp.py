from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.config import AgentConfig, McpServerConfig
from agent.llm.base_client import LlmResult
from agent.llm.decoder import decode_model_decision
from agent.llm.prompt_builder import build_prompt
from agent.llm.provider_router import ProviderRouter
from agent.llm.structured_output import build_agent_decision_tool_schema
from agent.mcp.client import McpCallResult, McpManager, McpToolInfo
from agent.runtime.orchestrator import Orchestrator
from agent.types import LlmRequestMeta

# ---------- config tests ----------


def test_mcp_config_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.mcp.enabled is True
    assert cfg.mcp.servers == {}
    assert cfg.mcp.tool_call_timeout_seconds == 60


def test_mcp_server_config_parsing() -> None:
    cfg = AgentConfig.model_validate(
        {
            "mcp": {
                "servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                        "env": {"FOO": "bar"},
                        "timeout_seconds": 15,
                    }
                },
                "tool_call_timeout_seconds": 30,
            }
        }
    )
    assert "filesystem" in cfg.mcp.servers
    fs = cfg.mcp.servers["filesystem"]
    assert fs.command == "npx"
    assert fs.args[0] == "-y"
    assert fs.env == {"FOO": "bar"}
    assert fs.timeout_seconds == 15
    assert cfg.mcp.tool_call_timeout_seconds == 30


# ---------- schema tests ----------


def test_tool_schema_includes_mcp_call() -> None:
    schema = build_agent_decision_tool_schema()
    items = schema["input_schema"]["properties"]["planned_actions"]["items"]
    action_enum = items["properties"]["type"]["enum"]
    assert "mcp_call" in action_enum


# ---------- decoder tests ----------


def test_mcp_call_decoded_correctly() -> None:
    raw = {
        "reasoning_summary": "use mcp",
        "planned_actions": [
            {
                "type": "mcp_call",
                "params": {"tool_name": "read_file", "arguments": {"path": "/tmp/x"}},
            }
        ],
    }
    decision = decode_model_decision(raw)
    assert decision.planned_actions[0].type == "mcp_call"
    assert decision.planned_actions[0].params["tool_name"] == "read_file"


def test_mcp_aliases_resolve_to_mcp_call() -> None:
    for alias in ("mcp_tool", "mcp_invoke", "call_mcp", "use_mcp_tool", "mcp"):
        raw = {
            "reasoning_summary": "alias test",
            "planned_actions": [
                {"type": alias, "params": {"tool_name": "my_tool", "arguments": {}}},
            ],
        }
        decision = decode_model_decision(raw)
        assert decision.planned_actions[0].type == "mcp_call", f"alias {alias} failed"


def test_mcp_call_missing_tool_name_demoted() -> None:
    raw = {
        "reasoning_summary": "missing name",
        "planned_actions": [
            {"type": "mcp_call", "params": {"arguments": {"x": 1}}},
        ],
    }
    decision = decode_model_decision(raw)
    assert decision.planned_actions[0].type == "ask_user"
    assert "mcp_call missing tool_name" in decision.planned_actions[0].params.get("message", "")


# ---------- prompt builder tests ----------


def test_prompt_includes_mcp_tools_section() -> None:
    mcp_tools = [
        {"name": "read_file", "description": "Read a file", "server": "fs", "input_schema": {}},
    ]
    result = build_prompt(
        task="test",
        candidates=[],
        all_skill_frontmatter=[],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
        mcp_tools=mcp_tools,
    )
    assert "MCP_TOOLS" in result.prompt
    assert "read_file" in result.prompt


def test_prompt_omits_mcp_tools_section_when_none() -> None:
    result = build_prompt(
        task="test",
        candidates=[],
        all_skill_frontmatter=[],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
    )
    # The MCP_TOOLS section (with tool data) should not appear
    assert "MCP_TOOLS:\n[" not in result.prompt


def test_prompt_mentions_mcp_call_in_rules() -> None:
    result = build_prompt(
        task="test",
        candidates=[],
        all_skill_frontmatter=[],
        disclosed_snippets={},
        step_results=[],
        max_context_tokens=32000,
        response_headroom_tokens=2000,
    )
    assert "mcp_call" in result.prompt


# ---------- McpManager unit tests ----------


def test_mcp_manager_call_tool_unknown_name() -> None:
    mgr = McpManager()
    result = mgr.call_tool("nonexistent", {})
    assert result.is_error is True
    assert "Unknown MCP tool" in result.raw_text


# ---------- helper for demo skill ----------


def _create_demo_skill(skills_dir: Path) -> None:
    skill_dir = skills_dir / "demo"
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    skill_md = "\n".join(
        [
            "---",
            "name: demo",
            "description: demo skill",
            "version: 0.1.0",
            "tags: [demo]",
            "allowed_tools: [run_command]",
            "---",
            "",
            "# Purpose",
            "Do demo",
            "",
        ]
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _make_llm_meta(model: str, attempt: int) -> LlmRequestMeta:
    return LlmRequestMeta(
        provider="anthropic", model=model, attempt=attempt,
        latency_ms=5, input_tokens=10, output_tokens=8,
    )


# ---------- orchestrator integration tests ----------


def test_orchestrator_executes_mcp_call(tmp_path: Path, monkeypatch: Any) -> None:
    """LLM returns mcp_call, orchestrator invokes MCP, result feeds back."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls: dict[str, int] = {"count": 0}

    def _mock_complete_structured(
        self: object, provider: str, prompt: str, model: str,
        max_tokens: int, attempt: int, **kwargs: object,
    ) -> LlmResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return LlmResult(
                data={
                    "selected_skill": None,
                    "reasoning_summary": "use mcp tool",
                    "required_disclosure_paths": [],
                    "planned_actions": [
                        {
                            "type": "mcp_call",
                            "params": {
                                "tool_name": "read_file",
                                "arguments": {"path": "/tmp/test.txt"},
                            },
                        },
                    ],
                },
                meta=_make_llm_meta(model, attempt),
            )
        # Second call: finish
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "done",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {"type": "finish", "params": {"summary": "task done"}}
                ],
            },
            meta=_make_llm_meta(model, attempt),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    # Mock McpManager
    monkeypatch.setattr(
        McpManager, "connect_all",
        lambda self, servers: [
            McpToolInfo(
                server_name="test", name="read_file",
                description="Read a file", input_schema={},
            ),
        ],
    )
    monkeypatch.setattr(
        McpManager, "call_tool",
        lambda self, tool_name, arguments, timeout_seconds=60: McpCallResult(
            server_name="test", tool_name="read_file",
            content=[{"type": "text", "text": "file contents here"}],
            is_error=False, raw_text="file contents here",
        ),
    )
    monkeypatch.setattr(McpManager, "close_all", lambda self: None)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.mcp.servers = {"test": McpServerConfig(command="echo", args=["test"])}

    result = Orchestrator(cfg).run(task="read a file", skills_dir=skills_dir)
    assert result.status == "success"
    assert calls["count"] >= 2

    # Verify mcp events were emitted
    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events_text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "mcp_servers_connected" in events_text
    assert "mcp_tool_call_started" in events_text
    assert "mcp_tool_call_completed" in events_text
    assert "mcp_servers_disconnected" in events_text


def test_orchestrator_graceful_mcp_connection_failure(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """MCP connection failure should not prevent the run from succeeding."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self: object, provider: str, prompt: str, model: str,
        max_tokens: int, attempt: int, **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "done",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {"type": "finish", "params": {"summary": "done"}}
                ],
            },
            meta=_make_llm_meta(model, attempt),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    # Mock McpManager to fail on connect
    monkeypatch.setattr(
        McpManager, "connect_all",
        lambda self, servers: (_ for _ in ()).throw(RuntimeError("connection failed")),
    )
    monkeypatch.setattr(McpManager, "close_all", lambda self: None)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.mcp.servers = {"test": McpServerConfig(command="bad", args=[])}

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir)
    assert result.status == "success"

    # Verify failure event was emitted
    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events_text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "mcp_connection_failed" in events_text


def test_orchestrator_mcp_call_failure_stops_run(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """MCP tool call failure should stop execution."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self: object, provider: str, prompt: str, model: str,
        max_tokens: int, attempt: int, **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "use mcp",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {
                        "type": "mcp_call",
                        "params": {
                            "tool_name": "bad_tool",
                            "arguments": {},
                        },
                    },
                ],
            },
            meta=_make_llm_meta(model, attempt),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    monkeypatch.setattr(
        McpManager, "connect_all",
        lambda self, servers: [
            McpToolInfo(
                server_name="test", name="bad_tool",
                description="Fails", input_schema={},
            ),
        ],
    )
    monkeypatch.setattr(
        McpManager, "call_tool",
        lambda self, tool_name, arguments, timeout_seconds=60: McpCallResult(
            server_name="test", tool_name="bad_tool",
            content=[], is_error=True, raw_text="tool error",
        ),
    )
    monkeypatch.setattr(McpManager, "close_all", lambda self: None)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    cfg.mcp.servers = {"test": McpServerConfig(command="echo", args=[])}

    result = Orchestrator(cfg).run(task="test", skills_dir=skills_dir)
    assert result.status == "failed"

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events_text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "mcp_tool_call_completed" in events_text


def test_orchestrator_no_mcp_without_config(tmp_path: Path, monkeypatch: Any) -> None:
    """Without MCP servers configured, no MCP events should be emitted."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _mock_complete_structured(
        self: object, provider: str, prompt: str, model: str,
        max_tokens: int, attempt: int, **kwargs: object,
    ) -> LlmResult:
        return LlmResult(
            data={
                "selected_skill": None,
                "reasoning_summary": "done",
                "required_disclosure_paths": [],
                "planned_actions": [
                    {"type": "finish", "params": {"summary": "done"}}
                ],
            },
            meta=_make_llm_meta(model, attempt),
        )

    monkeypatch.setattr(ProviderRouter, "complete_structured", _mock_complete_structured)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.model.provider = "anthropic"
    # No MCP servers configured (default)

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir)
    assert result.status == "success"

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    events_text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "mcp_servers_connected" not in events_text


def test_mcp_tool_catalog_appears_in_dry_run_prompt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """Dry run should include MCP_TOOLS in the prompt when servers are configured."""
    skills_dir = tmp_path / "skills"
    _create_demo_skill(skills_dir)

    monkeypatch.setattr(
        McpManager, "connect_all",
        lambda self, servers: [
            McpToolInfo(
                server_name="fs", name="list_dir",
                description="List directory", input_schema={"type": "object"},
            ),
        ],
    )
    monkeypatch.setattr(McpManager, "close_all", lambda self: None)

    cfg = AgentConfig()
    cfg.logging.jsonl_dir = str(tmp_path / "runs")
    cfg.mcp.servers = {"fs": McpServerConfig(command="echo", args=[])}

    result = Orchestrator(cfg).run(task="list files", skills_dir=skills_dir, dry_run=True)
    assert result.status == "success"

    run_dir = Path(cfg.logging.jsonl_dir) / result.run_id
    prompt_text = (run_dir / "dry_run_prompt.txt").read_text(encoding="utf-8")
    assert "MCP_TOOLS" in prompt_text
    assert "list_dir" in prompt_text
