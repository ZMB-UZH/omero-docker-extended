"""Utilities for querying Loki and normalizing log entries."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Dict, List

import urllib.error
import urllib.parse
import urllib.request

from ..config import LogConfig


@dataclass(frozen=True)
class LogEntry:
    """Typed log entry returned from Loki."""

    timestamp: str
    container: str
    level: str
    message: str


def build_loki_query(containers: List[str]) -> str:
    """Build a Loki query that matches any of the selected containers."""
    if not containers:
        raise ValueError("At least one container must be selected for log query.")
    container_selector = "|".join(containers)
    return f'{{compose_service=~"{container_selector}"}}'


def _format_timestamp(value_ns: str) -> str:
    """Convert a Loki nanosecond timestamp to an ISO string."""
    timestamp = dt.datetime.fromtimestamp(int(value_ns) / 1e9, tz=dt.timezone.utc)
    return timestamp.isoformat()


def fetch_loki_logs(
    config: LogConfig,
    containers: List[str],
    lookback_seconds: int,
    max_entries: int,
) -> List[LogEntry]:
    """Fetch logs from Loki for the selected containers and time window."""
    query = build_loki_query(containers)
    end_time = dt.datetime.now(tz=dt.timezone.utc)
    start_time = end_time - dt.timedelta(seconds=lookback_seconds)
    params = urllib.parse.urlencode(
        {
            "query": query,
            "direction": "backward",
            "limit": max_entries,
            "start": str(int(start_time.timestamp() * 1e9)),
            "end": str(int(end_time.timestamp() * 1e9)),
        }
    )
    url = f"{config.loki_url}/loki/api/v1/query_range?{params}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Loki request failed: {exc}") from exc
    entries: List[LogEntry] = []
    for stream in payload.get("data", {}).get("result", []):
        level = stream.get("stream", {}).get("level", "info")
        container = stream.get("stream", {}).get("container", "unknown")
        for value in stream.get("values", []):
            timestamp_ns, message = value
            entries.append(
                LogEntry(
                    timestamp=_format_timestamp(timestamp_ns),
                    container=container,
                    level=str(level).lower(),
                    message=message,
                )
            )
    return entries


def serialize_entries(entries: List[LogEntry]) -> List[Dict[str, str]]:
    """Serialize LogEntry objects for JSON responses."""
    return [
        {
            "timestamp": entry.timestamp,
            "container": entry.container,
            "level": entry.level,
            "message": entry.message,
        }
        for entry in entries
    ]
