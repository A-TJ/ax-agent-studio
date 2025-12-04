"""
Heartbeat and liveness tracking utilities.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable


HeartbeatCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class LivenessRecord:
    name: str
    timeout: timedelta
    metadata: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: datetime | None = None
    consecutive_misses: int = 0

    def beat(self) -> None:
        self.last_heartbeat = datetime.now(UTC)
        self.consecutive_misses = 0

    def mark_miss(self) -> None:
        self.consecutive_misses += 1

    def is_alive(self) -> bool:
        if self.last_heartbeat is None:
            return False
        return datetime.now(UTC) - self.last_heartbeat <= self.timeout


class LivenessRegistry:
    """Tracks liveness for multiple logical sessions or processes."""

    def __init__(
        self,
        domain: str,
        on_state_change: HeartbeatCallback | None = None,
    ):
        self.domain = domain
        self._records: dict[str, LivenessRecord] = {}
        self._state_callback = on_state_change
        self._lock = asyncio.Lock()

    def register(
        self,
        name: str,
        timeout: float,
        metadata: dict[str, Any] | None = None,
    ) -> LivenessRecord:
        record = LivenessRecord(
            name=name,
            timeout=timedelta(seconds=timeout),
            metadata=metadata or {},
        )
        self._records[name] = record
        return record

    async def beat(self, name: str) -> None:
        async with self._lock:
            record = self._records.get(name)
            if not record:
                return
            record.beat()
            await self._emit_state(name, "alive", record)

    async def miss(self, name: str) -> None:
        async with self._lock:
            record = self._records.get(name)
            if not record:
                return
            record.mark_miss()
            await self._emit_state(name, "miss", record)

    async def mark_dead(self, name: str) -> None:
        async with self._lock:
            record = self._records.get(name)
            if not record:
                return
            await self._emit_state(name, "dead", record)

    async def _emit_state(self, name: str, state: str, record: LivenessRecord) -> None:
        if not self._state_callback:
            return
        payload = {
            "domain": self.domain,
            "name": name,
            "state": state,
            "last_heartbeat": record.last_heartbeat,
            "consecutive_misses": record.consecutive_misses,
            **record.metadata,
        }
        try:
            self._state_callback(name, payload)
        except Exception:
            # Never raise from telemetry hooks
            pass

    def summary(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in self._records.values():
            items.append(
                {
                    "name": record.name,
                    "alive": record.is_alive(),
                    "last_heartbeat": record.last_heartbeat,
                    "consecutive_misses": record.consecutive_misses,
                    **record.metadata,
                }
            )
        return items

