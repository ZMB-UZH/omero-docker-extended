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
    #   "2026-02-02 11:01:49,631 DEBUG [...
    #   "[INFO] some message"
    #   "... INFO  [...
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

_TRACEBACK_CONTINUATION_PREFIXES = (
    "traceback (most recent call last)",
    "during handling of the above exception",
    'file "',
)

_EXCEPTION_LINE_RE = re.compile(
    r'^[A-Za-z][A-Za-z0-9_.]*(?:Error|Exception|Warning|Interrupt|Failure|Refused|NotFound)s?:'
)

def _is_traceback_continuation(message: str) -> bool:
    """Return True when the message is a traceback continuation line."""
    if not message:
        return False
    
    stripped = message.strip()
    lowered = stripped.lower()
    
    if lowered.startswith(_TRACEBACK_CONTINUATION_PREFIXES):
        return True
    
    # Generic Python exception line: SomeErrorClass: message
    if _EXCEPTION_LINE_RE.match(stripped):
        return True
        
    return False


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

    if _is_traceback_continuation(message):
        return "debug"

    if _is_django_template_lookup_noise(message):
        return "debug"

    lowered = message.lower()

    if "traceback (most recent call last):" in lowered:
        return "fatal"

    fatal_patterns = (r"\b(fatal|panic|critical)\b",)
    for pattern in fatal_patterns:
        if re.search(pattern, lowered):
            return "fatal"

    error_patterns = (
        r"\b(error|exception|failed|failure|cannot|unable|denied|invalid)\b",
    )
    for pattern in error_patterns:
        if re.search(pattern, lowered):
            return "error"

    warning_patterns = (
        r"\b(warn|warning|deprecated|retry|timed?\s*out|timeout)\b",
    )
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
    
    # FIX: Validate URL against config to prevent SSRF (CodeQL #91)
    base_parsed = urllib.parse.urlparse(config.loki_url)
    url_parsed = urllib.parse.urlparse(url)
    if (url_parsed.scheme != base_parsed.scheme or
            url_parsed.netloc != base_parsed.netloc or
            not url_parsed.path.startswith(base_parsed.path)):
        raise ValueError("Invalid Loki URL configuration")

    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.URLError as e:
        logger.error(f"Loki query failed: {e}")
        return {}

def fetch_loki_logs(
    config: LogConfig,
    containers: List[str],
    lookback_seconds: int = 3600,
    max_entries: int = 5000,
) -> List[LogEntry]:
    """Fetch logs from Loki for the given containers."""
    if not containers:
        return []

    # UI requests Docker and internal sources. We handle them via compose_service.
    services = set()
    for c in containers:
        internal_split = _split_internal_container(c)
        if internal_split:
            services.add(internal_split[0])
        else:
            services.add(c)
            
    query = build_loki_query(list(services))
    
    data = _execute_loki_query(config, query, lookback_seconds, max_entries)
    
    results = []
    if "data" in data and "result" in data["data"]:
        for stream_data in data["data"]["result"]:
            stream_labels = stream_data.get("stream", {})
            container = stream_labels.get("compose_service", "unknown")
            log_type = stream_labels.get("log_type", "docker")
            
            # Reconstruct the container name as UI expects it
            if log_type == "internal":
                filename = stream_labels.get("filename", "")
                if filename:
                    # Loki filename is absolute (e.g. /opt/omero/server/var/log/Blitz-0.log)
                    basename = os.path.basename(filename)
                    container = f"{container}_internal/{basename}"
                else:
                    container = f"{container}_internal"
            
            stream_level = stream_labels.get("level", "")
            
            for values in stream_data.get("values", []):
                if len(values) >= 2:
                    ts = _format_timestamp(values[0])
                    msg = values[1]
                    level = _normalize_level(stream_level, msg)
                    results.append(LogEntry(ts, container, level, msg))
                    
    # Sort by timestamp descending
    results.sort(key=lambda x: x.timestamp, reverse=True)
    return results[:max_entries]
