#!/usr/bin/env python3
"""
MCP Multi-Server Manager
Manages connections to multiple MCP servers and provides unified tool access.

Enhanced with liveness probes, automatic reconnection, and retry policies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ax_agent_studio.mcp_heartbeat import HeartbeatManager
from ax_agent_studio.monitoring.liveness import LivenessRegistry
from ax_agent_studio.monitoring.metrics import log_metric

logger = logging.getLogger(__name__)


@dataclass
class ServerConnectionState:
    name: str
    config: dict[str, Any]
    session: ClientSession | None = None
    heartbeat_task: asyncio.Task | None = None
    reconnect_attempts: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPServerManager:
    """Manages multiple MCP server connections with automatic heartbeat"""

    def __init__(
        self,
        agent_name: str,
        base_dir: Path | None = None,
        config_path: Path | None = None,
        heartbeat_interval: int = 240,
        operation_timeout: int = 30,
        max_operation_retries: int = 3,
        reconnect_backoff: float = 2.0,
    ):
        """
        Initialize MCP Server Manager.

        Args:
            agent_name: Name of the agent
            base_dir: Base directory for configs (default: project root)
            config_path: Path to agent config JSON (default: configs/agents/{agent_name}.json)
            heartbeat_interval: Seconds between heartbeat pings (default: 240 = 4 min, 0 = disabled)
        """
        self.agent_name = agent_name
        self.base_dir = base_dir or Path(__file__).parent.parent.parent
        if config_path is not None:
            self.config_path = Path(config_path)
        else:
            self.config_path = self.base_dir / "configs" / "agents" / f"{agent_name}.json"

        # Multi-server state
        self.sessions: dict[str, ClientSession] = {}
        self.server_states: dict[str, ServerConnectionState] = {}
        self.exit_stack: AsyncExitStack | None = None
        self.config: dict[str, Any] | None = None

        # Policy configuration
        self.operation_timeout = operation_timeout
        self.max_operation_retries = max_operation_retries
        self.reconnect_backoff = reconnect_backoff

        # Health tracking
        self.heartbeat_manager = HeartbeatManager(interval=heartbeat_interval)
        self.liveness = LivenessRegistry(
            domain="mcp",
            on_state_change=lambda name, payload: log_metric("mcp_liveness", **payload),
        )
        logger.info(
            "MCPServerManager initialized (heartbeat=%ss timeout=%ss retries=%s)",
            heartbeat_interval,
            operation_timeout,
            max_operation_retries,
        )

    async def __aenter__(self):
        """Async context manager entry - connect to all servers"""
        await self.connect_all()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup all connections"""
        await self.disconnect_all()

    def load_config(self) -> dict:
        """Load agent configuration from the specified config_path"""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Agent config not found: {self.config_path}\n"
                f"The config file does not exist at the specified path."
            )

        with open(self.config_path) as f:
            self.config = json.load(f)

        if "mcpServers" not in self.config:
            raise ValueError(
                f"Invalid config format. Expected 'mcpServers' key in {self.config_path}"
            )

        return self.config

    def _build_server_params(self, server_name: str, server_config: dict) -> StdioServerParameters:
        """Build StdioServerParameters from config"""
        command = server_config.get("command", "npx")
        args = server_config.get("args", [])
        env = server_config.get("env")

        return StdioServerParameters(command=command, args=args, env=env)

    async def _maybe_start_heartbeat(
        self,
        server_name: str,
        session: ClientSession,
        server_config: dict[str, Any],
    ) -> None:
        """Start heartbeat loop for remote servers."""
        requires_heartbeat = server_name.startswith("ax-") or "mcp-remote" in str(
            server_config.get("args", [])
        )
        if not requires_heartbeat:
            logger.debug("Skipping heartbeat for %s (local server)", server_name)
            return

        await self.heartbeat_manager.start(session, name=f"{self.agent_name}/{server_name}")
        logger.info("Started heartbeat for remote server: %s", server_name)

    async def _connect_single_server(self, state: ServerConnectionState) -> bool:
        """Create a single server session and start monitoring tasks."""
        server_name = state.name
        server_config = state.config

        try:
            server_params = self._build_server_params(server_name, server_config)
            read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), timeout=self.operation_timeout)

            self.sessions[server_name] = session
            state.session = session
            state.last_error = None
            state.reconnect_attempts = 0

            await self._maybe_start_heartbeat(server_name, session, server_config)
            await self.liveness.beat(server_name)

            tools_response = await asyncio.wait_for(session.list_tools(), timeout=self.operation_timeout)
            tool_count = len(tools_response.tools) if hasattr(tools_response, "tools") else 0
            state.metadata["tool_count"] = tool_count
            log_metric("mcp_connected", server=server_name, tool_count=tool_count)
            return True
        except Exception as exc:
            state.last_error = str(exc)
            log_metric("mcp_connection_failed", server=server_name, error=state.last_error)
            logger.error("Failed to connect to %s: %s", server_name, exc)
            return False

    async def connect_all(self):
        """Connect to all MCP servers defined in config."""
        if self.config is None:
            self.load_config()

        self.exit_stack = AsyncExitStack()
        await self.exit_stack.__aenter__()

        mcp_servers = self.config.get("mcpServers", {})

        print(f"\n Connecting to {len(mcp_servers)} MCP server(s)...")

        for server_name, server_config in mcp_servers.items():
            state = ServerConnectionState(
                name=server_name,
                config=server_config,
            )
            self.server_states[server_name] = state
            connected = await self._connect_single_server(state)
            if connected:
                print(f"   • {server_name} (connected)")
            else:
                print(f"   • {server_name} (failed, will retry on demand)")

        success_count = sum(1 for state in self.server_states.values() if state.session)
        print(f" Connected to {success_count}/{len(mcp_servers)} servers\n")

    async def disconnect_all(self):
        """Disconnect from all MCP servers and stop heartbeats"""
        # Stop all heartbeats
        await self.heartbeat_manager.stop_all()

        # Disconnect sessions
        if self.exit_stack:
            await self.exit_stack.__aexit__(None, None, None)
            self.sessions.clear()
            self.server_states.clear()

    def get_session(self, server_name: str) -> ClientSession | None:
        """Get a specific MCP session by server name"""
        return self.sessions.get(server_name)

    def get_primary_session(self) -> ClientSession:
        """Get the primary session (ax-gcp for messaging)"""
        # Try ax-gcp first
        if "ax-gcp" in self.sessions:
            return self.sessions["ax-gcp"]

        # Fallback to first available session
        if self.sessions:
            return next(iter(self.sessions.values()))

        raise RuntimeError("No MCP sessions available")

    async def _ensure_session(self, server_name: str) -> ClientSession:
        session = self.sessions.get(server_name)
        if session:
            return session

        state = self.server_states.get(server_name)
        if not state:
            raise ValueError(f"Unknown server '{server_name}'")

        reconnected = await self._attempt_reconnect(state)
        if not reconnected or not state.session:
            raise RuntimeError(f"Unable to reconnect to server '{server_name}'")
        return state.session

    async def _attempt_reconnect(self, state: ServerConnectionState) -> bool:
        """Attempt to reconnect to a server with exponential backoff."""
        max_attempts = self.max_operation_retries
        for attempt in range(1, max_attempts + 1):
            backoff = self.reconnect_backoff * (2 ** (attempt - 1))
            logger.warning(
                "Reconnecting to %s (attempt %s/%s, backoff %.1fs)",
                state.name,
                attempt,
                max_attempts,
                backoff,
            )
            await asyncio.sleep(backoff)
            state.reconnect_attempts = attempt
            success = await self._connect_single_server(state)
            if success:
                log_metric("mcp_reconnected", server=state.name, attempt=attempt)
                return True

        log_metric("mcp_reconnect_failed", server=state.name, attempts=max_attempts)
        return False

    async def list_all_tools(self) -> dict[str, list[Any]]:
        """List all available tools from all servers."""
        results: dict[str, list[Any]] = {}

        async def _list(session: ClientSession):
            response = await session.list_tools()
            return response.tools if hasattr(response, "tools") else []

        for server_name in self.server_states:
            try:
                tools = await self._execute_with_retry(server_name, _list, "list_tools")
                results[server_name] = tools
            except Exception as exc:
                logger.error("Failed to list tools for %s: %s", server_name, exc)
                results[server_name] = []
        return results

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        """Call a tool on a specific server with timeout/retry logic."""

        async def _call(session: ClientSession):
            return await session.call_tool(tool_name, arguments)

        return await self._execute_with_retry(server_name, _call, f"call_tool:{tool_name}")

    async def _execute_with_retry(
        self,
        server_name: str,
        operation: Callable[[ClientSession], Awaitable[Any]],
        opname: str,
    ) -> Any:
        last_error: Exception | None = None

        for attempt in range(1, self.max_operation_retries + 1):
            try:
                session = await self._ensure_session(server_name)
                result = await asyncio.wait_for(operation(session), timeout=self.operation_timeout)
                await self.liveness.beat(server_name)
                if attempt > 1:
                    log_metric("mcp_retry_success", server=server_name, op=opname, attempt=attempt)
                return result
            except asyncio.TimeoutError as exc:
                last_error = exc
                log_metric(
                    "mcp_operation_timeout",
                    server=server_name,
                    op=opname,
                    attempt=attempt,
                )
                await self.liveness.miss(server_name)
            except Exception as exc:
                last_error = exc
                log_metric(
                    "mcp_operation_failure",
                    server=server_name,
                    op=opname,
                    attempt=attempt,
                    error=str(exc),
                )
                await self.liveness.miss(server_name)
                # Force reconnect on next attempt
                with suppress(KeyError):
                    session = self.sessions.pop(server_name)
                    if session:
                        await session.close()
            await asyncio.sleep(self.reconnect_backoff * attempt)

        await self.liveness.mark_dead(server_name)
        raise RuntimeError(
            f"Operation '{opname}' failed for server '{server_name}' after "
            f"{self.max_operation_retries} attempts"
        ) from last_error

    def print_summary(self):
        """Print a summary of connected servers and available tools"""
        print("\n MCP Servers Summary:")
        print(f"   Agent: {self.agent_name}")
        print(f"   Config: {self.config_path}")
        print(f"   Servers: {len(self.sessions)}")

        for server_name, session in self.sessions.items():
            print(f"      • {server_name}")

    async def create_langchain_tools(self):
        """
        Create LangChain-compatible tools from all MCP servers using official adapter
        Returns list of async LangChain tools
        """
        from langchain_mcp_adapters.tools import load_mcp_tools

        all_tools = []

        for server_name, session in self.sessions.items():
            logger.info(f"Loading tools from {server_name}...")

            # Use official MCP adapter to load tools
            server_tools = await load_mcp_tools(session)

            # Prefix tool names with server name for clarity
            for tool in server_tools:
                # Store original name if not already prefixed
                if not tool.name.startswith(f"{server_name}_"):
                    tool.name = f"{server_name}_{tool.name}"
                all_tools.append(tool)
                logger.info(f"Created tool: {tool.name}")

        return all_tools
