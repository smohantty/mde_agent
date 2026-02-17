"""Synchronous wrapper around async MCP client sessions."""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from agent.config import McpServerConfig


@dataclass
class McpToolInfo:
    """Discovered MCP tool metadata."""

    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class McpCallResult:
    """Result of invoking an MCP tool."""

    server_name: str
    tool_name: str
    content: list[dict[str, Any]]
    is_error: bool
    raw_text: str


@dataclass
class _ServerSession:
    """Holds a live async session for one MCP server."""

    server_name: str
    session: Any = field(default=None, repr=False)


class McpManager:
    """Manages connections to multiple MCP servers.

    All public methods are synchronous.  Async MCP SDK calls run on a
    background event loop thread.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _ServerSession] = {}
        self._tools: list[McpToolInfo] = []
        self._tool_server_map: dict[str, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._exit_stack: AsyncExitStack | None = None

    @property
    def tools(self) -> list[McpToolInfo]:
        return list(self._tools)

    # ------------------------------------------------------------------
    # Public sync API
    # ------------------------------------------------------------------

    def connect_all(
        self, servers: dict[str, McpServerConfig]
    ) -> list[McpToolInfo]:
        """Connect to all configured MCP servers and discover tools."""
        self._start_loop()
        return self._run(self._async_connect_all(servers))

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: int = 60,
    ) -> McpCallResult:
        """Invoke a tool on its MCP server."""
        server_name = self._tool_server_map.get(tool_name)
        if server_name is None:
            return McpCallResult(
                server_name="unknown",
                tool_name=tool_name,
                content=[],
                is_error=True,
                raw_text=f"Unknown MCP tool: {tool_name}",
            )
        return self._run(
            self._async_call_tool(
                server_name, tool_name, arguments, timeout_seconds
            )
        )

    def close_all(self) -> None:
        """Close all MCP server connections and stop the background loop."""
        if self._loop is not None and self._loop.is_running():
            with contextlib.suppress(Exception):
                self._run(self._async_close_all())
        self._stop_loop()
        self._sessions.clear()
        self._tools.clear()
        self._tool_server_map.clear()

    # ------------------------------------------------------------------
    # Background event loop management
    # ------------------------------------------------------------------

    def _start_loop(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._thread.start()

    def _stop_loop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    def _run(self, coro: Any) -> Any:
        """Schedule *coro* on the background loop and wait for the result."""
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=120)

    # ------------------------------------------------------------------
    # Async internals
    # ------------------------------------------------------------------

    async def _async_connect_all(
        self, servers: dict[str, McpServerConfig]
    ) -> list[McpToolInfo]:
        try:
            from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
            from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "mcp package is not installed. "
                "Install it with: pip install 'autonomous-skill-agent[mcp]'"
            ) from exc

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        all_tools: list[McpToolInfo] = []
        for name, config in servers.items():
            env = {**os.environ, **config.env}
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=env,
            )
            transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = transport
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                schema: Any = {}
                if hasattr(tool, "inputSchema"):
                    schema = tool.inputSchema  # type: ignore[union-attr]
                info = McpToolInfo(
                    server_name=name,
                    name=tool.name,
                    description=getattr(tool, "description", "") or "",
                    input_schema=schema if isinstance(schema, dict) else {},
                )
                all_tools.append(info)
                self._tool_server_map[tool.name] = name

            self._sessions[name] = _ServerSession(
                server_name=name, session=session
            )

        self._tools = all_tools
        return all_tools

    async def _async_call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: int,
    ) -> McpCallResult:
        session_data = self._sessions.get(server_name)
        if session_data is None or session_data.session is None:
            return McpCallResult(
                server_name=server_name,
                tool_name=tool_name,
                content=[],
                is_error=True,
                raw_text=f"No active session for server: {server_name}",
            )

        result = await asyncio.wait_for(
            session_data.session.call_tool(tool_name, arguments=arguments),
            timeout=timeout_seconds,
        )

        text_parts: list[str] = []
        content_blocks: list[dict[str, Any]] = []
        for block in result.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
                content_blocks.append({"type": "text", "text": block.text})
            else:
                content_blocks.append(
                    {"type": type(block).__name__}
                )

        return McpCallResult(
            server_name=server_name,
            tool_name=tool_name,
            content=content_blocks,
            is_error=getattr(result, "isError", False),
            raw_text="\n".join(text_parts),
        )

    async def _async_close_all(self) -> None:
        if self._exit_stack is not None:
            with contextlib.suppress(Exception):
                await self._exit_stack.aclose()
            self._exit_stack = None
