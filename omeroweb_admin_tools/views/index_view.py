import json
import logging
import os
import shutil
from urllib.parse import urlparse
from urllib.parse import urlunparse
from urllib.parse import urlencode
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List

import urllib.error
import urllib.request

from django.http import JsonResponse
from django.shortcuts import render
from omeroweb.decorators import login_required

from ..config import optional_log_config
from ..services.log_query import (
    fetch_loki_logs,
    fetch_internal_log_labels,
    serialize_entries,
)
from .utils import current_username

logger = logging.getLogger(__name__)
LOG_TABLE_ROW_CAP = 5000


def _to_int_env(name: str, default: int) -> int:
    """Return an integer environment variable using the provided default on errors."""
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer for %s=%s; using %d", name, raw_value, default)
        return default


def _probe_http_url(url: str, timeout_seconds: float = 2.5) -> Dict[str, object]:
    """Probe an HTTP endpoint and return availability diagnostics."""
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 0) or 0)
            return {"ok": 200 <= status_code < 400, "status": status_code, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": int(exc.code), "error": f"HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "error": str(exc.reason)}


def _replace_host(url: str, hostname: str) -> str:
    """Return URL with host replaced while preserving scheme, port, and path."""
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    port = parsed.port
    netloc = f"{hostname}:{port}" if port else hostname
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _unwrap_rtype_value(value, default=None):
    """Extract primitive values from OMERO rtypes and similar wrappers."""
    if value is None:
        return default
    if hasattr(value, "val"):
        return value.val
    if hasattr(value, "getValue"):
        return value.getValue()
    return value


def _require_root_user(request, conn):
    username = current_username(request, conn)
    if username != "root":
        return JsonResponse(
            {"error": "Only root user can access admin tools data."}, status=403
        )
    return None


@login_required()
def index(request, conn=None, url=None, **kwargs):
    """Render the Admin tools landing page."""
    return render(
        request,
        "omeroweb_admin_tools/index.html",
        {},
    )


def _build_log_sources() -> List[Dict[str, str]]:
    """Return ordered Docker log sources for the UI."""
    return [
        {
            "key": "omeroserver",
            "label": "OMERO.server",
            "container": "omeroserver",
        },
        {
            "key": "omeroweb",
            "label": "OMERO.web",
            "container": "omeroweb",
        },
        {
            "key": "database",
            "label": "OMERO database",
            "container": "database",
        },
        {
            "key": "database_plugin",
            "label": "Plugin database",
            "container": "database_plugin",
        },
        {
            "key": "redis",
            "label": "Redis",
            "container": "redis",
        },
    ]


@login_required()
def logs_view(request, conn=None, url=None, **kwargs):
    """Render the logs view."""
    log_config = optional_log_config()
    return render(
        request,
        "omeroweb_admin_tools/logs.html",
        {
            "log_config": json.dumps(asdict(log_config)) if log_config else "null",
            "log_sources": _build_log_sources(),
            "table_row_cap": LOG_TABLE_ROW_CAP,
        },
    )


@login_required()
def logs_data(request, conn=None, url=None, **kwargs):
    """Serve log entries as JSON from the Loki backend."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    log_config = optional_log_config()
    if log_config is None:
        return JsonResponse(
            {"error": "ADMIN_TOOLS_LOKI_URL is not configured."},
            status=503,
        )
    containers = request.GET.getlist("container")
    internal_files_raw = request.GET.getlist("internal_file")
    if not containers:
        return JsonResponse({"entries": []})
    try:
        lookback_seconds = int(request.GET.get("lookback", log_config.lookback_seconds))
        max_entries = int(request.GET.get("limit", log_config.max_entries))
    except ValueError:
        return JsonResponse({"error": "Invalid lookback or limit value."}, status=400)
    query = request.GET.get("query", "").strip()
    level = request.GET.get("level", "").strip().lower()
    if level and level not in {"debug", "info", "warn", "error", "fatal"}:
        return JsonResponse({"error": "Invalid log level."}, status=400)
    try:
        internal_files = {}
        for value in internal_files_raw:
            if not value or "/" not in value:
                continue
            service, filename = value.split("/", 1)
            if service not in ("omeroserver_internal", "omeroweb_internal"):
                continue
            if filename:
                internal_files.setdefault(service, set()).add(filename)
        entries = fetch_loki_logs(
            log_config,
            containers,
            lookback_seconds,
            max_entries,
            internal_files=internal_files,
        )
    except RuntimeError as exc:  # pragma: no cover - network errors
        return JsonResponse(
            {"error": f"Failed to fetch logs: {exc}"},
            status=502,
        )
    if level:
        entries = [entry for entry in entries if entry.level == level]
    if query:
        needle = query.lower()
        entries = [
            entry
            for entry in entries
            if needle in entry.message.lower()
            or needle in entry.container.lower()
            or needle in entry.level.lower()
        ]
    return JsonResponse({"entries": serialize_entries(entries)})


@login_required()
def root_status(request, conn=None, url=None, **kwargs):
    """Return whether the current user is root."""
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})


@login_required()
def internal_log_labels(request, conn=None, url=None, **kwargs):
    """Return available filenames for an internal log compose_service."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    log_config = optional_log_config()
    if log_config is None:
        return JsonResponse(
            {"error": "ADMIN_TOOLS_LOKI_URL is not configured."},
            status=503,
        )
    service = request.GET.get("service", "")
    if service not in ("omeroserver_internal", "omeroweb_internal"):
        return JsonResponse(
            {"error": "Invalid service parameter."},
            status=400,
        )
    try:
        labels, _label_key = fetch_internal_log_labels(log_config, service)
    except Exception:
        logger.exception("Failed to fetch internal log labels for service=%s", service)
        labels = []
    return JsonResponse({"service": service, "labels": labels})


