"""Real-time Activity Logger for Knowledge Brain MCP server.

Appends structured JSON event records to ~/.knowledge-brain/activity.jsonl.
Guaranteed to never write to stdout so FastMCP stdio protocol is 100% clean.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_PATH = Path.home() / ".knowledge-brain" / "activity.jsonl"


def _generate_event_id() -> str:
    ms = time.time_ns() // 1_000_000
    rand = bytearray(os.urandom(10))
    ts_bytes = ms.to_bytes(6, "big")
    rand[0] = (rand[0] & 0x0F) | 0x70
    rand[2] = (rand[2] & 0x3F) | 0x80
    raw = (ts_bytes + bytes(rand)).hex()
    return f"EVT_{raw[:12].upper()}"


def log_activity(
    *,
    tool: str,
    client: str = "antigravity",
    operation: str,
    status: str = "success",
    workspace: str | None = None,
    branch: str | None = None,
    project_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a structured audit event to activity.jsonl in a thread/process safe way."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    now_time = datetime.now().strftime("%H:%M:%S")

    event_record = {
        "id": _generate_event_id(),
        "timestamp": now_iso,
        "time_str": now_time,
        "tool": tool,
        "client": client or "antigravity",
        "operation": operation,
        "status": status,
        "database": "Kuzu Graph",
        "workspace": workspace or "current",
        "branch": branch or "main",
        "project_id": project_id or "default",
        "details": details or {},
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_record) + "\n")
    except Exception:
        # Never crash or write to stdout if logging encounters an issue
        pass

    return event_record


def get_recent_activities(limit: int = 50) -> list[dict[str, Any]]:
    """Read the latest events in reverse chronological order."""
    if not LOG_PATH.exists():
        return []

    events: list[dict[str, Any]] = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                events.append(json.loads(line_str))
                if len(events) >= limit:
                    break
            except Exception:
                continue
    except Exception:
        return []
    return events


def get_activity_stats() -> dict[str, Any]:
    """Calculate live aggregated stats across recorded events."""
    events = get_recent_activities(limit=500)
    total = len(events)
    counts = {"remember": 0, "recall": 0, "handoff": 0, "forget": 0}
    clients: set[str] = set()

    for e in events:
        tool = e.get("tool", "")
        if tool in counts:
            counts[tool] += 1
        if e.get("client"):
            clients.add(e["client"])

    return {
        "total_invocations": total,
        "by_tool": counts,
        "active_clients": list(clients),
        "latest_timestamp": events[0]["timestamp"] if events else None,
    }

