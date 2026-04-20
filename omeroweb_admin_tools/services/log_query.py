"""Utilities for querying Loki and normalizing log entries."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import glob
import hashlib
import logging
import re
import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple, cast

import urllib.parse
import requests

from ..config import LogConfig
from omero_plugin_common.logging_utils import (
    sanitize_log_value,
    sanitize_url_for_logging,
)

logger = logging.getLogger(__name__)

_LOG_RESULT_CACHE_TTL_SECONDS = 5.0
_LABEL_CACHE_TTL_SECONDS = 60.0
_DEFAULT_LOG_CACHE_MAX_BYTES = 512 * 1024 * 1024
_DEFAULT_LABEL_CACHE_MAX_BYTES = 8 * 1024 * 1024
_CACHE_MAX_ITEMS = 128
_MAX_PARALLEL_LOKI_QUERIES = 4
_INTERNAL_FILE_QUERY_BATCH_SIZE = 12

_INTERNAL_LOG_GLOB_PATTERNS = {
    "omeroserver": (
        "/opt/omero/server/OMERO.server/var/log/*.log",
        "/opt/omero/server/OMERO.server/var/log/*.out",
        "/opt/omero/server/OMERO.server/var/log/*.err",
        "/opt/omero/server/OMERO.server/var/log/*/*.log",
        "/opt/omero/server/OMERO.server/var/log/*/*.out",
        "/opt/omero/server/OMERO.server/var/log/*/*.err",
    ),
    "omeroweb": (
        "/opt/omero/web/OMERO.web/var/log/*.log",
        "/opt/omero/web/OMERO.web/var/log/*.out",
        "/opt/omero/web/OMERO.web/var/log/*.err",
        "/opt/omero/web/OMERO.web/var/log/*/*.log",
        "/opt/omero/web/OMERO.web/var/log/*/*.out",
        "/opt/omero/web/OMERO.web/var/log/*/*.err",
        "/opt/omero/web/logs/*.log",
        "/opt/omero/web/logs/*.out",
        "/opt/omero/web/logs/*.err",
        "/opt/omero/web/logs/*/*.log",
        "/opt/omero/web/logs/*/*.out",
        "/opt/omero/web/logs/*/*.err",
    ),
}


@dataclass(frozen=True)
class _QueryJob:
    """Single Loki query task."""

    query: str
    source_type: str
    source_name: str
    selected_files: Tuple[str, ...] = ()


@dataclass(frozen=True)
class _CacheRecord:
    """Stored cached value with expiry metadata."""

    value: object
    expires_at: float
    size_bytes: int


class _InMemoryTTLCache:
    """Small process-local TTL cache with in-flight request coalescing."""

    def __init__(
        self,
        ttl_seconds: float,
        max_items: int,
        max_bytes: int,
        size_estimator: Callable[[object], int],
    ):
        self._ttl_seconds = ttl_seconds
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._size_estimator = size_estimator
        self._values: Dict[object, _CacheRecord] = {}
        self._inflight: Dict[object, concurrent.futures.Future] = {}
        self._total_size_bytes = 0
        self._lock = threading.Lock()

    def get_or_load(self, key: object, loader: Callable[[], object]) -> object:
        now = time.monotonic()
        owner = False

        with self._lock:
            self._prune_locked(now)
            cached = self._values.get(key)
            if cached and cached.expires_at > now:
                return cached.value

            future = self._inflight.get(key)
            if future is None:
                future = concurrent.futures.Future()
                self._inflight[key] = future
                owner = True

        if owner:
            try:
                value = loader()
            except Exception as exc:
                with self._lock:
                    pending = self._inflight.pop(key, None)
                if pending is not None and not pending.done():
                    pending.set_exception(exc)
                raise

            size_bytes = max(0, self._size_estimator(value))
            expires_at = time.monotonic() + self._ttl_seconds
            with self._lock:
                if size_bytes <= self._max_bytes:
                    previous = self._values.pop(key, None)
                    if previous is not None:
                        self._total_size_bytes = max(
                            0,
                            self._total_size_bytes - previous.size_bytes,
                        )
                    self._values[key] = _CacheRecord(
                        value=value,
                        expires_at=expires_at,
                        size_bytes=size_bytes,
                    )
                    self._total_size_bytes += size_bytes
                pending = self._inflight.pop(key, None)
                self._prune_locked(time.monotonic())
            if pending is not None and not pending.done():
                pending.set_result(value)
            return value

        return future.result()

    def _prune_locked(self, now: float) -> None:
        expired = [
            key for key, record in self._values.items() if record.expires_at <= now
        ]
        for key in expired:
            record = self._values.pop(key, None)
            if record is not None:
                self._total_size_bytes = max(
                    0, self._total_size_bytes - record.size_bytes
                )
        if (
            len(self._values) <= self._max_items
            and self._total_size_bytes <= self._max_bytes
        ):
            return
        overflow_items = max(0, len(self._values) - self._max_items)
        oldest = sorted(
            self._values.items(),
            key=lambda item: item[1].expires_at,
        )
        while oldest and (
            overflow_items > 0 or self._total_size_bytes > self._max_bytes
        ):
            key, record = oldest.pop(0)
            removed = self._values.pop(key, None)
            if removed is None:
                continue
            overflow_items = max(0, overflow_items - 1)
            self._total_size_bytes = max(0, self._total_size_bytes - record.size_bytes)
            if (
                len(self._values) <= self._max_items
                and self._total_size_bytes <= self._max_bytes
            ):
                break

    def reconfigure(self, *, max_bytes: Optional[int] = None) -> None:
        """Update cache sizing without discarding live entries."""
        with self._lock:
            if max_bytes is not None and max_bytes > 0:
                self._max_bytes = max_bytes
            self._prune_locked(time.monotonic())


def _estimate_log_entries_size(value: object) -> int:
    """Estimate cache size for a sequence of LogEntry values."""
    if not isinstance(value, tuple):
        return 0
    total = 0
    for entry in value:
        if not isinstance(entry, LogEntry):
            continue
        total += (
            len(entry.timestamp)
            + len(entry.container)
            + len(entry.level)
            + len(entry.message)
            + 160
        )
    return total


def _estimate_label_cache_size(value: object) -> int:
    """Estimate cache size for filesystem-discovered label tuples."""
    if not isinstance(value, tuple) or len(value) != 2:
        return 0
    labels, label_key = value
    if not isinstance(labels, tuple):
        return 0
    total = len(label_key) + 64
    for label in labels:
        total += len(label) + 48
    return total


_LOG_RESULT_CACHE = _InMemoryTTLCache(
    ttl_seconds=_LOG_RESULT_CACHE_TTL_SECONDS,
    max_items=_CACHE_MAX_ITEMS,
    max_bytes=_DEFAULT_LOG_CACHE_MAX_BYTES,
    size_estimator=_estimate_log_entries_size,
)
_INTERNAL_LABELS_CACHE = _InMemoryTTLCache(
    ttl_seconds=_LABEL_CACHE_TTL_SECONDS,
    max_items=_CACHE_MAX_ITEMS,
    max_bytes=_DEFAULT_LABEL_CACHE_MAX_BYTES,
    size_estimator=_estimate_label_cache_size,
)


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


def _chunks(values: Sequence[str], chunk_size: int) -> List[Tuple[str, ...]]:
    """Split a sequence into fixed-size tuples."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [
        tuple(values[index : index + chunk_size])
        for index in range(0, len(values), chunk_size)
    ]


