import asyncio

import pytest

from ax_agent_studio.monitoring.liveness import LivenessRegistry


@pytest.mark.asyncio
async def test_liveness_registry_tracks_beats():
    registry = LivenessRegistry("test")
    registry.register("session", timeout=0.5)

    await registry.beat("session")
    await asyncio.sleep(0.1)
    summary = registry.summary()
    assert summary[0]["alive"] is True

    await asyncio.sleep(0.6)
    summary = registry.summary()
    assert summary[0]["alive"] is False