@login_required()
def resource_monitoring_view(request, conn=None, url=None, **kwargs):
    """Render resource monitoring dashboard."""
    return render(request, "omeroweb_admin_tools/resource_monitoring.html", {})


@login_required()
def resource_monitoring_data(request, conn=None, url=None, **kwargs):
    """Return monitoring endpoint URLs for Grafana and Prometheus dashboards."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error

    grafana_base_url = os.environ.get("ADMIN_TOOLS_GRAFANA_URL", "http://grafana:3000")
    prometheus_base_url = os.environ.get(
        "ADMIN_TOOLS_PROMETHEUS_URL", "http://prometheus:9090"
    )

    request_host = request.get_host().split(":", 1)[0]
    grafana_public_port = _to_int_env("ADMIN_TOOLS_GRAFANA_PUBLIC_PORT", 3001)
    prometheus_public_port = _to_int_env("ADMIN_TOOLS_PROMETHEUS_PUBLIC_PORT", 9090)
    grafana_default_public = f"{request.scheme}://{request_host}:{grafana_public_port}"
    prometheus_default_public = (
        f"{request.scheme}://{request_host}:{prometheus_public_port}"
    )

    grafana_public_url = os.environ.get("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "").strip()
    prometheus_public_url = os.environ.get(
        "ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL", ""
    ).strip()

    if not grafana_public_url:
        grafana_public_url = _replace_host(grafana_base_url, request_host)
    if "grafana" in grafana_public_url or "localhost" in grafana_public_url:
        grafana_public_url = grafana_default_public

    if not prometheus_public_url:
        prometheus_public_url = _replace_host(prometheus_base_url, request_host)
    if "prometheus" in prometheus_public_url or "localhost" in prometheus_public_url:
        prometheus_public_url = prometheus_default_public
    dashboard_uid = os.environ.get(
        "ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "omero-infrastructure"
    )
    dashboard_slug = os.environ.get(
        "ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "omero-infrastructure"
    )

    dashboard_query = urlencode(
        {
            "orgId": "1",
            "refresh": "10s",
            "kiosk": "tv",
            "theme": "light",
        }
    )
    dashboard_url = f"{grafana_public_url.rstrip('/')}/d/{dashboard_uid}/{dashboard_slug}?{dashboard_query}"
    prometheus_targets_url = f"{prometheus_public_url.rstrip('/')}/targets"

    grafana_probe = _probe_http_url(f"{grafana_base_url.rstrip('/')}/api/health")
    prometheus_probe = _probe_http_url(f"{prometheus_base_url.rstrip('/')}/-/ready")

    return JsonResponse(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "grafana": {
                "base_url": grafana_base_url,
                "dashboard_url": dashboard_url,
                "probe": grafana_probe,
            },
            "prometheus": {
                "base_url": prometheus_base_url,
                "targets_url": prometheus_targets_url,
                "probe": prometheus_probe,
            },
        }
    )


@login_required()
def storage_view(request, conn=None, url=None, **kwargs):
    """Render storage capacity distribution page."""
    return render(request, "omeroweb_admin_tools/storage.html", {})


@login_required()
def storage_data(request, conn=None, url=None, **kwargs):
    """Return size distribution by OMERO user and group using OriginalFile sizes."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error

    query = """
        select e.id, e.omeName, g.id, g.name, sum(file.size)
        from OriginalFile file
        join file.details.owner e
        join file.details.group g
        group by e.id, e.omeName, g.id, g.name
    """
    per_user_group = []
    totals_by_user: Dict[str, int] = {}
    totals_by_group: Dict[str, int] = {}
    total_size = 0

    try:
        rows = conn.getQueryService().projection(query, None, conn.SERVICE_OPTS)
        for row in rows:
            user_name = str(_unwrap_rtype_value(row[1], "unknown") or "unknown")
            group_name = str(_unwrap_rtype_value(row[3], "unknown") or "unknown")
            size_raw = _unwrap_rtype_value(row[4], 0)
            size_value = int(size_raw or 0)
            per_user_group.append(
                {
                    "username": user_name,
                    "group": group_name,
                    "bytes": size_value,
                }
            )
            totals_by_user[user_name] = totals_by_user.get(user_name, 0) + size_value
            totals_by_group[group_name] = (
                totals_by_group.get(group_name, 0) + size_value
            )
            total_size += size_value
    except Exception as exc:
        logger.exception("Failed to compute storage distribution")
        return JsonResponse({"error": f"Storage query failed: {exc}"}, status=500)

    data_root = os.environ.get("OMERO_DATA_DIR", "/OMERO")
    data_total = data_used = data_free = None
    try:
        data_total, data_used, data_free = shutil.disk_usage(data_root)
    except Exception:
        logger.warning("Could not read disk usage for data root %s", data_root)

    return JsonResponse(
        {
            "totals": {
                "omero_binary_bytes": total_size,
                "data_root": data_root,
                "data_root_total_bytes": data_total,
                "data_root_used_bytes": data_used,
                "data_root_free_bytes": data_free,
            },
            "by_user": [
                {"username": username, "bytes": size}
                for username, size in sorted(
                    totals_by_user.items(), key=lambda item: item[1], reverse=True
                )
            ],
            "by_group": [
                {"group": groupname, "bytes": size}
                for groupname, size in sorted(
                    totals_by_group.items(), key=lambda item: item[1], reverse=True
                )
            ],
            "by_user_group": sorted(
                per_user_group, key=lambda item: item["bytes"], reverse=True
            ),
        }
    )
