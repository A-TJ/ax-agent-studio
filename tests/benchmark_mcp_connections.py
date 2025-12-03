#!/usr/bin/env python3
"""
MCP Connection Reliability Benchmark

Measures connection latency, success rates, and throughput
for MCP connections under various conditions.

Usage:
    python benchmark_mcp_connections.py
    python benchmark_mcp_connections.py --iterations 100 --concurrent 10
"""

import argparse
import asyncio
import logging
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionBenchmark:
    """Benchmark MCP connection reliability and performance"""

    def __init__(self):
        self.results = {
            "ping_latencies": [],
            "connection_attempts": 0,
            "connection_successes": 0,
            "connection_failures": 0,
            "tool_call_latencies": [],
            "errors": [],
        }

    async def benchmark_ping_latency(
        self, session: ClientSession, iterations: int = 50
    ) -> dict[str, float]:
        """
        Benchmark ping latency over multiple iterations

        Returns:
            Dict with min, max, mean, median, and std deviation
        """
        logger.info(f"\n{'=' * 60}")
        logger.info("PING LATENCY BENCHMARK")
        logger.info(f"{'=' * 60}")

        latencies = []
        failures = 0

        for i in range(iterations):
            try:
                start = time.perf_counter()
                await session.send_ping()
                duration = (time.perf_counter() - start) * 1000  # Convert to ms

                latencies.append(duration)

                if (i + 1) % 10 == 0:
                    logger.info(f"  Progress: {i + 1}/{iterations} pings")

            except Exception as e:
                failures += 1
                logger.error(f"  Ping failed: {e}")

        if not latencies:
            logger.error("❌ All pings failed")
            return {}

        results = {
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "mean_ms": statistics.mean(latencies),
            "median_ms": statistics.median(latencies),
            "stdev_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0,
            "success_rate": (iterations - failures) / iterations * 100,
            "total_pings": iterations,
            "failures": failures,
        }

        logger.info(f"\n📊 PING LATENCY RESULTS:")
        logger.info(f"  Min:     {results['min_ms']:.2f} ms")
        logger.info(f"  Max:     {results['max_ms']:.2f} ms")
        logger.info(f"  Mean:    {results['mean_ms']:.2f} ms")
        logger.info(f"  Median:  {results['median_ms']:.2f} ms")
        logger.info(f"  StdDev:  {results['stdev_ms']:.2f} ms")
        logger.info(f"  Success: {results['success_rate']:.1f}%")

        self.results["ping_latencies"] = latencies
        return results

    async def benchmark_connection_stability(
        self, server_params: StdioServerParameters, duration_seconds: int = 60
    ) -> dict[str, Any]:
        """
        Test connection stability over extended period

        Returns:
            Dict with connection duration, ping count, and failure rate
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"CONNECTION STABILITY BENCHMARK ({duration_seconds}s)")
        logger.info(f"{'=' * 60}")

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                ping_count = 0
                failures = 0
                start_time = time.time()

                while time.time() - start_time < duration_seconds:
                    try:
                        await session.send_ping()
                        ping_count += 1

                        if ping_count % 10 == 0:
                            elapsed = time.time() - start_time
                            logger.info(
                                f"  Progress: {ping_count} pings in {elapsed:.1f}s "
                                f"({ping_count/elapsed:.1f} pings/sec)"
                            )

                        await asyncio.sleep(1)  # 1 ping per second

                    except Exception as e:
                        failures += 1
                        logger.error(f"  Connection failure: {e}")

        results = {
            "duration_seconds": duration_seconds,
            "total_pings": ping_count,
            "failures": failures,
            "success_rate": (ping_count - failures) / ping_count * 100 if ping_count > 0 else 0,
            "pings_per_second": ping_count / duration_seconds,
        }

        logger.info(f"\n📊 STABILITY RESULTS:")
        logger.info(f"  Duration:   {results['duration_seconds']}s")
        logger.info(f"  Total Pings: {results['total_pings']}")
        logger.info(f"  Failures:    {results['failures']}")
        logger.info(f"  Success:     {results['success_rate']:.1f}%")
        logger.info(f"  Throughput:  {results['pings_per_second']:.1f} pings/sec")

        return results

    async def benchmark_concurrent_connections(
        self, server_params: StdioServerParameters, concurrent_count: int = 5
    ) -> dict[str, Any]:
        """
        Test multiple concurrent connections

        Returns:
            Dict with concurrency results and success rates
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"CONCURRENT CONNECTIONS BENCHMARK ({concurrent_count} connections)")
        logger.info(f"{'=' * 60}")

        async def single_connection_test(connection_id: int) -> dict:
            """Test a single connection"""
            try:
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()

                        # Perform 10 pings
                        latencies = []
                        for _ in range(10):
                            start = time.perf_counter()
                            await session.send_ping()
                            latencies.append((time.perf_counter() - start) * 1000)
                            await asyncio.sleep(0.1)

                        return {
                            "connection_id": connection_id,
                            "success": True,
                            "avg_latency_ms": statistics.mean(latencies),
                            "ping_count": len(latencies),
                        }

            except Exception as e:
                logger.error(f"  Connection {connection_id} failed: {e}")
                return {
                    "connection_id": connection_id,
                    "success": False,
                    "error": str(e),
                }

        # Run concurrent connections
        start_time = time.time()
        tasks = [single_connection_test(i) for i in range(concurrent_count)]
        connection_results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.time() - start_time

        successful = [r for r in connection_results if isinstance(r, dict) and r.get("success")]
        failed = [r for r in connection_results if not isinstance(r, dict) or not r.get("success")]

        results = {
            "concurrent_connections": concurrent_count,
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / concurrent_count * 100,
            "total_duration_seconds": duration,
            "avg_latency_ms": (
                statistics.mean([r["avg_latency_ms"] for r in successful]) if successful else 0
            ),
        }

        logger.info(f"\n📊 CONCURRENT CONNECTION RESULTS:")
        logger.info(f"  Total Connections: {results['concurrent_connections']}")
        logger.info(f"  Successful:        {results['successful']}")
        logger.info(f"  Failed:            {results['failed']}")
        logger.info(f"  Success Rate:      {results['success_rate']:.1f}%")
        logger.info(f"  Total Duration:    {results['total_duration_seconds']:.2f}s")
        logger.info(f"  Avg Latency:       {results['avg_latency_ms']:.2f} ms")

        return results

    async def benchmark_tool_calls(self, session: ClientSession, iterations: int = 20) -> dict:
        """
        Benchmark tool call latency

        Returns:
            Dict with tool call performance metrics
        """
        logger.info(f"\n{'=' * 60}")
        logger.info("TOOL CALL LATENCY BENCHMARK")
        logger.info(f"{'=' * 60}")

        # Get available tools
        tools_response = await session.list_tools()
        tools = tools_response.tools if hasattr(tools_response, "tools") else []

        if not tools:
            logger.warning("⚠️  No tools available for benchmarking")
            return {"error": "No tools available"}

        logger.info(f"  Testing with tool: {tools[0].name}")

        latencies = []
        failures = 0

        for i in range(iterations):
            try:
                start = time.perf_counter()

                # Call the first available tool (usually a read-only operation)
                await session.call_tool(tools[0].name, {})

                duration = (time.perf_counter() - start) * 1000  # Convert to ms
                latencies.append(duration)

                if (i + 1) % 5 == 0:
                    logger.info(f"  Progress: {i + 1}/{iterations} calls")

            except Exception as e:
                failures += 1
                logger.debug(f"  Tool call failed: {e}")

        if not latencies:
            logger.error("❌ All tool calls failed")
            return {"error": "All tool calls failed"}

        results = {
            "tool_name": tools[0].name,
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "mean_ms": statistics.mean(latencies),
            "median_ms": statistics.median(latencies),
            "stdev_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0,
            "success_rate": (iterations - failures) / iterations * 100,
            "total_calls": iterations,
            "failures": failures,
        }

        logger.info(f"\n📊 TOOL CALL RESULTS:")
        logger.info(f"  Tool:    {results['tool_name']}")
        logger.info(f"  Min:     {results['min_ms']:.2f} ms")
        logger.info(f"  Max:     {results['max_ms']:.2f} ms")
        logger.info(f"  Mean:    {results['mean_ms']:.2f} ms")
        logger.info(f"  Median:  {results['median_ms']:.2f} ms")
        logger.info(f"  StdDev:  {results['stdev_ms']:.2f} ms")
        logger.info(f"  Success: {results['success_rate']:.1f}%")

        self.results["tool_call_latencies"] = latencies
        return results

    def generate_report(self, output_file: Path | None = None) -> str:
        """Generate a comprehensive benchmark report"""
        report = []
        report.append("\n" + "=" * 80)
        report.append("MCP CONNECTION RELIABILITY BENCHMARK REPORT")
        report.append("=" * 80)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("\n")

        # Summary statistics
        if self.results["ping_latencies"]:
            report.append("PING LATENCY SUMMARY:")
            report.append(f"  Total Pings: {len(self.results['ping_latencies'])}")
            report.append(
                f"  Average:     {statistics.mean(self.results['ping_latencies']):.2f} ms"
            )
            report.append(
                f"  Median:      {statistics.median(self.results['ping_latencies']):.2f} ms"
            )
            report.append("")

        if self.results["tool_call_latencies"]:
            report.append("TOOL CALL LATENCY SUMMARY:")
            report.append(f"  Total Calls: {len(self.results['tool_call_latencies'])}")
            report.append(
                f"  Average:     {statistics.mean(self.results['tool_call_latencies']):.2f} ms"
            )
            report.append(
                f"  Median:      {statistics.median(self.results['tool_call_latencies']):.2f} ms"
            )
            report.append("")

        report.append("=" * 80)

        report_text = "\n".join(report)

        if output_file:
            output_file.write_text(report_text)
            logger.info(f"\n📝 Report saved to: {output_file}")

        return report_text


