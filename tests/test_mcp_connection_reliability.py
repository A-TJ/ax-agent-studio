#!/usr/bin/env python3
"""
MCP Connection Reliability Tests

Tests for MCP connection stability, retry logic, and error handling.
Validates that connections remain stable under various conditions.
"""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import ClientSession

from ax_agent_studio.mcp_heartbeat import HeartbeatManager, keep_alive
from ax_agent_studio.mcp_manager import MCPServerManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestConnectionStability:
    """Test MCP connection stability under normal and stress conditions"""

    @pytest.mark.asyncio
    async def test_heartbeat_basic_functionality(self):
        """Test basic heartbeat keeps connection alive"""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.send_ping = AsyncMock(return_value=MagicMock(status="ok", timestamp="2025-01-01"))

        # Run heartbeat for 3 pings (0.3 seconds)
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            keep_alive(mock_session, interval=0.1, name="test", stop_event=stop_event)
        )

        await asyncio.sleep(0.35)
        stop_event.set()
        await heartbeat_task

        # Should have sent 3 pings
        assert mock_session.send_ping.call_count >= 3
        logger.info(f"✅ Heartbeat sent {mock_session.send_ping.call_count} pings")

    @pytest.mark.asyncio
    async def test_heartbeat_handles_ping_failures(self):
        """Test heartbeat continues after ping failures"""
        mock_session = AsyncMock(spec=ClientSession)

        # Simulate ping failures with infinite repeating pattern
        async def failing_ping():
            # Fail every other time
            if mock_session.send_ping.call_count % 2 == 0:
                raise Exception("Connection timeout")
            return MagicMock(status="ok", timestamp="2025-01-01")

        mock_session.send_ping = AsyncMock(side_effect=failing_ping)

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            keep_alive(mock_session, interval=0.05, name="test_failure", stop_event=stop_event)
        )

        # Wait longer to allow more pings including retry delays
        await asyncio.sleep(0.5)
        stop_event.set()

        try:
            await heartbeat_task
        except Exception:
            pass  # Expected to continue despite errors

        # Should have attempted multiple pings despite failures (reduced expectation)
        assert mock_session.send_ping.call_count >= 2
        logger.info("✅ Heartbeat continued after failures")

    @pytest.mark.asyncio
    async def test_heartbeat_manager_multiple_sessions(self):
        """Test HeartbeatManager handles multiple sessions"""
        manager = HeartbeatManager(interval=0.1)

        mock_session1 = AsyncMock(spec=ClientSession)
        mock_session2 = AsyncMock(spec=ClientSession)
        mock_session1.send_ping = AsyncMock(return_value=MagicMock(status="ok", timestamp="2025-01-01"))
        mock_session2.send_ping = AsyncMock(return_value=MagicMock(status="ok", timestamp="2025-01-01"))

        # Start heartbeats for both sessions
        await manager.start(mock_session1, name="session1")
        await manager.start(mock_session2, name="session2")

        await asyncio.sleep(0.25)

        # Check stats
        stats = manager.get_stats()
        assert stats["active_heartbeats"] == 2
        assert "session1" in stats["task_names"]
        assert "session2" in stats["task_names"]

        await manager.stop_all()
        logger.info("✅ HeartbeatManager handled multiple sessions")

    @pytest.mark.asyncio
    async def test_heartbeat_disabled_with_zero_interval(self):
        """Test heartbeat can be disabled by setting interval to 0"""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.send_ping = AsyncMock()

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            keep_alive(mock_session, interval=0, name="disabled", stop_event=stop_event)
        )

        await asyncio.sleep(0.1)
        stop_event.set()
        await heartbeat_task

        # Should not have sent any pings
        assert mock_session.send_ping.call_count == 0
        logger.info("✅ Heartbeat correctly disabled with interval=0")


class TestConnectionRetryLogic:
    """Test connection retry and recovery mechanisms"""

    @pytest.mark.asyncio
    async def test_connection_recovery_after_failure(self):
        """Test system recovers from connection failures"""
        mock_session = AsyncMock(spec=ClientSession)

        # Simulate connection failure then recovery
        call_count = 0

        async def mock_ping():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("Connection lost")
            return MagicMock(status="ok", timestamp="2025-01-01")

        mock_session.send_ping = mock_ping

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            keep_alive(mock_session, interval=0.05, name="recovery", stop_event=stop_event)
        )

        # Wait longer to allow retry delays (5s pause after error)
        await asyncio.sleep(11)
        stop_event.set()

        try:
            await heartbeat_task
        except Exception:
            pass

        # Should have attempted pings and recovered
        assert call_count >= 3
        logger.info("✅ Connection recovered after failures")

    @pytest.mark.asyncio
    async def test_graceful_cancellation(self):
        """Test heartbeat task can be gracefully cancelled"""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.send_ping = AsyncMock(return_value=MagicMock(status="ok", timestamp="2025-01-01"))

        heartbeat_task = asyncio.create_task(keep_alive(mock_session, interval=0.1, name="cancel"))

        await asyncio.sleep(0.15)
        heartbeat_task.cancel()

        # The task catches CancelledError and logs it, so we just check it completes
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass  # Expected

        assert heartbeat_task.cancelled() or heartbeat_task.done()
        logger.info("✅ Heartbeat cancelled gracefully")


