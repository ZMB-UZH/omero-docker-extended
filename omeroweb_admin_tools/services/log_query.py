"""Utilities for querying Loki and normalizing log entries."""

from __future__ import annotations

import datetime as dt
import re
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

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
    """Build a Loki query that matches any of the selected container sources.

    We intentionally query ONLY by ``compose_service`` which is guaranteed by our Alloy config:

    - Docker logs: derived from Docker Compose label ``com.docker.compose.service``
    - Internal logs: explicitly set in ``monitoring/alloy/alloy-config.alloy``

    This avoids LogQL parser issues caused by combining multiple stream selectors with ``or``
    (which is not consistently supported across Loki versions/configurations for log queries).
    """
    if not containers:
        raise ValueError("At least one container must be selected for log query.")

    # Loki uses RE2 regex. Escape any user-provided values so they cannot break the query.
    selector = "|".join(re.escape(c) for c in containers)
    return f'{{compose_service=~"^({selector})$"}}'


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
            raw = response.read()
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                snippet = raw[:800].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Loki returned non-JSON response (status {getattr(response, 'status', 'unknown')}): "
                    f"{snippet}"
                ) from exc

    except urllib.error.HTTPError as exc:
        # HTTPError is also a file-like object; read the body for diagnostics.
        try:
            body = exc.read()
            snippet = body[:800].decode("utf-8", errors="replace")
        except Exception:
            snippet = "<unable to read error body>"
        raise RuntimeError(f"Loki HTTP error {exc.code}: {snippet}") from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(f"Loki request failed: {exc}") from exc
    entries: List[LogEntry] = []
    for stream in payload.get("data", {}).get("result", []):
        stream_labels = stream.get("stream", {})
        level = stream_labels.get("level", "info")
        container = stream_labels.get("container", "unknown")
        compose_service = stream_labels.get("compose_service")
        display_container = compose_service or container
        filename = _extract_filename(stream_labels)
        if compose_service and compose_service.endswith("_internal") and filename:
            display_container = f"{compose_service}/{filename}"
        for value in stream.get("values", []):
            timestamp_ns, message = value
            entries.append(
                LogEntry(
                    timestamp=_format_timestamp(timestamp_ns),
                    container=display_container,
                    level=str(level).lower(),
                    message=message,
                )
            )
    return entries


def _extract_filename(stream_labels: Dict[str, str]) -> Optional[str]:
    """Extract the filename label for internal OMERO log streams."""
    for key in ("filename", "__path__", "path", "file"):
        value = stream_labels.get(key)
        if value:
            return os.path.basename(value)
    return None


def fetch_internal_log_labels(
    config: LogConfig,
    compose_service: str,
) -> List[str]:
    """Query Loki for distinct filenames collected under a compose_service label.

    Returns a sorted list of base filenames (e.g. ``["Blitz-0.log", "master.err"]``).
    """
    selector = f'{{compose_service="{compose_service}"}}'
    end_time = dt.datetime.now(tz=dt.timezone.utc)
    start_time = end_time - dt.timedelta(seconds=config.lookback_seconds)
    # The Loki /series endpoint requires the parameter name ``match[]``,
    # NOT ``query`` (which is for /query_range).  Using the wrong name
    # causes Loki to silently ignore the selector and return ALL series.
    params = urllib.parse.urlencode(
        {
            "match[]": selector,
            "start": str(int(start_time.timestamp() * 1e9)),
            "end": str(int(end_time.timestamp() * 1e9)),
        }
    )
    url = f"{config.loki_url}/loki/api/v1/series?{params}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            raw = response.read()
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                return []
    except (urllib.error.HTTPError, urllib.error.URLError):
        return []

    filenames: set[str] = set()
    for series in payload.get("data", []):
        # Double-check the compose_service label matches, in case Loki
        # returns broader results than expected.
        if series.get("compose_service") != compose_service:
            continue
        fname = _extract_filename(series)
        if fname:
            filenames.add(fname)
    return sorted(filenames)


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
