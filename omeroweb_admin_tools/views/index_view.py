import json
from dataclasses import asdict
from typing import Dict, List

from django.http import JsonResponse
from django.shortcuts import render
from omeroweb.decorators import login_required

from ..config import optional_log_config
from ..services.log_query import fetch_loki_logs, fetch_internal_log_labels, serialize_entries
from .utils import current_username


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
            "label": "Omero server",
            "container": "omeroserver",
        },
        {
            "key": "omeroweb",
            "label": "Omero web",
            "container": "omeroweb",
        },
        {
            "key": "database",
            "label": "Database",
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


def _build_omero_log_sources() -> List[Dict[str, str]]:
    """Return ordered OMERO internal log sources for the UI."""
    return [
        {
            "key": "omeroserver_internal",
            "label": "Omero server",
            "container": "omeroserver_internal",
        },
        {
            "key": "omeroweb_internal",
            "label": "Omero web",
            "container": "omeroweb_internal",
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
        },
    )


@login_required()
def logs_data(request, conn=None, url=None, **kwargs):
    """Serve log entries as JSON from the Loki backend."""
    username = current_username(request, conn)
    if username != "root":
        return JsonResponse(
            {"error": "Only root user can access logs."},
            status=403,
        )
    log_config = optional_log_config()
    if log_config is None:
        return JsonResponse(
            {"error": "ADMIN_TOOLS_LOKI_URL is not configured."},
            status=503,
        )
    containers = request.GET.getlist("container")
    if not containers:
        return JsonResponse({"entries": []})
    try:
        lookback_seconds = int(request.GET.get("lookback", log_config.lookback_seconds))
        max_entries = int(request.GET.get("limit", log_config.max_entries))
    except ValueError:
        return JsonResponse({"error": "Invalid lookback or limit value."}, status=400)
    try:
        entries = fetch_loki_logs(log_config, containers, lookback_seconds, max_entries)
    except RuntimeError as exc:  # pragma: no cover - network errors
        return JsonResponse(
            {"error": f"Failed to fetch logs: {exc}"},
            status=502,
        )
    return JsonResponse({"entries": serialize_entries(entries)})


@login_required()
def root_status(request, conn=None, url=None, **kwargs):
    """Return whether the current user is root."""
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})


@login_required()
def internal_log_labels(request, conn=None, url=None, **kwargs):
    """Return available filenames for an internal log compose_service."""
    username = current_username(request, conn)
    if username != "root":
        return JsonResponse(
            {"error": "Only root user can access logs."},
            status=403,
        )
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
        labels = fetch_internal_log_labels(log_config, service)
    except RuntimeError:
        labels = []
    return JsonResponse({"service": service, "labels": labels})
