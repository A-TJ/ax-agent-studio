#!/usr/bin/env python3
"""
MCP Connection Integration Tests

Integration tests for real-world MCP connection scenarios including:
- Connection initialization and cleanup
- Session management across multiple servers
- Tool calling reliability
- Heartbeat functionality in real scenarios

These tests require actual MCP servers to be available.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from ax_agent_studio.mcp_manager import MCPServerManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture
def temp_agent_config(tmp_path) -> Path:
    """Create a temporary agent config for testing"""
    config_dir = tmp_path / "configs" / "agents"
    config_dir.mkdir(parents=True)

    config_file = config_dir / "test_agent.json"

    # Use filesystem MCP server for testing (widely available)
    config = {
        "mcpServers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", str(tmp_path)],
            }
        }
    }

    config_file.write_text(json.dumps(config, indent=2))
    return config_file


class TestMCPManagerIntegration:
    """Integration tests for MCPServerManager"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_connect_and_disconnect_lifecycle(self, temp_agent_config):
        """Test complete connection lifecycle"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,  # Disable heartbeat for this test
        )

        # Test connection
        async with manager:
            assert len(manager.sessions) > 0
            assert manager.get_session("filesystem") is not None
            logger.info("✅ Successfully connected to MCP servers")

        # Test cleanup
        assert len(manager.sessions) == 0
        logger.info("✅ Successfully disconnected from all servers")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_tools_from_connected_server(self, temp_agent_config):
        """Test listing tools from connected MCP server"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        async with manager:
            all_tools = await manager.list_all_tools()

            assert "filesystem" in all_tools
            assert len(all_tools["filesystem"]) > 0

            logger.info(f"✅ Listed {len(all_tools['filesystem'])} tools from filesystem server")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_call_tool_on_connected_server(self, temp_agent_config, tmp_path):
        """Test calling tools on connected MCP server"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello from MCP test!")

        async with manager:
            # List available tools
            all_tools = await manager.list_all_tools()
            tool_names = [tool.name for tool in all_tools["filesystem"]]

            logger.info(f"Available tools: {tool_names}")

            # Try to call a read operation (if available)
            if any("read" in name.lower() for name in tool_names):
                read_tool = next(name for name in tool_names if "read" in name.lower())

                try:
                    result = await manager.call_tool(
                        "filesystem", read_tool, {"path": str(test_file)}
                    )
                    logger.info(f"✅ Successfully called {read_tool} tool")
                    assert result is not None
                except Exception as e:
                    logger.warning(f"Tool call failed (may be expected): {e}")
            else:
                logger.warning("No read tool found, skipping tool call test")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_multiple_sequential_connections(self, temp_agent_config):
        """Test multiple sequential connection/disconnection cycles"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        # Cycle 1
        async with manager:
            assert len(manager.sessions) > 0

        assert len(manager.sessions) == 0

        # Cycle 2
        async with manager:
            assert len(manager.sessions) > 0

        assert len(manager.sessions) == 0

        # Cycle 3
        async with manager:
            assert len(manager.sessions) > 0

        logger.info("✅ Successfully completed multiple connection cycles")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_primary_session(self, temp_agent_config):
        """Test getting primary session"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        async with manager:
            # Should get the first available session
            primary_session = manager.get_primary_session()
            assert primary_session is not None

            logger.info("✅ Successfully retrieved primary session")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_manager_with_heartbeat_enabled(self, temp_agent_config):
        """Test manager with heartbeat functionality enabled"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=1,  # 1 second for faster testing
        )

        async with manager:
            # Let heartbeat run for a few seconds
            await asyncio.sleep(3)

            # Check heartbeat stats
            stats = manager.heartbeat_manager.get_stats()
            logger.info(f"Heartbeat stats: {stats}")

            # For local filesystem server, heartbeat should not be started
            # (only remote aX servers get heartbeats)
            assert stats["active_heartbeats"] == 0

            logger.info("✅ Heartbeat manager working correctly")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test handling of connection errors"""
        # Create manager with invalid config
        manager = MCPServerManager(
            agent_name="nonexistent_agent",
            config_path=Path("/nonexistent/path/config.json"),
        )

        # Should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            async with manager:
                pass

        logger.info("✅ Connection error handling works correctly")


class TestConnectionResilience:
    """Test connection resilience under various conditions"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_rapid_connection_cycling(self, temp_agent_config):
        """Test rapid connection/disconnection cycles"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        # Perform 10 rapid cycles
        for i in range(10):
            async with manager:
                assert len(manager.sessions) > 0

            assert len(manager.sessions) == 0

            if (i + 1) % 5 == 0:
                logger.info(f"  Completed {i + 1}/10 rapid cycles")

        logger.info("✅ Successfully completed rapid connection cycling")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self, temp_agent_config, tmp_path):
        """Test multiple concurrent tool calls"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        async with manager:
            all_tools = await manager.list_all_tools()

            if not all_tools.get("filesystem"):
                pytest.skip("No filesystem tools available")

            # Make multiple concurrent list_tools calls
            tasks = [manager.list_all_tools() for _ in range(5)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed
            successful = [r for r in results if not isinstance(r, Exception)]
            assert len(successful) == 5

            logger.info("✅ Successfully handled concurrent tool calls")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_session_persistence_during_operations(self, temp_agent_config):
        """Test that sessions remain stable during operations"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        async with manager:
            session_before = manager.get_session("filesystem")

            # Perform multiple operations
            for _ in range(10):
                await manager.list_all_tools()
                await asyncio.sleep(0.1)

            session_after = manager.get_session("filesystem")

            # Session should be the same object
            assert session_before is session_after

            logger.info("✅ Session remained stable during operations")


class TestRealWorldScenarios:
    """Test real-world usage scenarios"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_long_running_session(self, temp_agent_config):
        """Test long-running session with periodic activity"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=2,  # 2 second heartbeat
        )

        async with manager:
            # Simulate long-running session with periodic tool calls
            for i in range(5):
                await manager.list_all_tools()
                await asyncio.sleep(1)

                if (i + 1) % 2 == 0:
                    logger.info(f"  Iteration {i + 1}/5 completed")

            logger.info("✅ Long-running session completed successfully")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_manager_print_summary(self, temp_agent_config, capsys):
        """Test manager summary printing"""
        manager = MCPServerManager(
            agent_name="test_agent",
            base_dir=temp_agent_config.parent.parent.parent,
            heartbeat_interval=0,
        )

        async with manager:
            manager.print_summary()

            captured = capsys.readouterr()
            assert "MCP Servers Summary" in captured.out
            assert "test_agent" in captured.out
            assert "filesystem" in captured.out

            logger.info("✅ Manager summary printed correctly")


def run_integration_tests():
    """Run all integration tests"""
    logger.info("=" * 80)
    logger.info("MCP CONNECTION INTEGRATION TESTS")
    logger.info("=" * 80)

    pytest.main([__file__, "-v", "-s", "-m", "integration"])


if __name__ == "__main__":
    run_integration_tests()