async def main():
    """Run comprehensive benchmark suite"""
    parser = argparse.ArgumentParser(description="MCP Connection Reliability Benchmark")
    parser.add_argument(
        "--iterations", type=int, default=50, help="Number of iterations for tests"
    )
    parser.add_argument(
        "--concurrent", type=int, default=5, help="Number of concurrent connections to test"
    )
    parser.add_argument(
        "--duration", type=int, default=30, help="Duration in seconds for stability test"
    )
    parser.add_argument(
        "--output", type=str, help="Output file for benchmark report"
    )

    args = parser.parse_args()

    benchmark = ConnectionBenchmark()

    # Example: Test with a local MCP server (filesystem)
    # In production, replace with actual MCP server configuration
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    )

    try:
        logger.info("\n🚀 Starting MCP Connection Reliability Benchmark")
        logger.info(f"   Iterations: {args.iterations}")
        logger.info(f"   Concurrent: {args.concurrent}")
        logger.info(f"   Duration:   {args.duration}s")

        # Test 1: Ping Latency
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await benchmark.benchmark_ping_latency(session, args.iterations)
                await benchmark.benchmark_tool_calls(session, args.iterations // 2)

        # Test 2: Connection Stability
        await benchmark.benchmark_connection_stability(server_params, args.duration)

        # Test 3: Concurrent Connections
        await benchmark.benchmark_concurrent_connections(server_params, args.concurrent)

        # Generate report
        output_file = Path(args.output) if args.output else None
        report = benchmark.generate_report(output_file)
        print(report)

        logger.info("\n✅ Benchmark completed successfully!")

    except KeyboardInterrupt:
        logger.info("\n⚠️  Benchmark interrupted by user")
    except Exception as e:
        logger.error(f"\n❌ Benchmark failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
