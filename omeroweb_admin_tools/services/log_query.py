"""Utilities for querying Loki and normalizing log entries."""

from __future__ import annotations

import datetime as dt
import logging
import re
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import urllib.error
import urllib.parse
import urllib.request

from ..config import LogConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LogEntry:
    """Typed log entry returned from Loki."""

    timestamp: str
    container: str
    level: str
    message: str


def _normalize_internal_service(service: str) -> str:
    """
    UI uses service keys like 'omeroserver_internal' and 'omeroweb_internal'.
    Loki streams in this project are labeled with compose_service='omeroserver'/'omeroweb'
    and log_type='internal'.  Normalize keys so queries match what Loki actually stores.
    """
    if service.endswith("_internal"):
        return service[: -len("_internal")]
    return service


def _split_internal_container(container: str) -> Optional[Tuple[str, str]]:
    """Split a container string like 'omeroserver_internal/Blitz-0.log'."""
    if "_internal/" not in container:
        return None
    service, filename = container.split("/", 1)
    if not service or not filename:
        return None
    return service, filename


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
        "LOG": "info",  # Postgres uses "LOG"
    }

    # Pattern 1: level keyword in square brackets or after a timestamp, e.g.
    #   "2026-02-02 11:01:49,631 DEBUG [..."
    #   "[INFO] some message"
    #   "... INFO  [..."
    # We look for a standalone level token surrounded by whitespace, brackets,
    # or start/end of string.
    m = re.search(
        r"(?:^|[\s\[\(])(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|SEVERE|CRITICAL|FATAL|PANIC|LOG)(?:[\s\]\):]|$)",
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
        with urllib.request.urlopen(
            request, timeout=config.timeout_seconds
        ) as response:
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
            stream_level = (
                stream_labels.get("detected_level", "").strip().lower() or stream_level
            )
        container = stream_labels.get("container", "unknown")
        compose_service = stream_labels.get("compose_service")
        log_type = stream_labels.get("log_type", "")
        display_container = compose_service or container
        filename = _extract_filename(stream_labels)
        # For internal log streams, ALWAYS include the filename in the
        # display_container so the JS filter can match them against the
        # user's file selection.  When no filename label is available
        # (which can happen when Alloy/Loki drops __path__ on query) we
        # still tag with "unknown" so the entry is visible instead of
        # silently hidden.
        # Detection: check for log_type="internal" OR compose_service ending with "_internal"
        # to support both old and new Alloy configurations.
        is_internal = (log_type == "internal") or (
            compose_service and compose_service.endswith("_internal")
        )
        if is_internal:
            # For the UI, we need the container name to include "_internal" suffix
            # so the JS filtering logic can identify internal log entries.
            service_base = (
                _normalize_internal_service(compose_service)
                if compose_service
                else "unknown"
            )
            display_container = f"{service_base}_internal/{filename or 'unknown'}"
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
            cleaned_message = _strip_message_prefix(message)
            if cleaned_message:
                message = cleaned_message
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
    internal_files: Optional[Dict[str, set[str]]] = None,
) -> List[LogEntry]:
    """Fetch logs from Loki for the selected containers and time window.

    Docker container sources and internal log files are queried independently
    so that each source can receive up to ``max_entries`` entries without
    starving other selections.
    """
    docker_containers = [c for c in containers if not c.endswith("_internal")]
    internal_services = [c for c in containers if c.endswith("_internal")]

    logger.debug(
        "fetch_loki_logs called: docker=%s, internal=%s, lookback=%d, max=%d",
        docker_containers,
        internal_services,
        lookback_seconds,
        max_entries,
    )

    all_entries: List[LogEntry] = []

    # ── Docker container logs: query each container independently ──
    # For containers that also have internal file logs (omeroserver, omeroweb),
    # we use the container_id label to filter to ONLY Docker container logs.
    # Docker logs have container_id set, internal file logs do not.
    # For other containers (database, redis), we query normally.
    containers_with_internal_logs = {"omeroserver", "omeroweb"}

    for container in docker_containers:
        if container in containers_with_internal_logs:
            # Use container_id=~".+" to match only Docker logs (which have container_id)
            # Internal file logs don't have container_id label, so they won't match
            query = f'{{compose_service="{container}", container_id=~".+"}}'
        else:
            query = f'{{compose_service="{container}"}}'

        try:
            payload = _execute_loki_query(config, query, lookback_seconds, max_entries)
            entries = _parse_entries_from_payload(payload)
            logger.debug("Docker query for %s: got %d entries", container, len(entries))
            all_entries.extend(entries)
        except RuntimeError as exc:
            logger.warning("Docker log query failed for %s: %s", container, exc)

    # ── Internal logs: one query per service ──
    # Query all internal logs for each service. File-level filtering is done
    # on the frontend based on user's checkbox selections.
    for service in internal_services:
        normalized = _normalize_internal_service(service)
        query = f'{{compose_service="{normalized}", log_type="internal"}}'
        try:
            payload = _execute_loki_query(config, query, lookback_seconds, max_entries)
            entries = _parse_entries_from_payload(payload)
            selected_files = internal_files.get(service) if internal_files else None
            if selected_files:
                filtered_entries: List[LogEntry] = []
                for entry in entries:
                    parsed = _split_internal_container(entry.container)
                    if not parsed:
                        continue
                    entry_service, filename = parsed
                    if entry_service == service and filename in selected_files:
                        filtered_entries.append(entry)
                entries = filtered_entries
            logger.debug(
                "Internal query for %s (normalized=%s): got %d entries",
                service,
                normalized,
                len(entries),
            )
            all_entries.extend(entries)
        except RuntimeError as exc:
            logger.warning("Internal log query failed for %s: %s", service, exc)

    result = _cap_entries_per_container(all_entries, max_entries)
    logger.debug(
        "fetch_loki_logs returning %d entries (from %d total)",
        len(result),
        len(all_entries),
    )
    return result