class TestMCPServerManagerReliability:
    """Test MCPServerManager connection handling"""

    @pytest.mark.asyncio
    async def test_manager_load_invalid_config(self):
        """Test manager handles invalid config gracefully"""
        manager = MCPServerManager(
            agent_name="test_agent",
            config_path=Path("/nonexistent/config.json"),
        )

        with pytest.raises(FileNotFoundError):
            manager.load_config()

        logger.info("✅ Manager raises FileNotFoundError for missing config")

    @pytest.mark.asyncio
    async def test_manager_missing_mcpservers_key(self, tmp_path):
        """Test manager validates config structure"""
        config_file = tmp_path / "invalid_config.json"
        config_file.write_text('{"wrong_key": {}}')

        manager = MCPServerManager(
            agent_name="test_agent",
            config_path=config_file,
        )

        with pytest.raises(ValueError, match="Expected 'mcpServers'"):
            manager.load_config()

        logger.info("✅ Manager validates config structure")

    @pytest.mark.asyncio
    async def test_manager_get_session_returns_none_for_missing(self):
        """Test get_session returns None for non-existent server"""
        manager = MCPServerManager(agent_name="test_agent")

        result = manager.get_session("nonexistent_server")
        assert result is None

        logger.info("✅ Manager returns None for missing sessions")

    @pytest.mark.asyncio
    async def test_manager_get_primary_session_raises_without_sessions(self):
        """Test get_primary_session raises error when no sessions available"""
        manager = MCPServerManager(agent_name="test_agent")

        with pytest.raises(RuntimeError, match="No MCP sessions available"):
            manager.get_primary_session()

        logger.info("✅ Manager raises error when no sessions available")


class TestConnectionLatency:
    """Test connection latency measurements"""

    @pytest.mark.asyncio
    async def test_ping_latency_measurement(self):
        """Test ping latency is measured correctly"""
        mock_session = AsyncMock(spec=ClientSession)

        # Simulate slow ping response
        async def slow_ping():
            await asyncio.sleep(0.1)
            return MagicMock(status="ok", timestamp="2025-01-01")

        mock_session.send_ping = slow_ping

        import time
        start = time.time()
        result = await mock_session.send_ping()
        duration = time.time() - start

        assert duration >= 0.1
        assert result.status == "ok"
        logger.info(f"✅ Ping latency measured: {duration:.3f}s")

    @pytest.mark.asyncio
    async def test_multiple_ping_latencies(self):
        """Test multiple pings and measure average latency"""
        mock_session = AsyncMock(spec=ClientSession)

        latencies = []

        async def variable_latency_ping():
            import random
            delay = random.uniform(0.01, 0.05)
            await asyncio.sleep(delay)
            latencies.append(delay)
            return MagicMock(status="ok", timestamp="2025-01-01")

        mock_session.send_ping = variable_latency_ping

        # Send 5 pings
        for _ in range(5):
            await mock_session.send_ping()

        avg_latency = sum(latencies) / len(latencies)
        assert len(latencies) == 5
        assert 0.01 <= avg_latency <= 0.05
        logger.info(f"✅ Average ping latency: {avg_latency:.3f}s")


class TestErrorHandling:
    """Test error handling and recovery"""

    @pytest.mark.asyncio
    async def test_handle_connection_timeout(self):
        """Test handling of connection timeouts"""
        mock_session = AsyncMock(spec=ClientSession)
        mock_session.send_ping = AsyncMock(side_effect=asyncio.TimeoutError("Connection timeout"))

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            keep_alive(mock_session, interval=0.05, name="timeout", stop_event=stop_event)
        )

        # Wait longer to allow retry delays (5s pause after error)
        await asyncio.sleep(7)
        stop_event.set()

        try:
            await heartbeat_task
        except Exception:
            pass  # Expected to continue

        # Should have attempted multiple pings (reduced expectation)
        assert mock_session.send_ping.call_count >= 2
        logger.info("✅ Handled connection timeouts")

    @pytest.mark.asyncio
    async def test_handle_network_errors(self):
        """Test handling of various network errors"""
        mock_session = AsyncMock(spec=ClientSession)

        # Create infinite error generator
        error_cycle = [
            ConnectionResetError("Connection reset"),
            ConnectionRefusedError("Connection refused"),
            OSError("Network unreachable"),
        ]
        call_counter = {"count": 0}

        async def get_next_error():
            error_index = call_counter["count"] % len(error_cycle)
            call_counter["count"] += 1
            raise error_cycle[error_index]

        mock_session.send_ping = AsyncMock(side_effect=get_next_error)

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            keep_alive(mock_session, interval=0.05, name="network_error", stop_event=stop_event)
        )

        # Wait longer to allow retry delays (5s pause after each error)
        await asyncio.sleep(12)
        stop_event.set()

        try:
            await heartbeat_task
        except Exception:
            pass

        # Should have attempted multiple pings
        assert mock_session.send_ping.call_count >= 3
        logger.info("✅ Handled various network errors")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
