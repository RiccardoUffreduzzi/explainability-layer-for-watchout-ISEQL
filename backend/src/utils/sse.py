from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

SENTINEL_RUN_DONE = "<<RUN_DONE>>"
SENTINEL_RUN_FAILED = "<<RUN_FAILED>>"

HEARTBEAT_INTERVAL = 15.0


def format_sse_event(event: str, data: str) -> str:
    """Format an SSE event with the given event name and data payload."""
    lines = ["event: " + event]
    for chunk_line in data.split("\n"):
        lines.append("data: " + chunk_line)
    lines.append("")
    return "\n".join(lines) + "\n"


def make_log_entry(stage: str, message: str, **extra) -> dict:
    """Create a log entry dict with timestamp, stage, and message."""
    return {"ts": time.time(), "stage": stage, "message": message, **extra}


async def drain_queue_into_sse(
    queue: asyncio.Queue, heartbeat_interval: float = HEARTBEAT_INTERVAL
) -> AsyncIterator[str]:
    """Drain an asyncio.Queue into SSE events until a sentinel is received."""
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
        except asyncio.TimeoutError:
            yield ": ping\n\n"
            continue
        yield format_sse_event("log", json.dumps(item))
        if item.get("message") == SENTINEL_RUN_DONE:
            yield format_sse_event("end", "{}")
            return
        if item.get("message") == SENTINEL_RUN_FAILED:
            yield format_sse_event("end", "{}")
            return