def _escape_logql_string(value: str) -> str:
    """Escape a string for safe inclusion inside a LogQL double-quoted literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _append_text_filter(query: str, text_query: Optional[str]) -> str:
    """Append a case-insensitive literal text filter to a LogQL query."""
    if not text_query:
        return query
    pattern = f"(?i){re.escape(text_query)}"
    return f'{query} |~ "{_escape_logql_string(pattern)}"'


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
    #   "2026-02-02 11:01:49,631 DEBUG [... "
    #   "[INFO] some message"
    #   "... INFO  [... "
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


_TRACEBACK_FRAME_PREFIXES = (
    "during handling of the above exception",
    'file "',
)

_EXCEPTION_LINE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.]*(?:Error|Exception|Warning|Interrupt|Failure|Refused|NotFound)s?:"
)


def _is_traceback_continuation(message: str) -> bool:
    """Return True for traceback frame/continuation lines (not the start or exception line)."""
    if not message:
        return False
    lowered = message.strip().lower()
    return lowered.startswith(_TRACEBACK_FRAME_PREFIXES)


def _is_django_template_lookup_noise(message: str) -> bool:
    """Return True for Django template lookup diagnostics that are not runtime failures."""
    if not message:
        return False
    lowered = message.strip().lower()
    if "django.template.base.variabledoesnotexist:" not in lowered:
        return False
    if "failed lookup for key" not in lowered:
        return False
    return True


def _is_redis_bloom_info(message: str) -> bool:
    """Return True for RedisBloom informational lines containing bf-error-rate."""
    if not message:
        return False
    lowered = message.lower()
    return "<bf>" in lowered and "bf-error-rate" in lowered


def _infer_level_from_message(message: str) -> str:
    """Infer a severity when stream labels do not provide a trusted level."""
    if not message:
        return "info"

    if _is_redis_bloom_info(message):
        return "info"

    if _is_django_template_lookup_noise(message):
        return "debug"

    if _is_traceback_continuation(message):
        return "debug"

    # Exception class lines (e.g., "KeyError: ...", "ValueError: ...") are errors
    stripped = message.strip()
    if _EXCEPTION_LINE_RE.match(stripped):
        return "error"

    lowered = message.lower()

    fatal_patterns = (r"\b(fatal|panic|critical)\b",)
    for pattern in fatal_patterns:
        if re.search(pattern, lowered):
            return "fatal"

    error_patterns = (
        r"\b(error|exception|failed|failure|cannot|unable|denied|invalid|traceback)\b",
    )
    for pattern in error_patterns:
        if re.search(pattern, lowered):
            return "error"

    warning_patterns = (r"\b(warn|warning|deprecated|retry|timed?\s*out|timeout)\b",)
    for pattern in warning_patterns:
        if re.search(pattern, lowered):
            return "warn"

    debug_patterns = (r"\b(debug|trace)\b",)
    for pattern in debug_patterns:
        if re.search(pattern, lowered):
            return "debug"

    return "info"


def _normalize_level(stream_level: str, message: str) -> str:
    """Normalize Loki stream level labels to canonical UI values."""
    aliases = {
        "trace": "debug",
        "debug": "debug",
        "info": "info",
        "notice": "info",
        "log": "info",
        "warn": "warn",
        "warning": "warn",
        "error": "error",
        "err": "error",
        "severe": "error",
        "fatal": "fatal",
        "critical": "fatal",
        "panic": "fatal",
    }
    trusted_level = aliases.get((stream_level or "").strip().lower())

    # Trust explicit stream label first if it's a specific level (not just generic info)
    if trusted_level and trusted_level != "info":
        return trusted_level

    parsed = _parse_level_from_message(message)
    if parsed:
        return parsed

    if trusted_level:
        return trusted_level

    return _infer_level_from_message(message)


def _execute_loki_query(
    config: LogConfig,
    query: str,
    lookback_seconds: int,
    max_entries: int,
    since_ns: Optional[int] = None,
) -> dict:
    """Execute a single Loki query_range request and return the parsed JSON payload."""
    end_time = dt.datetime.now(tz=dt.timezone.utc)
    start_time = end_time - dt.timedelta(seconds=lookback_seconds)
    start_ns = int(start_time.timestamp() * 1e9)
    end_ns = int(end_time.timestamp() * 1e9)
    if since_ns is not None:
        start_ns = max(start_ns, since_ns + 1)
    params = urllib.parse.urlencode(
        {
            "query": query,
            "direction": "backward",
            "limit": max_entries,
            "start": str(start_ns),
            "end": str(end_ns),
        }
    )
    base_parsed = urllib.parse.urlsplit(str(config.loki_url or "").strip())
    if base_parsed.scheme not in {"http", "https"} or not base_parsed.netloc:
        raise RuntimeError("Invalid Loki URL (SSRF protection)")
    if base_parsed.username or base_parsed.password or base_parsed.fragment:
        raise RuntimeError("Invalid Loki URL (SSRF protection)")
    url = urllib.parse.urlunsplit(
        (
            base_parsed.scheme,
            base_parsed.netloc,
            f"{base_parsed.path.rstrip('/')}/loki/api/v1/query_range",
            params,
            "",
        )
    )
    try:
        response = requests.get(url, timeout=config.timeout_seconds)
    except (requests.Timeout, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"Loki request timed out: {exc}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Loki request failed for {sanitize_url_for_logging(url)}: {sanitize_log_value(exc)}"
        ) from exc

    if response.status_code >= 400:
        snippet = response.text[:800]
        raise RuntimeError(f"Loki HTTP error {response.status_code}: {snippet}")

    raw = response.content
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        snippet = raw[:800].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Loki returned non-JSON response (status {response.status_code}): {snippet}"
        ) from exc


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
            level = _normalize_level(stream_level, message)
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
    since_ns: Optional[int] = None,
    text_query: Optional[str] = None,
) -> List[LogEntry]:
    """Fetch logs from Loki for the selected containers and time window."""
    _LOG_RESULT_CACHE.reconfigure(max_bytes=config.cache_max_bytes)
    cache_key = _build_logs_cache_key(
        config,
        containers,
        lookback_seconds,
        max_entries,
        internal_files=internal_files,
        since_ns=since_ns,
        text_query=text_query,
    )
    cached_entries = cast(
        tuple[LogEntry, ...],
        _LOG_RESULT_CACHE.get_or_load(
            cache_key,
            lambda: tuple(
                _fetch_loki_logs_uncached(
                    config,
                    containers,
                    lookback_seconds,
                    max_entries,
                    internal_files=internal_files,
                    since_ns=since_ns,
                    text_query=text_query,
                )
            ),
        ),
    )
    return list(cached_entries)


def _build_docker_query(container: str) -> str:
    """Build a Loki selector for a Docker container stream."""
    if container in {"omeroserver", "omeroweb"}:
        return f'{{compose_service="{container}", container_id=~".+"}}'
    return f'{{compose_service="{container}"}}'


def _prepare_query_jobs(
    containers: List[str],
    internal_files: Optional[Dict[str, set[str]]] = None,
    text_query: Optional[str] = None,
) -> List[_QueryJob]:
    """Build the minimal set of Loki queries required for the request."""
    docker_containers = [c for c in containers if not c.endswith("_internal")]
    internal_services = [c for c in containers if c.endswith("_internal")]
    jobs: List[_QueryJob] = []

    for container in docker_containers:
        jobs.append(
            _QueryJob(
                query=_append_text_filter(_build_docker_query(container), text_query),
                source_type="docker",
                source_name=container,
            )
        )

    for service in internal_services:
        selected_files = sorted((internal_files or {}).get(service, set()))
        if selected_files:
            for batch in _chunks(selected_files, _INTERNAL_FILE_QUERY_BATCH_SIZE):
                jobs.append(
                    _QueryJob(
                        query=_append_text_filter(
                            _build_internal_files_query(
                                service,
                                batch,
                                label_key="filepath",
                            ),
                            text_query,
                        ),
                        source_type="internal_batch",
                        source_name=service,
                        selected_files=batch,
                    )
                )
            continue

        normalized = _normalize_internal_service(service)
        jobs.append(
            _QueryJob(
                query=_append_text_filter(
                    f'{{compose_service="{normalized}", log_type="internal"}}',
                    text_query,
                ),
                source_type="internal_all",
                source_name=service,
            )
        )

    return jobs


def _execute_query_job(
    config: LogConfig,
    job: _QueryJob,
    lookback_seconds: int,
    max_entries: int,
    since_ns: Optional[int],
) -> Tuple[_QueryJob, List[LogEntry]]:
    """Run a single Loki query job and parse the payload."""
    payload = _execute_loki_query(
        config,
        job.query,
        lookback_seconds,
        max_entries,
        since_ns=since_ns,
    )
    return job, _parse_entries_from_payload(payload)


def _filter_internal_batch_entries(
    service: str,
    selected_files: Sequence[str],
    entries: List[LogEntry],
) -> List[LogEntry]:
    """Keep only entries that belong to the requested internal files."""
    selected = set(selected_files)
    filtered: List[LogEntry] = []
    for entry in entries:
        parsed = _split_internal_container(entry.container)
        if not parsed:
            continue
        entry_service, entry_filename = parsed
        if entry_service == service and entry_filename in selected:
            filtered.append(entry)
    return filtered


def _fetch_loki_logs_uncached(
    config: LogConfig,
    containers: List[str],
    lookback_seconds: int,
    max_entries: int,
    internal_files: Optional[Dict[str, set[str]]] = None,
    since_ns: Optional[int] = None,
    text_query: Optional[str] = None,
) -> List[LogEntry]:
    """Fetch logs without using the process-local cache."""
    jobs = _prepare_query_jobs(
        containers,
        internal_files=internal_files,
        text_query=text_query,
    )
    logger.debug(
        "fetch_loki_logs called: jobs=%d, lookback=%d, max=%d, since_ns=%s, text_query=%r",
        len(jobs),
        lookback_seconds,
        max_entries,
        since_ns,
        text_query,
    )
    if not jobs:
        return []

    all_entries: List[LogEntry] = []
    internal_entries_by_service: Dict[str, List[LogEntry]] = {}
    worker_count = max(1, min(len(jobs), _MAX_PARALLEL_LOKI_QUERIES))

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_job = {
            executor.submit(
                _execute_query_job,
                config,
                job,
                lookback_seconds,
                max_entries,
                since_ns,
            ): job
            for job in jobs
        }

        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            try:
                _resolved_job, entries = future.result()
            except Exception as exc:
                if job.source_type == "internal_batch" and job.selected_files:
                    logger.warning(
                        "Internal log query failed for %s/%s: %s",
                        job.source_name,
                        ",".join(job.selected_files),
                        exc,
                    )
                else:
                    logger.warning(
                        "%s log query failed for %s: %s",
                        "Internal"
                        if job.source_type.startswith("internal")
                        else "Docker",
                        job.source_name,
                        exc,
                    )
                continue

            if job.source_type == "docker":
                logger.debug(
                    "Docker query for %s: got %d entries",
                    job.source_name,
                    len(entries),
                )
                all_entries.extend(entries)
                continue

            if job.source_type == "internal_batch":
                entries = _filter_internal_batch_entries(
                    job.source_name,
                    job.selected_files,
                    entries,
                )

            logger.debug(
                "Internal query for %s (%s): got %d entries",
                job.source_name,
                job.source_type,
                len(entries),
            )
            internal_entries_by_service.setdefault(job.source_name, []).extend(entries)

    for service, service_entries in internal_entries_by_service.items():
        if len(service_entries) > max_entries:
            service_entries.sort(key=_entry_sort_key, reverse=True)
            service_entries = service_entries[:max_entries]
        all_entries.extend(service_entries)
        logger.debug(
            "Internal query aggregate for %s: returning %d entries",
            service,
            len(service_entries),
        )

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
    # LogQL string parsing consumes backslashes before the regex engine sees
    # them, so regex escapes must be doubled to survive into the matcher.
    escaped = re.escape(filename).replace("\\", "\\\\")
    return f'{{compose_service="{normalized}", log_type="internal", {label_key}=~"(^|.*/){escaped}$"}}'


def _build_internal_files_query(
    service: str, filenames: Sequence[str], label_key: str = "filepath"
) -> str:
    """Build a Loki query that matches any of the selected internal log files."""
    if not filenames:
        raise ValueError("At least one filename is required for an internal log query.")
    normalized = _normalize_internal_service(service)
    escaped_parts = [
        re.escape(filename).replace("\\", "\\\\") for filename in sorted(set(filenames))
    ]
    pattern = "|".join(escaped_parts)
    return (
        f'{{compose_service="{normalized}", log_type="internal", '
        f'{label_key}=~"(^|.*/)({pattern})$"}}'
    )


def _discover_internal_log_labels_from_filesystem(
    compose_service: str,
) -> Optional[Tuple[List[str], str]]:
    """Discover internal log filenames from the locally mounted log directories."""
    normalized = _normalize_internal_service(compose_service)
    patterns = _INTERNAL_LOG_GLOB_PATTERNS.get(normalized)
    if not patterns:
        return None

    filenames: set[str] = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                filenames.add(os.path.basename(path))
    return sorted(filenames), "filepath"


def _build_logs_cache_key(
    config: LogConfig,
    containers: List[str],
    lookback_seconds: int,
    max_entries: int,
    internal_files: Optional[Dict[str, set[str]]] = None,
    since_ns: Optional[int] = None,
    text_query: Optional[str] = None,
) -> str:
    """Build a stable cache key for log result caching."""
    normalized_internal = tuple(
        (service, tuple(sorted(files)))
        for service, files in sorted((internal_files or {}).items())
        if files
    )
    raw = json.dumps(
        {
            "loki_url": config.loki_url,
            "containers": sorted(containers),
            "lookback_seconds": lookback_seconds,
            "max_entries": max_entries,
            "internal_files": normalized_internal,
            "since_ns": since_ns,
            "text_query": text_query or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    del config
    cache_key = f"internal-labels:{_normalize_internal_service(compose_service)}"
    cached = cast(
        tuple[tuple[str, ...], str],
        _INTERNAL_LABELS_CACHE.get_or_load(
            cache_key,
            lambda: _fetch_internal_log_labels_uncached(compose_service),
        ),
    )
    labels, label_key = cached
    return list(labels), label_key


def _fetch_internal_log_labels_uncached(
    compose_service: str,
) -> Tuple[Tuple[str, ...], str]:
    """Discover internal log filenames from the mounted filesystem."""
    discovered = _discover_internal_log_labels_from_filesystem(compose_service)
    if discovered is None:
        return tuple(), "filepath"
    labels, label_key = discovered
    normalized = _normalize_internal_service(compose_service)
    logger.debug(
        "fetch_internal_log_labels: found %d files for %s via filesystem: %s",
        len(labels),
        compose_service,
        labels[:5],
    )
    if not labels:
        logger.debug(
            "fetch_internal_log_labels: no files discovered for %s (normalized=%s)",
            compose_service,
            normalized,
        )
    return tuple(labels), label_key


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
