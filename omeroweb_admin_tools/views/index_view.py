import json
import logging
import os
import re
import shutil
import socket
import subprocess
import traceback
import uuid
from http.client import HTTPConnection
from http.client import HTTPMessage
from urllib.parse import urlparse
from urllib.parse import urlencode
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import urllib.error
import urllib.request

from django.http import JsonResponse
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..config import optional_log_config
from ..services.log_query import (
    fetch_loki_logs,
    fetch_internal_log_labels,
    serialize_entries,
)
from ..services.system_diagnostics import run_diagnostic_script
from ..services.system_diagnostics import serialize_scripts
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


def _proxy_http_request(
    django_request,
    base_url: str,
    path: str,
    query: str = "",
    *,
    proxy_prefix: str = "",
) -> HttpResponse:
    """Proxy an HTTP request to a backend URL and return the response body."""
    target_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if query:
        target_url = f"{target_url}?{query}"

    forwarded_headers = {}
    for header_name in ("Accept", "Content-Type", "User-Agent"):
        value = django_request.headers.get(header_name)
        if value:
            forwarded_headers[header_name] = value

    request = urllib.request.Request(
        target_url,
        data=(
            django_request.body
            if django_request.method in {"POST", "PUT", "PATCH"}
            else None
        ),
        headers=forwarded_headers,
        method=django_request.method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            payload = response.read()
            headers: HTTPMessage = response.headers
            content_type = headers.get("Content-Type", "application/octet-stream")
            if "text/html" in content_type and proxy_prefix:
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    text = payload.decode("latin-1", errors="ignore")
                text = text.replace('href="/', f'href="{proxy_prefix}/')
                text = text.replace("href='/", f"href='{proxy_prefix}/")
                text = text.replace('src="/', f'src="{proxy_prefix}/')
                text = text.replace("src='/", f"src='{proxy_prefix}/")
                text = text.replace('action="/', f'action="{proxy_prefix}/')
                text = text.replace("action='/", f"action='{proxy_prefix}/")
                text = text.replace(base_url.rstrip("/"), proxy_prefix)
                payload = text.encode("utf-8")
            proxied = HttpResponse(
                payload, status=response.status, content_type=content_type
            )
            for header_name in ("Cache-Control", "ETag", "Last-Modified"):
                header_value = headers.get(header_name)
                if header_value:
                    proxied[header_name] = header_value
            location = headers.get("Location")
            if location:
                if location.startswith(base_url.rstrip("/")):
                    proxied["Location"] = location.replace(
                        base_url.rstrip("/"), proxy_prefix, 1
                    )
                elif location.startswith("/") and proxy_prefix:
                    proxied["Location"] = f"{proxy_prefix}{location}"
                else:
                    proxied["Location"] = location
            return proxied
    except urllib.error.HTTPError as exc:
        body = exc.read()
        content_type = exc.headers.get("Content-Type", "text/plain; charset=utf-8")
        return HttpResponse(body, status=int(exc.code), content_type=content_type)
    except urllib.error.URLError as exc:
        return JsonResponse(
            {"error": f"Backend unreachable for {target_url}: {exc.reason}"},
            status=502,
        )


def _is_internal_hostname(hostname: str) -> bool:
    """Return whether hostname points to a local/container-only endpoint."""
    lowered = str(hostname or "").strip().lower()
    return lowered in {"", "localhost", "127.0.0.1", "::1", "grafana", "prometheus"}


def _safe_request_host(request) -> str:
    """Return request host without port, falling back safely when host validation fails."""
    try:
        host_value = request.get_host()
    except Exception as exc:
        logger.warning("Unable to resolve request host from get_host(): %s", exc)
        host_value = (
            request.META.get("HTTP_HOST", "")
            or request.META.get("SERVER_NAME", "")
            or "localhost"
        )
    return str(host_value).split(":", 1)[0].strip() or "localhost"


def _build_public_service_url(
    internal_url: str,
    request_scheme: str,
    request_host: str,
    public_port: int,
) -> str:
    """Build externally reachable service URL from request host and configured public port."""
    parsed = urlparse(internal_url)
    scheme = parsed.scheme or request_scheme
    base_path = parsed.path.rstrip("/")
    host_only = str(request_host or "").strip()
    if host_only.startswith("[") and "]" in host_only:
        normalized_host = host_only
    elif ":" in host_only:
        normalized_host = f"[{host_only}]"
    else:
        normalized_host = host_only
    public_base = f"{scheme}://{normalized_host}:{public_port}"
    if base_path:
        return f"{public_base}{base_path}"
    return public_base


def _unwrap_rtype_value(value, default=None):
    """Extract primitive values from OMERO rtypes and similar wrappers."""
    if value is None:
        return default
    if hasattr(value, "val"):
        return value.val
    if hasattr(value, "getValue"):
        return value.getValue()
    return value


def _safe_full_name(user_obj) -> str:
    """Return "First Last" for an OMERO experimenter-like object."""
    first_name = ""
    last_name = ""
    for getter_name, field_name in (
        ("getFirstName", "firstName"),
        ("getLastName", "lastName"),
    ):
        raw_value = None
        if hasattr(user_obj, getter_name):
            raw_value = _unwrap_rtype_value(getattr(user_obj, getter_name)(), "")
        elif hasattr(user_obj, field_name):
            raw_value = _unwrap_rtype_value(getattr(user_obj, field_name), "")
        if getter_name == "getFirstName":
            first_name = str(raw_value or "").strip()
        else:
            last_name = str(raw_value or "").strip()
    return " ".join(part for part in (first_name, last_name) if part)


def _safe_username(user_obj) -> str:
    """Return username for an OMERO experimenter-like object."""
    if hasattr(user_obj, "getOmeName"):
        return str(_unwrap_rtype_value(user_obj.getOmeName(), "") or "").strip()
    if hasattr(user_obj, "omeName"):
        return str(_unwrap_rtype_value(user_obj.omeName, "") or "").strip()
    return ""


def _safe_group_name(group_obj) -> str:
    """Return name for an OMERO group-like object."""
    if hasattr(group_obj, "getName"):
        return str(_unwrap_rtype_value(group_obj.getName(), "") or "").strip()
    if hasattr(group_obj, "name"):
        return str(_unwrap_rtype_value(group_obj.name, "") or "").strip()
    return ""


def _call_admin_listing(admin_service, method_name, arg_options=None):
    """Call admin-service listing methods with tolerant signatures."""
    if not hasattr(admin_service, method_name):
        return []
    method = getattr(admin_service, method_name)
    argument_options = arg_options or ((), (None,), (False,))
    for args in argument_options:
        try:
            result = method(*args)
            return list(result or [])
        except TypeError:
            continue
    return []


def _safe_object_id(obj):
    """Extract numeric ID for OMERO model-like objects."""
    if obj is None:
        return None
    if hasattr(obj, "getId"):
        value = _unwrap_rtype_value(obj.getId(), None)
    elif hasattr(obj, "id"):
        value = _unwrap_rtype_value(obj.id, None)
    else:
        value = None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _list_all_users_and_groups(conn):
    """Collect all OMERO users and groups to keep zero-usage rows visible."""
    users = {}
    groups = set()
    group_permissions = {}
    groups_by_user = {}
    users_by_group = {}
    try:
        admin_service = conn.getAdminService()
        experimenters = []
        experimenter_groups = []
        for method_name in ("lookupExperimenters", "containedExperimenters"):
            experimenters = _call_admin_listing(admin_service, method_name)
            if experimenters:
                break
        for method_name in ("lookupGroups", "containedGroups"):
            experimenter_groups = _call_admin_listing(admin_service, method_name)
            if experimenter_groups:
                break

        for user in experimenters:
            username = _safe_username(user)
            if username:
                users[username] = _safe_full_name(user)
                groups_by_user.setdefault(username, set())
        for group in experimenter_groups:
            group_name = _safe_group_name(group)
            if group_name:
                groups.add(group_name)
                group_permissions[group_name] = _safe_group_permission_label(group)
                users_by_group.setdefault(group_name, set())

        for user in experimenters:
            user_id = _safe_object_id(user)
            username = _safe_username(user)
            if user_id is None or not username:
                continue
            user_groups = _call_admin_listing(
                admin_service,
                "containedGroups",
                arg_options=(
                    (user_id,),
                    (int(user_id),),
                    (user_id, False),
                    (user_id, None),
                ),
            )
            for group in user_groups:
                group_name = _safe_group_name(group)
                if not group_name:
                    continue
                groups.add(group_name)
                groups_by_user.setdefault(username, set()).add(group_name)
                users_by_group.setdefault(group_name, set()).add(username)
                group_permissions.setdefault(
                    group_name, _safe_group_permission_label(group)
                )

        for group in experimenter_groups:
            group_id = _safe_object_id(group)
            group_name = _safe_group_name(group)
            if group_id is None or not group_name:
                continue
            group_users = _call_admin_listing(
                admin_service,
                "containedExperimenters",
                arg_options=(
                    (group_id,),
                    (int(group_id),),
                    (group_id, False),
                    (group_id, None),
                ),
            )
            for user in group_users:
                username = _safe_username(user)
                if not username:
                    continue
                users.setdefault(username, _safe_full_name(user))
                groups_by_user.setdefault(username, set()).add(group_name)
                users_by_group.setdefault(group_name, set()).add(username)
    except Exception:
        logger.exception(
            "Failed to enumerate all users/groups from OMERO admin service"
        )
    return users, groups, group_permissions, groups_by_user, users_by_group


def _permission_flag(permission_obj, method_name: str) -> bool:
    """Safely read a bool-like permission method from OMERO permissions."""
    if permission_obj is None:
        return False
    method = getattr(permission_obj, method_name, None)
    if not callable(method):
        return False
    try:
        return bool(method())
    except Exception:
        return False


def _safe_group_permission_label(group_obj) -> str:
    """Return a stable group permission name for the storage group view."""
    permission_obj = None
    try:
        details = group_obj.getDetails()
        permission_obj = details.getPermissions() if details is not None else None
    except Exception:
        permission_obj = None

    group_read = _permission_flag(permission_obj, "isGroupRead")
    group_write = _permission_flag(permission_obj, "isGroupWrite")
    group_annotate = _permission_flag(permission_obj, "isGroupAnnotate")
    if group_read and group_write:
        return "Read-write"
    if group_read and group_annotate:
        return "Read-annotate"
    if group_read:
        return "Read-only"

    permission_text = str(permission_obj or "").strip().lower()
    if "read-write" in permission_text or "rwrw" in permission_text:
        return "Read-write"
    if "read-annotate" in permission_text or "rwra" in permission_text:
        return "Read-annotate"
    if "read-only" in permission_text:
        return "Read-only"
    if "private" in permission_text:
        return "Private"
    return "Private"


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


def _load_compose_service_names(compose_file: str = "docker-compose.yml") -> List[str]:
    """Return declared Docker Compose service names from the local compose file."""
    compose_path = os.path.join(os.getcwd(), compose_file)
    if not os.path.exists(compose_path):
        logger.warning("Compose file not found at %s", compose_path)
        return []

    service_names: List[str] = []
    in_services = False
    service_pattern = re.compile(r"^  ([a-zA-Z0-9_-]+):\s*$")

    with open(compose_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith("services:"):
                in_services = True
                continue
            if in_services and line and not line.startswith(" "):
                break
            if not in_services:
                continue
            match = service_pattern.match(line)
            if match:
                service_names.append(match.group(1))

    return service_names


def _prometheus_instant_query(prometheus_base_url: str, expr: str) -> Optional[float]:
    """Execute a Prometheus instant query and return the first numeric value."""
    query = urlencode({"query": expr})
    query_url = f"{prometheus_base_url.rstrip('/')}/api/v1/query?{query}"
    with urllib.request.urlopen(query_url, timeout=5.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    results = payload.get("data", {}).get("result", [])
    if not results:
        return None
    value = results[0].get("value", [])
    if len(value) < 2:
        return None
    return float(value[1])


def _collect_system_metrics(prometheus_base_url: str) -> Dict[str, Optional[float]]:
    """Collect a compact set of host-level metrics for admin overview cards."""
    metrics: Dict[str, Optional[float]] = {
        "cpu_usage_percent": None,
        "memory_usage_percent": None,
        "disk_usage_percent": None,
        "network_receive_bps": None,
        "network_transmit_bps": None,
    }
    expressions = {
        "cpu_usage_percent": '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))',
        "memory_usage_percent": "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))",
        "disk_usage_percent": '100 * (1 - (node_filesystem_avail_bytes{fstype!="tmpfs",mountpoint="/"} / node_filesystem_size_bytes{fstype!="tmpfs",mountpoint="/"}))',
        "network_receive_bps": 'sum(rate(node_network_receive_bytes_total{device!="lo"}[5m]))',
        "network_transmit_bps": 'sum(rate(node_network_transmit_bytes_total{device!="lo"}[5m]))',
    }
    for metric_name, expr in expressions.items():
        try:
            metrics[metric_name] = _prometheus_instant_query(prometheus_base_url, expr)
        except Exception:
            logger.exception("Failed to fetch Prometheus metric %s", metric_name)
    return metrics


def _collect_recently_seen_services(prometheus_base_url: str) -> List[str]:
    """Return compose services that have emitted cAdvisor samples recently."""
    expr = (
        "count by (container_label_com_docker_compose_service) "
        "(max_over_time(container_last_seen"
        '{container_label_com_docker_compose_service!="",image!=""}[5m]))'
    )
    query = urlencode({"query": expr})
    query_url = f"{prometheus_base_url.rstrip('/')}/api/v1/query?{query}"
    with urllib.request.urlopen(query_url, timeout=5.0) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("status") != "success":
        return []

    results = payload.get("data", {}).get("result", [])
    discovered = set()
    for sample in results:
        metric = sample.get("metric", {}) or {}
        service_name = str(
            metric.get("container_label_com_docker_compose_service", "")
        ).strip()
        if service_name:
            discovered.add(service_name)
    return sorted(discovered)


def _docker_compose_json(command: List[str]) -> Optional[object]:
    """Run a docker compose JSON command and return decoded payload."""
    try:
        process = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    stdout = process.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to decode JSON from command: %s", " ".join(command))
        return None


class _UnixSocketHTTPConnection(HTTPConnection):
    """HTTP client connection implementation for Docker Unix sockets."""

    def __init__(self, unix_socket_path: str, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.unix_socket_path = unix_socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_socket_path)


def _docker_api_json(path: str, timeout_seconds: float = 3.0) -> Optional[object]:
    """Query Docker Engine API over /var/run/docker.sock and return JSON payload."""
    docker_socket = os.environ.get("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    if not os.path.exists(docker_socket):
        logger.debug("Docker socket not found at %s", docker_socket)
        return None

    connection = _UnixSocketHTTPConnection(docker_socket, timeout=timeout_seconds)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            logger.debug(
                "Docker API request failed for %s with status %d", path, response.status
            )
            return None
        payload = response.read().decode("utf-8")
        if not payload:
            return None
        return json.loads(payload)
    except PermissionError:
        logger.warning(
            "Permission denied accessing Docker socket at %s. "
            "Ensure the container user is in the docker group "
            "(check group_add GID in docker-compose.yml matches: "
            "stat -c '%%g' /var/run/docker.sock).",
            docker_socket,
        )
        return None
    except (ConnectionError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Docker API request failed for %s: %s", path, exc)
        return None
    finally:
        connection.close()


def _diagnose_docker_health() -> Dict[str, object]:
    """Return diagnostic info about Docker socket access and health data retrieval.

    This is included in the resource monitoring API response to help debug
    cases where container health status is not being reported correctly.
    """
    docker_socket = os.environ.get("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    diag: Dict[str, object] = {
        "socket_path": docker_socket,
        "socket_exists": os.path.exists(docker_socket),
        "socket_readable": os.access(docker_socket, os.R_OK),
        "socket_writable": os.access(docker_socket, os.W_OK),
        "current_user": "",
        "current_uid": -1,
        "current_gids": [],
        "socket_stat": "",
        "api_reachable": False,
        "api_error": "",
        "container_count": 0,
        "containers_with_health": 0,
        "sample_statuses": [],
    }

    # Who we are inside the container
    try:
        diag["current_uid"] = os.getuid()
        diag["current_gids"] = list(os.getgroups())
        import pwd

        try:
            diag["current_user"] = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            diag["current_user"] = f"uid={os.getuid()}"
    except Exception as exc:
        diag["current_user"] = f"error: {exc}"

    # Socket file ownership
    if diag["socket_exists"]:
        try:
            stat_info = os.stat(docker_socket)
            diag["socket_stat"] = (
                f"uid={stat_info.st_uid} gid={stat_info.st_gid} "
                f"mode={oct(stat_info.st_mode)}"
            )
        except Exception as exc:
            diag["socket_stat"] = f"stat error: {exc}"

    # Try the actual API call
    try:
        containers = _docker_api_json("/containers/json?all=1")
        if containers is None:
            diag["api_error"] = "API returned None (connection or permission error)"
        elif not isinstance(containers, list):
            diag["api_error"] = f"unexpected type: {type(containers).__name__}"
        else:
            diag["api_reachable"] = True
            diag["container_count"] = len(containers)
            health_count = 0
            samples = []
            for container in containers[:15]:
                if not isinstance(container, dict):
                    continue
                labels = container.get("Labels", {}) or {}
                service = str(labels.get("com.docker.compose.service", "")).strip()
                status = str(container.get("Status", "")).strip()
                state = str(container.get("State", "")).strip()
                parsed_health = _parse_docker_status_health(status)
                if parsed_health:
                    health_count += 1
                samples.append(
                    {
                        "service": service or "(no label)",
                        "state": state,
                        "status": status,
                        "parsed_health": parsed_health or "(none)",
                    }
                )
            diag["containers_with_health"] = health_count
            diag["sample_statuses"] = samples
    except Exception as exc:
        diag["api_error"] = f"{type(exc).__name__}: {exc}"

    return diag


def _parse_docker_status_health(status: str) -> str:
    """Parse Docker status text and return health state when present."""
    match = re.search(r"\((healthy|unhealthy|starting)\)", str(status or "").lower())
    if match:
        return match.group(1)
    return ""


def _load_compose_health_data() -> Tuple[Dict[str, bool], Dict[str, Dict[str, str]]]:
    """Return compose healthcheck config and runtime state, preferring Docker API.

    Uses the /containers/json list endpoint directly.  The human-readable
    ``Status`` field already contains healthcheck indicators such as
    ``(healthy)``, ``(unhealthy)`` or ``(starting)`` — so individual
    ``/containers/{id}/json`` inspect calls are only made for running
    containers whose Status string does *not* contain a health parenthetical
    (to detect healthchecks that haven't produced a result yet).
    """
    containers = _docker_api_json("/containers/json?all=1")
    if not isinstance(containers, list):
        logger.warning(
            "Docker API container list unavailable; "
            "falling back to CLI for compose health data"
        )
        return _load_compose_healthcheck_config(), _load_compose_runtime_health()

    healthcheck_config: Dict[str, bool] = {}
    runtime_health: Dict[str, Dict[str, str]] = {}

    # Containers that are running but whose Status field has no health
    # parenthetical — we need to inspect these to detect healthchecks
    # that haven't produced a result yet (e.g. still in start_period).
    needs_inspect: List[Tuple[str, str]] = []  # (service_name, container_id)

    for container in containers:
        if not isinstance(container, dict):
            continue
        labels = container.get("Labels", {}) or {}
        if not isinstance(labels, dict):
            continue
        service_name = str(labels.get("com.docker.compose.service", "")).strip()
        if not service_name:
            continue

        state = str(container.get("State", "")).strip().lower()
        status_text = str(container.get("Status", "")).strip()
        health_from_status = _parse_docker_status_health(status_text)

        if health_from_status:
            # Status field has a health indicator → container has a healthcheck.
            healthcheck_config[service_name] = True
            runtime_health[service_name] = {
                "state": state,
                "health": health_from_status,
            }
        else:
            # No health indicator in Status.  Store what we know so far and
            # queue an inspect for running containers (they might have a
            # healthcheck in start_period or without a status yet).
            if service_name not in healthcheck_config:
                healthcheck_config[service_name] = False
            runtime_health[service_name] = {"state": state, "health": ""}
            if state == "running":
                container_id = str(container.get("Id", "")).strip()
                if container_id:
                    needs_inspect.append((service_name, container_id))

    # Inspect only the small set of running containers that lacked a health
    # parenthetical — typically services without a healthcheck at all.
    for service_name, container_id in needs_inspect:
        inspect_payload = _docker_api_json(f"/containers/{container_id}/json")
        if not isinstance(inspect_payload, dict):
            continue

        config_payload = inspect_payload.get("Config", {}) or {}
        healthcheck_payload = config_payload.get("Healthcheck")
        has_healthcheck = (
            isinstance(healthcheck_payload, dict)
            and bool(healthcheck_payload.get("Test"))
            and healthcheck_payload.get("Test") != ["NONE"]
        )
        if has_healthcheck:
            healthcheck_config[service_name] = True
            # Try to read Health.Status from inspect State
            state_payload = inspect_payload.get("State", {}) or {}
            state_health = state_payload.get("Health", {}) or {}
            if isinstance(state_health, dict):
                inspected_health = str(state_health.get("Status", "")).strip().lower()
                if inspected_health in {"healthy", "unhealthy", "starting"}:
                    runtime_health[service_name]["health"] = inspected_health

    return healthcheck_config, runtime_health


def _load_compose_healthcheck_config() -> Dict[str, bool]:
    """Return whether each compose service defines a Docker healthcheck."""
    payload = _docker_compose_json(["docker", "compose", "config", "--format", "json"])
    if not isinstance(payload, dict):
        return {}
    services = payload.get("services", {}) or {}
    if not isinstance(services, dict):
        return {}

    result: Dict[str, bool] = {}
    for service_name, config in services.items():
        if not isinstance(config, dict):
            continue
        result[str(service_name)] = "healthcheck" in config
    return result


def _load_compose_runtime_health() -> Dict[str, Dict[str, str]]:
    """Return runtime state and health values reported by docker compose ps."""
    payload = _docker_compose_json(["docker", "compose", "ps", "--format", "json"])
    if not isinstance(payload, list):
        return {}

    runtime: Dict[str, Dict[str, str]] = {}
    for container in payload:
        if not isinstance(container, dict):
            continue
        service_name = str(container.get("Service", "")).strip()
        if not service_name:
            continue
        runtime[service_name] = {
            "state": str(container.get("State", "")).strip().lower(),
            "health": str(container.get("Health", "")).strip().lower(),
        }
    return runtime


def _build_target_service_status(
    active_targets: List[Dict[str, object]],
    expected_services: List[str],
    recently_seen_services: Optional[List[str]] = None,
    service_healthcheck_config: Optional[Dict[str, bool]] = None,
    runtime_health_by_service: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Map expected compose services to their Prometheus target health."""
    expected_lookup = {service.lower(): service for service in expected_services}

    def _resolve_expected_service_name(raw_candidate: str) -> str:
        candidate = str(raw_candidate or "").strip().lstrip("/")
        if not candidate:
            return ""

        variants = {candidate}
        variants.add(candidate.lower())

        if "/" in candidate:
            tail = candidate.rsplit("/", 1)[-1]
            variants.add(tail)
            variants.add(tail.lower())
        if ":" in candidate:
            head = candidate.split(":", 1)[0]
            variants.add(head)
            variants.add(head.lower())

        container_name_match = re.match(r"^[^_]+_([^_]+)_\d+$", candidate)
        if container_name_match:
            service_candidate = container_name_match.group(1)
            variants.add(service_candidate)
            variants.add(service_candidate.lower())

        normalized_variants = set(variants)
        normalized_variants.update(value.replace("_", "-") for value in variants)
        normalized_variants.update(value.replace("-", "_") for value in variants)

        for variant in normalized_variants:
            direct_match = expected_lookup.get(variant)
            if direct_match:
                return direct_match
            lower_match = expected_lookup.get(variant.lower())
            if lower_match:
                return lower_match
        return ""

    status_by_service: Dict[str, str] = {
        service: "unknown" for service in expected_services
    }

    for target in active_targets:
        labels = target.get("labels", {}) or {}
        discovered_labels = target.get("discoveredLabels", {}) or {}
        candidates = [
            str(labels.get("container_label_com_docker_compose_service", "")).strip(),
            str(
                discovered_labels.get(
                    "__meta_docker_container_label_com_docker_compose_service", ""
                )
            ).strip(),
            str(discovered_labels.get("__meta_docker_container_name", "")).strip(),
            str(labels.get("job", "")).strip(),
            str(target.get("scrapePool", "")).strip(),
        ]
        health = str(target.get("health", "unknown")).lower()
        for candidate in candidates:
            service_name = _resolve_expected_service_name(candidate)
            if not service_name:
                continue
            current = status_by_service[service_name]
            if health == "up":
                status_by_service[service_name] = "up"
            elif current != "up" and health in {"down", "unknown"}:
                status_by_service[service_name] = health

    recently_seen = {
        str(service).strip().lower() for service in (recently_seen_services or [])
    }

    for service, health in list(status_by_service.items()):
        if health == "unknown" and service.lower() in recently_seen:
            status_by_service[service] = "up"

    healthcheck_lookup = {
        str(name).lower(): bool(enabled)
        for name, enabled in (service_healthcheck_config or {}).items()
    }
    runtime_lookup = {
        str(name).lower(): payload
        for name, payload in (runtime_health_by_service or {}).items()
    }

    services: List[Dict[str, str]] = []
    for service in expected_services:
        prometheus_health = status_by_service.get(service, "unknown")
        runtime = runtime_lookup.get(service.lower(), {})
        state = str(runtime.get("state", "")).lower()
        healthcheck_state = str(runtime.get("health", "")).lower()
        has_healthcheck = healthcheck_lookup.get(service.lower(), False)
        if not has_healthcheck and healthcheck_state:
            has_healthcheck = True

        final_health = prometheus_health
        if has_healthcheck:
            if state and state != "running":
                final_health = "down"
            elif healthcheck_state == "healthy":
                final_health = "healthy"
            elif healthcheck_state == "unhealthy":
                final_health = "unhealthy"
            elif healthcheck_state == "starting":
                final_health = "starting"
            elif final_health == "unknown" and state == "running":
                final_health = "up"
        elif final_health == "unknown" and state == "running":
            final_health = "up"

        services.append(
            {
                "service": service,
                "health": final_health,
                "state": state or "unknown",
                "healthcheck": healthcheck_state if has_healthcheck else "none",
            }
        )

    return services


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

    grafana_public_url = os.environ.get("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "").strip()
    prometheus_public_url = os.environ.get(
        "ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL", ""
    ).strip()
    grafana_host_port = _to_int_env("GRAFANA_HOST_PORT", 3000)
    prometheus_host_port = _to_int_env("PROMETHEUS_HOST_PORT", 9090)

    request_host = _safe_request_host(request)
    request_scheme = request.scheme

    dashboard_uid = os.environ.get(
        "ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "omero-infrastructure"
    )
    dashboard_slug = os.environ.get(
        "ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "server-infrastructure"
    )

    dashboard_query = urlencode(
        {
            "orgId": "1",
            "from": "now-6h",
            "to": "now",
            "timezone": "browser",
            "refresh": "10s",
        }
    )
    grafana_public_base_url = grafana_public_url
    if not grafana_public_base_url and _is_internal_hostname(
        urlparse(grafana_base_url).hostname or ""
    ):
        grafana_public_base_url = _build_public_service_url(
            grafana_base_url,
            request_scheme,
            request_host,
            grafana_host_port,
        )

    prometheus_public_base_url = prometheus_public_url
    if not prometheus_public_base_url and _is_internal_hostname(
        urlparse(prometheus_base_url).hostname or ""
    ):
        prometheus_public_base_url = _build_public_service_url(
            prometheus_base_url,
            request_scheme,
            request_host,
            prometheus_host_port,
        )

    dashboard_external_url = ""
    if grafana_public_base_url:
        dashboard_external_url = f"{grafana_public_base_url.rstrip('/')}/d/{dashboard_uid}/{dashboard_slug}?{dashboard_query}"

    prometheus_targets_url = ""
    if prometheus_public_base_url:
        prometheus_targets_url = f"{prometheus_public_base_url.rstrip('/')}/targets"

    dashboard_proxy_path = reverse(
        "omeroweb_admin_tools_grafana_proxy",
        kwargs={"subpath": f"d/{dashboard_uid}/{dashboard_slug}"},
    )
    dashboard_proxy_url = f"{dashboard_proxy_path}?{dashboard_query}"
    dashboard_url = dashboard_proxy_url

    postgres_dashboard_proxy_path = reverse(
        "omeroweb_admin_tools_grafana_proxy",
        kwargs={"subpath": "d/database-metrics/database"},
    )
    database_dashboard_url = f"{postgres_dashboard_proxy_path}?{dashboard_query}"

    plugin_database_dashboard_proxy_path = reverse(
        "omeroweb_admin_tools_grafana_proxy",
        kwargs={"subpath": "d/plugin-database-metrics/plugin-database"},
    )
    plugin_database_dashboard_url = (
        f"{plugin_database_dashboard_proxy_path}?{dashboard_query}"
    )

    redis_dashboard_proxy_path = reverse(
        "omeroweb_admin_tools_grafana_proxy",
        kwargs={"subpath": "d/redis-metrics/redis"},
    )
    redis_dashboard_url = f"{redis_dashboard_proxy_path}?{dashboard_query}"
    prometheus_targets_proxy_url = reverse(
        "omeroweb_admin_tools_prometheus_proxy", kwargs={"subpath": "targets"}
    )

    grafana_probe = _probe_http_url(f"{grafana_base_url.rstrip('/')}/api/health")
    prometheus_probe = _probe_http_url(f"{prometheus_base_url.rstrip('/')}/-/ready")

    expected_services = _load_compose_service_names()
    system_metrics = _collect_system_metrics(prometheus_base_url)

    targets_overview = {
        "active": 0,
        "up": 0,
        "down": 0,
        "unknown": 0,
        "services": [],
    }
    try:
        targets_api = f"{prometheus_base_url.rstrip('/')}/api/v1/targets"
        with urllib.request.urlopen(targets_api, timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        active_targets = payload.get("data", {}).get("activeTargets", [])
        targets_overview["active"] = len(active_targets)
        targets_overview["up"] = sum(
            1
            for target in active_targets
            if str(target.get("health", "")).lower() == "up"
        )
        targets_overview["down"] = sum(
            1
            for target in active_targets
            if str(target.get("health", "")).lower() == "down"
        )
        targets_overview["unknown"] = (
            targets_overview["active"]
            - targets_overview["up"]
            - targets_overview["down"]
        )

        recently_seen_services: List[str] = []
        service_healthcheck_config, runtime_health_by_service = (
            _load_compose_health_data()
        )
        try:
            recently_seen_services = _collect_recently_seen_services(
                prometheus_base_url
            )
        except Exception:
            logger.exception("Failed to fetch recently seen cAdvisor services")

        all_services = sorted(set(expected_services) | set(recently_seen_services))
        targets_overview["services"] = _build_target_service_status(
            active_targets,
            all_services,
            recently_seen_services=recently_seen_services,
            service_healthcheck_config=service_healthcheck_config,
            runtime_health_by_service=runtime_health_by_service,
        )
    except Exception:
        logger.exception("Failed to fetch Prometheus targets overview")

    return JsonResponse(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "grafana": {
                "base_url": grafana_base_url,
                "dashboard_url": dashboard_url,
                "dashboard_external_url": dashboard_external_url,
                "dashboard_proxy_url": dashboard_proxy_url,
                "database_dashboard_url": database_dashboard_url,
                "plugin_database_dashboard_url": plugin_database_dashboard_url,
                "redis_dashboard_url": redis_dashboard_url,
                "probe": grafana_probe,
            },
            "prometheus": {
                "base_url": prometheus_base_url,
                "targets_url": prometheus_targets_url,
                "targets_proxy_url": prometheus_targets_proxy_url,
                "probe": prometheus_probe,
                "targets_overview": targets_overview,
            },
            "system_metrics": system_metrics,
            "docker_diagnostics": _diagnose_docker_health(),
        }
    )


@csrf_exempt
@login_required()
def grafana_proxy(request, subpath: str, conn=None, url=None, **kwargs):
    """Proxy Grafana HTTP responses through OMERO.web."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    grafana_base_url = os.environ.get("ADMIN_TOOLS_GRAFANA_URL", "http://grafana:3000")
    if subpath.startswith(("http://", "https://")):
        parsed = urlparse(subpath)
        subpath = parsed.path.lstrip("/")
        forwarded_query = parsed.query
    else:
        forwarded_query = ""
    request_query = request.META.get("QUERY_STRING", "")
    merged_query = "&".join(part for part in (forwarded_query, request_query) if part)
    proxy_prefix = (
        request.path[: -len(subpath)].rstrip("/") if subpath else request.path
    )
    return _proxy_http_request(
        request,
        grafana_base_url,
        subpath,
        merged_query,
        proxy_prefix=proxy_prefix,
    )


@csrf_exempt
@login_required()
def prometheus_proxy(request, subpath: str, conn=None, url=None, **kwargs):
    """Proxy Prometheus HTTP responses through OMERO.web."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    prometheus_base_url = os.environ.get(
        "ADMIN_TOOLS_PROMETHEUS_URL", "http://prometheus:9090"
    )
    if subpath.startswith(("http://", "https://")):
        parsed = urlparse(subpath)
        subpath = parsed.path.lstrip("/")
        forwarded_query = parsed.query
    else:
        forwarded_query = ""
    request_query = request.META.get("QUERY_STRING", "")
    merged_query = "&".join(part for part in (forwarded_query, request_query) if part)
    proxy_prefix = (
        request.path[: -len(subpath)].rstrip("/") if subpath else request.path
    )
    return _proxy_http_request(
        request,
        prometheus_base_url,
        subpath,
        merged_query,
        proxy_prefix=proxy_prefix,
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
    full_name_by_user: Dict[str, str] = {}
    groups_by_user: Dict[str, set] = {}
    totals_by_group: Dict[str, int] = {}
    users_by_group: Dict[str, set] = {}
    total_size = 0

    try:
        service_opts = conn.SERVICE_OPTS
        if hasattr(service_opts, "setOmeroGroup"):
            service_opts.setOmeroGroup(-1)
        rows = conn.getQueryService().projection(query, None, service_opts)
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
            groups_by_user.setdefault(user_name, set()).add(group_name)
            totals_by_group[group_name] = (
                totals_by_group.get(group_name, 0) + size_value
            )
            users_by_group.setdefault(group_name, set()).add(user_name)
            total_size += size_value

        (
            all_users,
            all_groups,
            group_permissions,
            all_groups_by_user,
            all_users_by_group,
        ) = _list_all_users_and_groups(conn)
        for username, full_name in all_users.items():
            totals_by_user.setdefault(username, 0)
            groups_by_user.setdefault(username, set()).update(
                all_groups_by_user.get(username, set())
            )
            full_name_by_user[username] = full_name
        for group_name in all_groups:
            totals_by_group.setdefault(group_name, 0)
            users_by_group.setdefault(group_name, set()).update(
                all_users_by_group.get(group_name, set())
            )
            group_permissions.setdefault(group_name, "Private")

        for username in totals_by_user:
            full_name_by_user.setdefault(username, "")
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
                {
                    "username": username,
                    "full_name": full_name_by_user.get(username, ""),
                    "groups": sorted(groups_by_user.get(username, set())),
                    "bytes": size,
                }
                for username, size in sorted(
                    totals_by_user.items(), key=lambda item: item[1], reverse=True
                )
            ],
            "by_group": [
                {
                    "group": groupname,
                    "users": sorted(users_by_group.get(groupname, set())),
                    "permissions": group_permissions.get(groupname, "Private"),
                    "bytes": size,
                }
                for groupname, size in sorted(
                    totals_by_group.items(), key=lambda item: item[1], reverse=True
                )
            ],
            "by_user_group": sorted(
                per_user_group, key=lambda item: item["bytes"], reverse=True
            ),
        }
    )


@login_required()
def server_database_testing_view(request, conn=None, url=None, **kwargs):
    """Render OMERO.server and database diagnostics page."""
    return render(
        request,
        "omeroweb_admin_tools/server_database_testing.html",
        {"diagnostic_scripts": json.dumps(serialize_scripts())},
    )


@csrf_exempt
@login_required()
def server_database_testing_run(request, conn=None, url=None, **kwargs):
    """Execute selected diagnostics scripts and return a report."""
    root_error = _require_root_user(request, conn)
    if root_error:
        return root_error
    if request.method != "POST":
        return JsonResponse({"error": "POST method required."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    script_ids = payload.get("scripts")
    if not isinstance(script_ids, list) or not script_ids:
        return JsonResponse(
            {"error": "Payload must include non-empty 'scripts' list."},
            status=400,
        )

    normalized_script_ids = [str(script_id).strip() for script_id in script_ids]
    if any(not script_id for script_id in normalized_script_ids):
        return JsonResponse(
            {"error": "Payload contains invalid empty script IDs."},
            status=400,
        )

    request_id = str(uuid.uuid4())
    logger.info(
        "[%s] Running diagnostics scripts requested by %s: %s",
        request_id,
        current_username(request),
        ", ".join(normalized_script_ids),
    )
    try:
        results = [
            run_diagnostic_script(script_id) for script_id in normalized_script_ids
        ]
    except Exception as exc:
        logger.error(
            "[%s] Failed to run diagnostics scripts %s: %s\n%s",
            request_id,
            ", ".join(normalized_script_ids),
            exc,
            traceback.format_exc(),
        )
        return JsonResponse(
            {
                "error": "Failed to run diagnostics due to an internal server error.",
                "request_id": request_id,
            },
            status=500,
        )

    logger.info(
        "[%s] Diagnostics scripts completed successfully. scripts=%s",
        request_id,
        ", ".join(normalized_script_ids),
    )
    return JsonResponse({"results": results, "request_id": request_id})
