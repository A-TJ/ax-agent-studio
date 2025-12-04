import asyncio

import pytest

from ax_agent_studio.mcp_manager import MCPServerManager, ServerConnectionState


class FlakySession:
    def __init__(self, fail_times: int = 1):
        self.fail_times = fail_times
        self.calls = 0

    async def call_tool(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient failure")
        return "success"


@pytest.mark.asyncio
async def test_execute_with_retry_recovers(monkeypatch):
    manager = MCPServerManager(
        agent_name="test_agent",
        heartbeat_interval=0,
        operation_timeout=1,
        max_operation_retries=3,
        reconnect_backoff=0.01,
    )
    state = ServerConnectionState(name="dummy", config={})
    manager.server_states["dummy"] = state
    session = FlakySession(fail_times=1)

    async def fake_ensure(name: str):
        assert name == "dummy"
        return session

    monkeypatch.setattr(manager, "_ensure_session", fake_ensure)
    result = await manager._execute_with_retry("dummy", lambda s: s.call_tool(), "unit-test")
    assert result == "success"
    assert session.calls == 2

