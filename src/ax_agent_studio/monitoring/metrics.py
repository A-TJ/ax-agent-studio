"""
Internal metrics logging utilities.

These helpers provide a consistent way to emit structured metrics without
introducing a full telemetry dependency. Metrics are logged through the
standard logging subsystem so they automatically respect existing handlers.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

METRIC_LOGGER = logging.getLogger("ax.metrics")


def log_metric(event: str, **fields: Any) -> None:
    """Emit a structured metric entry."""
    payload = {
        "event": event,
        "timestamp": time.time(),
        **fields,
    }
    try:
        METRIC_LOGGER.info("METRIC %s", json.dumps(payload, default=str))
    except Exception:
        METRIC_LOGGER.debug("Failed to serialize metric payload", exc_info=True)

