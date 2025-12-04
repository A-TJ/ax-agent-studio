import asyncio
import os
from datetime import datetime

import pytest

from ax_agent_studio.monitoring.liveness import LivenessRegistry


@pytest.mark.asyncio
async def test_simulated_long_running_session():
    """Fast-running simulation that mimics multi-hour beats."""
    registry = LivenessRegistry("stability")
    registry.register("session", timeout=5)

    for _ in range(50):
        await registry.beat("session")
        await asyncio.sleep(0.02)

    summary = registry.summary()[0]
    assert summary["alive"] is True


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_STABILITY_TESTS") != "1",
    reason="Set RUN_STABILITY_TESTS=1 to enable soak test",
)
async def test_extended_stability_window():
    """
    Optional soak test that can run for hours/days when triggered via env vars.
    """
    iterations = int(os.getenv("STABILITY_ITERATIONS", "120"))
    sleep_seconds = float(os.getenv("STABILITY_SLEEP_SECONDS", "0.5"))

    registry = LivenessRegistry("extended_stability")
    registry.register("session", timeout=max(5, sleep_seconds * 4))

    start = datetime.utcnow()
    for _ in range(iterations):
        await registry.beat("session")
        await asyncio.sleep(sleep_seconds)

    elapsed = (datetime.utcnow() - start).total_seconds()
    assert elapsed >= iterations * sleep_seconds

