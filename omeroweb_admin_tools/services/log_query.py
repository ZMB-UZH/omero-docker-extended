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


def _parse_level_from_message(message: str) -> Optional[str]:
    """Try to extract a log level from the message text.

    OMERO log lines typically contain level keywords such as DEBUG, INFO, WARN,
    WARNING, ERROR, FATAL, CRITICAL, SEVERE, or TRACE either as standalone
    tokens or inside bracket-delimited fields.  Docker container logs from
    Postgres, Redis, OMERO.web (gunicorn), etc. use varying formats.  We try
    a few common patterns and return the first match (normalised to lowercase).
    """
    if not message:
        return None

    # Map of recognised tokens → canonical level names.
    _LEVEL_MAP = {
        "TRACE": "debug",
        "DEBUG": "debug",
        "INFO": "info",
        "NOTICE": "info",
        "WARN": "warn",
        "WARNING": "warn",
        "ERROR": "error",
        "SEVERE": "error",
        "CRITICAL": "fatal",
        "FATAL": "fatal",
        "PANIC": "fatal",
        "LOG": "info",        # Postgres uses "LOG"
    }

    # Pattern 1: level keyword in square brackets or after a timestamp, e.g.
    #   "2026-02-02 11:01:49,631 DEBUG [..."
    #   "[INFO] some message"
    #   "... INFO  [..."
    # We look for a standalone level token surrounded by whitespace, brackets,
    # or start/end of string.
    m = re.search(
        r'(?:^|[\s\[\(])(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|SEVERE|CRITICAL|FATAL|PANIC|LOG)(?:[\s\]\):]|$)',
        message[:500],  # limit search to first 500 chars for performance
    )
    if m:
        token = m.group(1).upper()
        if token in _LEVEL_MAP:
            return _LEVEL_MAP[token]

    return None


def _execute_loki_query(
    config: LogConfig,
    query: str,
    lookback_seconds: int,
    max_entries: int,
) -> dict:
    """Execute a single Loki query_range request and return the parsed JSON payload."""
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
                return json.loads(raw.decode("utf-8", errors="replace"))
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


def _parse_entries_from_payload(payload: dict) -> List[LogEntry]:
    """Extract LogEntry objects from a Loki query_range response payload."""
    entries: List[LogEntry] = []
    for stream in payload.get("data", {}).get("result", []):
        stream_labels = stream.get("stream", {})
        stream_level = stream_labels.get("level", "").strip().lower() or ""
        # Treat Loki/Alloy-detected_level if present (some Loki versions
        # auto-detect it).
        if not stream_level or stream_level == "info":
            stream_level = stream_labels.get("detected_level", "").strip().lower() or stream_level
        container = stream_labels.get("container", "unknown")
        compose_service = stream_labels.get("compose_service")
        display_container = compose_service or container
        filename = _extract_filename(stream_labels)
        # For internal log streams, ALWAYS include the filename in the
        # display_container so the JS filter can match them against the
        # user's file selection.  When no filename label is available
        # (which can happen when Alloy/Loki drops __path__ on query) we
        # still tag with "unknown" so the entry is visible instead of
        # silently hidden.
        if compose_service and compose_service.endswith("_internal"):
            display_container = f"{compose_service}/{filename or 'unknown'}"
        for value in stream.get("values", []):
            timestamp_ns, message = value
            # Determine severity: prefer the stream-level label, but if
            # it is missing / generic "info" we try to parse a more
            # specific level from the log message content.
            level = stream_level or "info"
            parsed = _parse_level_from_message(message)
            if parsed:
                level = parsed
            elif not stream_level:
                level = "info"
            entries.append(
                LogEntry(
                    timestamp=_format_timestamp(timestamp_ns),
                    container=display_container,
                    level=level,
                    message=message,
                )
            )
    return entries


def fetch_loki_logs(
    config: LogConfig,
    containers: List[str],
    lookback_seconds: int,
    max_entries: int,
) -> List[LogEntry]:
    """Fetch logs from Loki for the selected containers and time window.

    Docker container sources are queried together in a single Loki request.
    Each internal log source (``*_internal``) is queried **individually** so
    that every service gets its own share of ``max_entries`` and a single
    high-volume service cannot starve others.
    """
    docker_containers = [c for c in containers if not c.endswith("_internal")]
    internal_services = [c for c in containers if c.endswith("_internal")]

    all_entries: List[LogEntry] = []

    # ── Docker container logs: single combined query ──
    if docker_containers:
        query = build_loki_query(docker_containers)
        payload = _execute_loki_query(config, query, lookback_seconds, max_entries)
        all_entries.extend(_parse_entries_from_payload(payload))

    # ── Internal logs: one query per service ──
    # Each service (omeroserver_internal, omeroweb_internal) gets its own
    # query with the full max_entries limit.  This ensures that both
    # services are always represented even when one is far more active.
    for service in internal_services:
        query = f'{{compose_service="{service}"}}'
        try:
            payload = _execute_loki_query(config, query, lookback_seconds, max_entries)
            all_entries.extend(_parse_entries_from_payload(payload))
        except RuntimeError:
            # If one service query fails, continue with the others.
            pass

    return all_entries


def _extract_filename(stream_labels: Dict[str, str]) -> Optional[str]:
    """Extract the filename label for internal OMERO log streams."""
    for key in ("filename", "filepath", "__path__", "path", "file"):
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
