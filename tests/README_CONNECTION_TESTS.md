# MCP Connection Reliability Tests

This directory contains comprehensive tests for MCP connection reliability, including unit tests, integration tests, and benchmarks.

## Test Files

### 1. `test_mcp_connection_reliability.py`
Unit tests for MCP connection components:
- **Heartbeat functionality** - Tests basic heartbeat, failure handling, and recovery
- **Connection retry logic** - Tests connection recovery and graceful cancellation
- **MCPServerManager reliability** - Tests config validation and session management
- **Connection latency** - Tests ping latency measurements
- **Error handling** - Tests timeout and network error handling

**Run unit tests:**
```bash
pytest tests/test_mcp_connection_reliability.py -v
```

### 2. `test_mcp_connection_integration.py`
Integration tests for real-world MCP scenarios:
- **Connection lifecycle** - Tests connect/disconnect cycles
- **Tool calling** - Tests listing and calling tools on live servers
- **Session management** - Tests primary session retrieval
- **Heartbeat integration** - Tests heartbeat with actual connections
- **Connection resilience** - Tests rapid cycling and concurrent operations
- **Real-world scenarios** - Tests long-running sessions

**Run integration tests:**
```bash
pytest tests/test_mcp_connection_integration.py -v -m integration
```

### 3. `benchmark_mcp_connections.py`
Performance benchmarks for MCP connections:
- **Ping latency** - Measures min/max/mean/median latency over iterations
- **Connection stability** - Tests connection over extended duration
- **Concurrent connections** - Tests multiple simultaneous connections
- **Tool call latency** - Measures tool invocation performance

**Run benchmarks:**
```bash
# Basic benchmark
python tests/benchmark_mcp_connections.py

# Custom parameters
python tests/benchmark_mcp_connections.py --iterations 100 --concurrent 10 --duration 60

# Save report to file
python tests/benchmark_mcp_connections.py --output benchmark_report.txt
```

## Test Categories

### Unit Tests (`test_mcp_connection_reliability.py`)
- ✅ Fast execution (uses mocks)
- ✅ No external dependencies
- ✅ Tests individual components
- ✅ Runs in CI/CD pipeline

### Integration Tests (`test_mcp_connection_integration.py`)
- ⚠️ Requires MCP servers
- ⚠️ Slower execution
- ✅ Tests real-world scenarios
- ✅ Marked with `@pytest.mark.integration`

### Benchmarks (`benchmark_mcp_connections.py`)
- 📊 Performance measurements
- 📊 Latency analysis
- 📊 Success rate tracking
- 📊 Generates detailed reports

## Running All Tests

```bash
# Run all unit tests
pytest tests/test_mcp_connection_reliability.py -v

# Run all integration tests
pytest tests/test_mcp_connection_integration.py -v -m integration

# Run all connection tests (unit + integration)
pytest tests/test_mcp_connection_*.py -v

# Run with coverage
pytest tests/test_mcp_connection_*.py --cov=ax_agent_studio --cov-report=html

# Run specific test class
pytest tests/test_mcp_connection_reliability.py::TestConnectionStability -v

# Run specific test
pytest tests/test_mcp_connection_reliability.py::TestConnectionStability::test_heartbeat_basic_functionality -v
```

## Benchmark Usage Examples

### Quick Benchmark (30s)
```bash
python tests/benchmark_mcp_connections.py --iterations 20 --duration 10
```

### Comprehensive Benchmark (5 min)
```bash
python tests/benchmark_mcp_connections.py --iterations 200 --concurrent 20 --duration 300 --output results.txt
```

### Stress Test
```bash
python tests/benchmark_mcp_connections.py --iterations 500 --concurrent 50 --duration 600
```

## Test Metrics

### Connection Reliability
- **Success Rate**: Percentage of successful connections/operations
- **Ping Latency**: Round-trip time for ping operations (ms)
- **Tool Call Latency**: Time to execute tool calls (ms)
- **Failure Rate**: Percentage of failed operations
- **Recovery Time**: Time to recover from failures

### Performance Benchmarks
- **Min Latency**: Fastest operation
- **Max Latency**: Slowest operation
- **Mean Latency**: Average latency
- **Median Latency**: 50th percentile
- **Standard Deviation**: Latency variance
- **Throughput**: Operations per second

## Understanding Test Results

### ✅ All Tests Pass
Connection reliability is good. All components working correctly.

### ⚠️ Some Integration Tests Fail
May indicate:
- MCP server not available
- Network issues
- Configuration problems

### ❌ Unit Tests Fail
Indicates code-level issues that need immediate attention.

### 📊 Benchmark Results
- **Latency < 100ms**: Excellent
- **Latency 100-500ms**: Good
- **Latency 500-1000ms**: Acceptable
- **Latency > 1000ms**: Investigate network/server issues

## Continuous Integration

Add to your CI/CD pipeline:

```yaml
# .github/workflows/test.yml
- name: Run Connection Tests
  run: |
    pytest tests/test_mcp_connection_reliability.py -v
    pytest tests/test_mcp_connection_integration.py -v -m integration
```

## Troubleshooting

### Tests Fail with "Connection timeout"
- Check MCP server is running
- Verify network connectivity
- Increase timeout values

### Tests Fail with "FileNotFoundError"
- Ensure config files exist
- Check file paths in tests

### Integration Tests Skip
- MCP servers may not be available
- Check server configuration
- Verify MCP server installation

## Contributing

When adding new connection-related features:

1. ✅ Add unit tests to `test_mcp_connection_reliability.py`
2. ✅ Add integration tests to `test_mcp_connection_integration.py`
3. ✅ Update benchmarks if adding performance-critical features
4. ✅ Document new test scenarios in this README

## Related Documentation

- [MCP Manager Documentation](../src/ax_agent_studio/mcp_manager.py)
- [Heartbeat Documentation](../src/ax_agent_studio/mcp_heartbeat.py)
- [Main README](../README.md)