def _strip_message_prefix(message: str) -> str:
    """Remove duplicate timestamp/level prefixes from a log message."""
    if not message:
        return message

    patterns = [
        re.compile(
            r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?\s+"
            r"\[?(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|SEVERE|CRITICAL|FATAL|PANIC|LOG)\]?\s+",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*\[?(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|SEVERE|CRITICAL|FATAL|PANIC|LOG)\]?\s+"
            r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?\s+",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        cleaned = pattern.sub("", message, count=1)
        if cleaned != message:
            return cleaned.lstrip()
    return message


def _extract_filename(stream_labels: Dict[str, str]) -> Optional[str]:
    """Extract the filename label for internal OMERO log streams."""
    for key in ("filename", "filepath", "__path__", "path", "file"):
        value = stream_labels.get(key)
        if value:
            return os.path.basename(value)
    return None


def _build_internal_file_query(
    service: str, filename: str, label_key: str = "filepath"
) -> str:
    """Build a Loki query for a specific internal log file."""
    normalized = _normalize_internal_service(service)
    escaped = re.escape(filename)
    return f'{{compose_service="{normalized}", log_type="internal", {label_key}=~"(^|.*/){escaped}$"}}'


def _cap_entries_per_container(entries: List[LogEntry], limit: int) -> List[LogEntry]:
    """Limit entries per container/file to the most recent `limit` items."""
    if limit <= 0:
        return []
    buckets: Dict[str, List[LogEntry]] = {}
    for entry in entries:
        buckets.setdefault(entry.container, []).append(entry)

    capped: List[LogEntry] = []
    for container, container_entries in buckets.items():
        container_entries.sort(key=_entry_sort_key, reverse=True)
        capped.extend(container_entries[:limit])
    return capped


def _apply_global_cap(entries: List[LogEntry], limit: int) -> List[LogEntry]:
    """Apply a global cap on total entries, keeping the most recent ones."""
    if limit <= 0:
        return []
    if len(entries) <= limit:
        return entries
    # Sort by timestamp descending and take the most recent `limit` entries
    sorted_entries = sorted(entries, key=_entry_sort_key, reverse=True)
    return sorted_entries[:limit]


def _entry_sort_key(entry: LogEntry) -> Tuple[int, str]:
    """Sort key for log entries based on timestamp."""
    try:
        timestamp = dt.datetime.fromisoformat(entry.timestamp)
        return int(timestamp.timestamp()), entry.timestamp
    except ValueError:
        return 0, entry.timestamp


def fetch_internal_log_labels(
    config: LogConfig,
    compose_service: str,
) -> Tuple[List[str], str]:
    """Query Loki for distinct filenames collected under a compose_service label.

    Returns a sorted list of base filenames (e.g. ``["Blitz-0.log", "master.err"]``).
    """
    normalized = _normalize_internal_service(compose_service)
    selector = f'{{compose_service="{normalized}", log_type="internal"}}'
    end_time = dt.datetime.now(tz=dt.timezone.utc)
    label_lookback_seconds = max(config.lookback_seconds, 7 * 24 * 60 * 60)
    start_time = end_time - dt.timedelta(seconds=label_lookback_seconds)
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
    logger.debug("fetch_internal_log_labels: querying %s", url)
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(
            request, timeout=config.timeout_seconds
        ) as response:
            raw = response.read()
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                logger.warning("fetch_internal_log_labels: JSON decode error: %s", exc)
                # Keep return type consistent (Tuple[List[str], str]) to avoid
                # a ValueError during unpacking in the Django view.
                return [], "filepath"
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        logger.warning("fetch_internal_log_labels: request failed: %s", exc)
        return [], "filepath"

    filenames: set[str] = set()
    label_key = "filepath"
    label_candidates = ("filepath", "filename", "__path__", "path", "file")
    series_data = payload.get("data", [])
    logger.debug("fetch_internal_log_labels: got %d series from Loki", len(series_data))
    for series in series_data:
        # Double-check labels match, in case Loki returns broader results than expected.
        if series.get("compose_service") != normalized:
            continue
        if series.get("log_type") != "internal":
            continue
        for candidate in label_candidates:
            if candidate in series:
                label_key = candidate
                break
        fname = _extract_filename(series)
        if fname:
            filenames.add(fname)
    result = sorted(filenames)
    logger.debug(
        "fetch_internal_log_labels: found %d files for %s: %s",
        len(result),
        compose_service,
        result[:5],  # Log first 5 filenames
    )
    return result, label_key


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
