from __future__ import annotations

import json
import os
import shlex
import socket
import time
import logging
from http.client import HTTPConnection
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import urllib.parse
import requests

from omero_plugin_common.logging_utils import (
    sanitize_log_value,
    sanitize_url_for_logging,
)

logger = logging.getLogger(__name__)


_DOCKER_RUNTIME_ERROR_SUMMARY = "Docker runtime inspection failed"
_DIRECT_SQL_ERROR_SUMMARY = "Direct SQL sanity test failed"

_PSYCOPG2_UNSET = object()


@dataclass
class _ModuleCache:
    """Represent module cache."""

    value: Any = _PSYCOPG2_UNSET


_PSYCOPG2_CACHE = _ModuleCache()


def _get_cached_psycopg2_module():
    """Return cached psycopg2 module.

    Inputs: none. Output: `_PSYCOPG2_CACHE.value`.
    """
    return _PSYCOPG2_CACHE.value


def _set_cached_psycopg2_module(module) -> None:
    """Set cached psycopg2 module.

    Inputs: `module`. Output: None.
    """
    _PSYCOPG2_CACHE.value = module


@dataclass(frozen=True)
class DiagnosticCheckResult:
    """Single test execution outcome."""

    check_id: str
    label: str
    status: str
    duration_ms: int
    summary: str
    details: str


@dataclass(frozen=True)
class DiagnosticScript:
    """Runnable script profile displayed in the UI."""

    script_id: str
    label: str
    description: str
    category: str


@dataclass(frozen=True)
class DatabaseRuntimeProfile:
    """Resolved runtime connection profile for direct SQL diagnostics."""

    host: str
    port: int
    user: str
    password: str
    dbname: str


def _get_env(name: str, default: str) -> str:
    """Return environment.

    Inputs: `name`, `default`. Output: `str`.
    """
    value = os.environ.get(name, default)
    return str(value).strip() or default


def _to_float_env(name: str, default: float) -> float:
    """To float env.

    Inputs: `name`, `default`. Output: `float`.
    """
    raw_value = _get_env(name, str(default))
    try:
        return float(raw_value)
    except ValueError:
        return default


def _first_present_env(names: Sequence[str], default: str = "") -> str:
    """First present env.

    Inputs: `names`, `default`. Output: `str`.
    """
    for name in names:
        raw_value = os.environ.get(name)
        if raw_value is None:
            continue
        normalized = str(raw_value).strip()
        if normalized:
            return normalized
    return default


def _config_failure(summary: str, details: str, start: float) -> DiagnosticCheckResult:
    """Config failure.

    Inputs: `summary`, `details`, `start`. Output: `DiagnosticCheckResult`.
    """
    return DiagnosticCheckResult(
        check_id="omero_runtime_config",
        label="Validate OMERO runtime diagnostic configuration",
        status="fail",
        duration_ms=_elapsed_ms(start),
        summary=summary,
        details=details,
    )


def _parse_runtime_port(raw_value: str, env_names: Sequence[str]) -> int:
    """Parse runtime port.

    Inputs: `raw_value`, `env_names`. Output: `int`. Raises on invalid or unavailable
    state.

    state.
    """
    try:
        port = int(raw_value)
    except ValueError as exc:
        names_label = ", ".join(env_names)
        raise RuntimeError(
            f"Invalid TCP port value {raw_value!r} in runtime env ({names_label})."
        ) from exc

    if port < 1 or port > 65535:
        names_label = ", ".join(env_names)
        raise RuntimeError(
            f"TCP port value {raw_value!r} is outside 1-65535 "
            f"in runtime env ({names_label})."
        )
    return port


def _elapsed_ms(start: float) -> int:
    """Elapsed ms.

    Inputs: `start`. Output: `int`.
    """
    return int(max(0.0, (time.monotonic() - start) * 1000.0))


def _load_psycopg2():
    """Load psycopg2.

    Inputs: none. Output: computed value. Raises on invalid or unavailable state.
    """
    cached_module = _get_cached_psycopg2_module()
    if cached_module is None:
        raise RuntimeError("psycopg2-binary is not installed in the OMERO.web runtime.")
    if cached_module is not _PSYCOPG2_UNSET:
        return cached_module

    try:
        import psycopg2
    except ImportError as exc:
        _set_cached_psycopg2_module(None)
        raise RuntimeError(
            "psycopg2-binary is not installed in the OMERO.web runtime."
        ) from exc
    _set_cached_psycopg2_module(psycopg2)
    return psycopg2


def _resolve_db_profile(
    *,
    host_names: Sequence[str],
    port_names: Sequence[str],
    user_names: Sequence[str],
    password_names: Sequence[str],
    db_names: Sequence[str],
    default_host: str,
    default_port: str,
    default_user: str,
    default_dbname: str,
) -> DatabaseRuntimeProfile:
    """Resolve database profile.

    Inputs: `host_names`, `port_names`, `user_names`, `password_names`, `db_names`,
    `default_host`, `default_port`, `default_user`, `default_dbname`. Output:
    `DatabaseRuntimeProfile`. Raises on invalid or unavailable state.
    """
    host = _first_present_env(host_names, default_host)
    user = _first_present_env(user_names, default_user)
    password = _first_present_env(password_names, "")
    dbname = _first_present_env(db_names, default_dbname)
    port_raw = _first_present_env(port_names, default_port)

    try:
        port = int(port_raw)
    except ValueError as exc:
        names_label = ", ".join(port_names)
        raise RuntimeError(
            f"Invalid PostgreSQL port value {port_raw!r} in runtime env "
            f"({names_label})."
        ) from exc

    return DatabaseRuntimeProfile(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname,
    )


def _omero_database_profile() -> DatabaseRuntimeProfile:
    """OMERO database profile.

    Inputs: none. Output: `DatabaseRuntimeProfile`.
    """
    return _resolve_db_profile(
        host_names=("ADMIN_TOOLS_OMERO_DB_HOST", "CONFIG_omero_db_host"),
        port_names=("ADMIN_TOOLS_OMERO_DB_PORT", "CONFIG_omero_db_port"),
        user_names=("ADMIN_TOOLS_OMERO_DB_USER", "CONFIG_omero_db_user"),
        password_names=("ADMIN_TOOLS_OMERO_DB_PASSWORD", "OMERO_DB_PASS"),
        db_names=("ADMIN_TOOLS_OMERO_DB_NAME", "CONFIG_omero_db_name"),
        default_host="database",
        default_port="5432",
        default_user="omero",
        default_dbname="omero",
    )


def _plugin_database_profile() -> DatabaseRuntimeProfile:
    """Plugin database profile.

    Inputs: none. Output: `DatabaseRuntimeProfile`.
    """
    return _resolve_db_profile(
        host_names=(
            "ADMIN_TOOLS_PLUGIN_DB_HOST",
            "OMP_DATA_HOST",
            "PLUGIN_DB_HOST",
        ),
        port_names=(
            "ADMIN_TOOLS_PLUGIN_DB_PORT",
            "OMP_DATA_PORT",
            "PLUGIN_DB_PORT",
        ),
        user_names=(
            "ADMIN_TOOLS_PLUGIN_DB_USER",
            "OMP_DATA_USER",
            "PLUGIN_DB_USER",
        ),
        password_names=(
            "ADMIN_TOOLS_PLUGIN_DB_PASSWORD",
            "OMP_DATA_PASS",
            "OMP_PLUGIN_DB_PASS",
            "PLUGIN_DB_PASS",
        ),
        db_names=("ADMIN_TOOLS_PLUGIN_DB_NAME", "OMP_DATA_DB", "PLUGIN_DB_NAME"),
        default_host="database_plugin",
        default_port="5433",
        default_user="omero-plugin",
        default_dbname="omero-plugin",
    )


class _UnixSocketHTTPConnection(HTTPConnection):
    """HTTPConnection implementation for Docker Engine unix sockets."""

    def __init__(self, unix_socket_path: str, timeout: float = 3.0):
        """Initialize the instance.

        Inputs: `unix_socket_path`, `timeout`. Output: None.
        """
        super().__init__("localhost", timeout=timeout)
        self.unix_socket_path = unix_socket_path

    def connect(self) -> None:
        """Open the connection.

        Inputs: none. Output: None.
        """
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_socket_path)


def _docker_api_json(path: str, timeout_seconds: float = 4.0) -> Tuple[bool, Any, str]:
    """Docker API JSON.

    Inputs: `path`, `timeout_seconds`. Output: `Tuple[bool, Any, str]`.
    """
    docker_socket = _get_env("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    if not os.path.exists(docker_socket):
        return (
            False,
            None,
            f"Docker socket not found at {docker_socket}. "
            "Mount the engine socket read-only into the OMERO.web runtime.",
        )

    connection = _UnixSocketHTTPConnection(docker_socket, timeout=timeout_seconds)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
    except PermissionError:
        return (
            False,
            None,
            f"Permission denied accessing Docker socket at {docker_socket}. "
            "The OMERO.web runtime user must have read access to the engine socket.",
        )
    except OSError as exc:
        return (
            False,
            None,
            f"Docker API request failed for {path}: {sanitize_log_value(exc)}",
        )
    finally:
        connection.close()

    if response.status < 200 or response.status >= 300:
        return (
            False,
            None,
            f"Docker API returned HTTP {response.status} for {path}.",
        )
    if not payload.strip():
        return False, None, f"Docker API returned an empty response for {path}."
    try:
        return True, json.loads(payload), ""
    except json.JSONDecodeError:
        return False, None, f"Docker API returned invalid JSON for {path}."


def _inspect_docker_service_runtime(
    service: str,
) -> Tuple[Optional[Dict[str, str]], str]:
    """Inspect docker service runtime.

    Inputs: `service`. Output: `Tuple[Optional[Dict[str, str]], str]`.
    """
    project_name = _get_env("ADMIN_TOOLS_COMPOSE_PROJECT_NAME", "omero")
    filters = json.dumps(
        {
            "label": [
                f"com.docker.compose.project={project_name}",
                f"com.docker.compose.service={service}",
            ]
        },
        separators=(",", ":"),
    )
    encoded_filters = urllib.parse.quote(filters, safe="")
    ok, payload, error = _docker_api_json(
        f"/containers/json?all=1&filters={encoded_filters}"
    )
    if not ok:
        return None, error
    if not isinstance(payload, list) or not payload:
        return None, f"No container found for compose service {service!r}."

    containers: list[dict[str, Any]] = [
        item for item in payload if isinstance(item, dict)
    ]
    if not containers:
        return (
            None,
            f"Docker API returned no container records for service {service!r}.",
        )

    def _created_key(item: dict[str, object]) -> int:
        """Created key.

        Inputs: `item`. Output: `int`.
        """
        created = item.get("Created")
        if not isinstance(created, (str, int, float)):
            return 0
        try:
            return int(created)
        except (TypeError, ValueError):
            return 0

    container = max(containers, key=_created_key)
    container_id = str(container.get("Id") or "").strip()
    if not container_id:
        return (
            None,
            f"Docker API did not return a container ID for service {service!r}.",
        )

    ok, inspect_payload, error = _docker_api_json(f"/containers/{container_id}/json")
    if not ok:
        return None, error
    if not isinstance(inspect_payload, dict):
        return None, f"Docker inspect payload was invalid for service {service!r}."

    raw_state_payload = inspect_payload.get("State", {}) or {}
    state_payload = raw_state_payload if isinstance(raw_state_payload, dict) else {}
    raw_health_payload = state_payload.get("Health", {}) or {}
    health_payload = raw_health_payload if isinstance(raw_health_payload, dict) else {}
    names = container.get("Names") or []
    container_name = ""
    if isinstance(names, list) and names:
        container_name = str(names[0]).strip().lstrip("/")
    if not container_name:
        container_name = str(inspect_payload.get("Name") or "").strip().lstrip("/")

    return (
        {
            "container_id": container_id[:12],
            "container_name": container_name or service,
            "state": str(
                state_payload.get("Status") or container.get("State") or "unknown"
            ),
            "health": str(health_payload.get("Status") or "").strip() or "none",
        },
        "",
    )


def _execute_sql_sanity_query(
    profile: DatabaseRuntimeProfile,
) -> Tuple[Optional[int], str]:
    """Execute sql sanity query.

    Inputs: `profile`. Output: `Tuple[Optional[int], str]`.
    """
    psycopg2 = _load_psycopg2()
    conn = None
    try:
        conn = psycopg2.connect(
            host=profile.host,
            port=profile.port,
            user=profile.user,
            password=profile.password,
            dbname=profile.dbname,
            connect_timeout=max(
                1,
                int(
                    round(_to_float_env("ADMIN_TOOLS_DIAGNOSTIC_TIMEOUT_SECONDS", 3.5))
                ),
            ),
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                logger.debug("Suppressed connection close failure", exc_info=True)

    if not row:
        return None, "SQL query returned no rows."
    try:
        return int(row[0]), ""
    except (TypeError, ValueError, IndexError):
        return None, f"SQL query returned unexpected payload: {row!r}"


def _resolve_hostname(check_id: str, label: str, host: str) -> DiagnosticCheckResult:
    """Resolve hostname.

    Inputs: `check_id`, `label`, `host`. Output: `DiagnosticCheckResult`.
    """
    start = time.monotonic()
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        logger.warning(
            "Failed to resolve hostname %s: %s",
            sanitize_log_value(host),
            sanitize_log_value(exc),
        )
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=f"Unable to resolve host {host}",
            details="DNS resolution failed.",
        )
    unique_ips = sorted({str(entry[4][0]) for entry in addresses if entry and entry[4]})
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status="pass",
        duration_ms=_elapsed_ms(start),
        summary=f"Resolved {host}",
        details=", ".join(unique_ips[:6]),
    )


def _tcp_connect(
    check_id: str, label: str, host: str, port: int, timeout_s: float
) -> DiagnosticCheckResult:
    """Tcp connect.

    Inputs: `check_id`, `label`, `host`, `port`, `timeout_s`. Output:
    `DiagnosticCheckResult`.
    """
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return DiagnosticCheckResult(
                check_id=check_id,
                label=label,
                status="pass",
                duration_ms=_elapsed_ms(start),
                summary=f"TCP connection succeeded ({host}:{port})",
                details="Socket opened and closed successfully.",
            )
    except OSError as exc:
        logger.warning(
            "TCP connection failed for %s:%s: %s",
            sanitize_log_value(host),
            sanitize_log_value(port),
            sanitize_log_value(exc),
        )
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=f"TCP connection failed ({host}:{port})",
            details="Socket connection failed.",
        )


def _http_probe(
    check_id: str, label: str, url: str, timeout_s: float
) -> DiagnosticCheckResult:
    """HTTP probe.

    Inputs: `check_id`, `label`, `url`, `timeout_s`. Output: `DiagnosticCheckResult`.
    """
    start = time.monotonic()
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary="HTTP probe failed",
            details="HTTP probe URL is invalid.",
        )
    if parsed.username or parsed.password or parsed.fragment:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary="HTTP probe failed",
            details="HTTP probe URL is invalid.",
        )
    safe_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, "")
    )
    try:
        response = requests.get(safe_url, timeout=timeout_s, allow_redirects=True)
        status_code = int(response.status_code)
    except requests.RequestException as exc:
        logger.warning(
            "HTTP probe failed for %s: %s",
            sanitize_url_for_logging(safe_url),
            sanitize_log_value(exc),
        )
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary="HTTP probe failed",
            details="HTTP probe could not reach the target.",
        )
    status = "pass" if 200 <= status_code < 400 else "warn"
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=_elapsed_ms(start),
        summary=f"HTTP probe returned {status_code}",
        details=safe_url,
    )


def _compose_ps_health(
    check_id: str, label: str, service: str
) -> DiagnosticCheckResult:
    """Compose ps health.

    Inputs: `check_id`, `label`, `service`. Output: `DiagnosticCheckResult`.
    """
    start = time.monotonic()
    runtime_state, error = _inspect_docker_service_runtime(service)
    if runtime_state is None:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=_DOCKER_RUNTIME_ERROR_SUMMARY,
            details=error,
        )
    state = runtime_state["state"]
    health = runtime_state["health"]
    status = (
        "pass"
        if state.lower() == "running" and health.lower() in {"healthy", "none"}
        else "fail"
    )
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=_elapsed_ms(start),
        summary=f"Docker state: {state}, health: {health}",
        details=(
            f"Service {service} -> container {runtime_state['container_name']} "
            f"({runtime_state['container_id']})."
        ),
    )


def _direct_pg_test(
    check_id: str,
    label: str,
    profile_loader: Callable[[], DatabaseRuntimeProfile],
) -> DiagnosticCheckResult:
    """Direct pg test.

    Inputs: `check_id`, `label`, `profile_loader`. Output: `DiagnosticCheckResult`.
    Raises on invalid or unavailable state.
    """
    start = time.monotonic()
    try:
        profile = profile_loader()
        if not profile.password:
            raise RuntimeError(
                "Missing PostgreSQL password in runtime env for the selected database."
            )
        sql_result, error = _execute_sql_sanity_query(profile)
    except Exception as exc:
        logger.warning("Direct SQL test failed: %s", sanitize_log_value(exc))
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=_DIRECT_SQL_ERROR_SUMMARY,
            details=str(exc),
        )
    if error:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=_DIRECT_SQL_ERROR_SUMMARY,
            details=error,
        )
    status = "pass" if sql_result == 1 else "fail"
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=_elapsed_ms(start),
        summary="Direct SQL check completed",
        details=(
            f"Connected to {profile.user}@{profile.host}:{profile.port}/"
            f"{profile.dbname}; SELECT 1 returned {sql_result!r}."
        ),
    )


def list_diagnostic_scripts() -> List[DiagnosticScript]:
    """Return list diagnostic scripts.

    Inputs: none. Output: `List[DiagnosticScript]`.
    """
    return [
        DiagnosticScript(
            script_id="omero_server_core",
            label="OMERO.server core connectivity",
            description=(
                "DNS resolution, Blitz TCP ports, OMERO.web health probe, "
                "and Docker runtime state."
            ),
            category="OMERO.server",
        ),
        DiagnosticScript(
            script_id="omero_database",
            label="OMERO database deep check",
            description=(
                "Host resolution, TCP connectivity, Docker runtime state, "
                "and a direct SQL SELECT 1 probe."
            ),
            category="Database",
        ),
        DiagnosticScript(
            script_id="plugin_database",
            label="Plugin database deep check",
            description=(
                "Host resolution, TCP connectivity, Docker runtime state, "
                "and a direct SQL SELECT 1 probe."
            ),
            category="Database",
        ),
        DiagnosticScript(
            script_id="platform_end_to_end",
            label="Platform end-to-end bundle",
            description="Runs all checks and returns an operator-friendly readiness report.",
            category="Bundle",
        ),
    ]


def _run_omero_server_core() -> List[DiagnosticCheckResult]:
    """OMERO server core.

    Inputs: none. Output: `List[DiagnosticCheckResult]`.
    """
    config_start = time.monotonic()
    host = _first_present_env(
        ("ADMIN_TOOLS_OMERO_SERVER_HOST", "OMEROHOST", "CONFIG_omero_host")
    )
    blitz_port_names = ("ADMIN_TOOLS_OMERO_BLITZ_PORT", "OMERO_PORT", "OMERO_CLI_PORT")
    secure_port_names = ("ADMIN_TOOLS_OMERO_SECURE_PORT", "OMERO_SECURE_PORT")
    web_host = _first_present_env(("ADMIN_TOOLS_OMERO_WEB_HOST",))
    web_port_names = (
        "ADMIN_TOOLS_OMERO_WEB_PORT",
        "CONFIG_omero_web_application__server_port",
    )
    web_path = _first_present_env(("ADMIN_TOOLS_OMERO_WEB_PATH",))

    missing_config = []
    if not host:
        missing_config.append(
            "ADMIN_TOOLS_OMERO_SERVER_HOST/OMEROHOST/CONFIG_omero_host"
        )
    if not _first_present_env(blitz_port_names):
        missing_config.append("/".join(blitz_port_names))
    if not _first_present_env(secure_port_names):
        missing_config.append("/".join(secure_port_names))
    if not web_host:
        missing_config.append("ADMIN_TOOLS_OMERO_WEB_HOST")
    if not _first_present_env(web_port_names):
        missing_config.append("/".join(web_port_names))
    if not web_path:
        missing_config.append("ADMIN_TOOLS_OMERO_WEB_PATH")
    if missing_config:
        return [
            _config_failure(
                "Missing OMERO runtime diagnostic configuration.",
                "Missing required runtime environment: "
                + ", ".join(sorted(missing_config)),
                config_start,
            )
        ]

    try:
        blitz_port = _parse_runtime_port(
            _first_present_env(blitz_port_names), blitz_port_names
        )
        secure_port = _parse_runtime_port(
            _first_present_env(secure_port_names), secure_port_names
        )
        web_port = _parse_runtime_port(
            _first_present_env(web_port_names), web_port_names
        )
    except RuntimeError as exc:
        return [
            _config_failure(
                "Invalid OMERO runtime diagnostic port configuration.",
                str(exc),
                config_start,
            )
        ]

    configured_web_url = _first_present_env(("ADMIN_TOOLS_OMERO_WEB_HEALTH_URL",))
    web_url = configured_web_url or urllib.parse.urlunsplit(
        ("http", f"{web_host}:{web_port}", web_path, "", "")
    )
    timeout_s = _to_float_env("ADMIN_TOOLS_DIAGNOSTIC_TIMEOUT_SECONDS", 3.5)

    return [
        _resolve_hostname("omero_host_dns", "Resolve OMERO.server hostname", host),
        _tcp_connect(
            "omero_blitz_tcp",
            "Connect to OMERO Blitz port",
            host,
            blitz_port,
            timeout_s,
        ),
        _tcp_connect(
            "omero_secure_tcp",
            "Connect to OMERO secure port",
            host,
            secure_port,
            timeout_s,
        ),
        _http_probe("omero_web_http", "Probe OMERO.web endpoint", web_url, timeout_s),
        _compose_ps_health(
            "omero_compose_state", "Inspect OMERO.server compose state", "omeroserver"
        ),
    ]


def _run_database_checks(
    script_prefix: str,
    label_prefix: str,
    service: str,
    profile_loader: Callable[[], DatabaseRuntimeProfile],
) -> List[DiagnosticCheckResult]:
    """Database checks.

    Inputs: `script_prefix`, `label_prefix`, `service`, `profile_loader`. Output:
    `List[DiagnosticCheckResult]`.
    """
    profile = profile_loader()
    timeout_s = _to_float_env("ADMIN_TOOLS_DIAGNOSTIC_TIMEOUT_SECONDS", 3.5)

    return [
        _resolve_hostname(
            f"{script_prefix}_dns", f"Resolve {label_prefix} hostname", profile.host
        ),
        _tcp_connect(
            f"{script_prefix}_tcp",
            f"Connect to {label_prefix} PostgreSQL TCP endpoint",
            profile.host,
            profile.port,
            timeout_s,
        ),
        _compose_ps_health(
            f"{script_prefix}_compose_state",
            f"Inspect {label_prefix} compose state",
            service,
        ),
        _direct_pg_test(
            f"{script_prefix}_sql",
            f"Run direct SQL sanity test ({label_prefix})",
            profile_loader,
        ),
    ]


def run_diagnostic_script(script_id: str) -> Dict[str, object]:
    """A configured diagnostic script.

    Inputs: `script_id`. Output: `Dict[str, object]`.
    """
    scripts = list_diagnostic_scripts()
    script_lookup = {script.script_id: script for script in scripts}
    script_map: Dict[str, Callable[[], List[DiagnosticCheckResult]]] = {
        "omero_server_core": _run_omero_server_core,
        "omero_database": lambda: _run_database_checks(
            "omero_database",
            "OMERO database",
            "database",
            _omero_database_profile,
        ),
        "plugin_database": lambda: _run_database_checks(
            "plugin_database",
            "plugin database",
            "database_plugin",
            _plugin_database_profile,
        ),
    }

    try:
        if script_id == "platform_end_to_end":
            checks: List[DiagnosticCheckResult] = []
            for child_script in (
                "omero_server_core",
                "omero_database",
                "plugin_database",
            ):
                checks.extend(script_map[child_script]())
        elif script_id in script_map:
            checks = script_map[script_id]()
        else:
            return {
                "script_id": script_id,
                "status": "fail",
                "error": f"Unknown script_id: {shlex.quote(script_id)}",
                "checks": [],
            }

        pass_count = sum(1 for item in checks if item.status == "pass")
        warn_count = sum(1 for item in checks if item.status == "warn")
        fail_count = sum(1 for item in checks if item.status == "fail")
        status = "pass"
        if fail_count:
            status = "fail"
        elif warn_count:
            status = "warn"

        script_meta = script_lookup.get(script_id)
        return {
            "script_id": script_id,
            "label": script_meta.label if script_meta else script_id,
            "description": script_meta.description if script_meta else "",
            "category": script_meta.category if script_meta else "",
            "status": status,
            "summary": {
                "pass": pass_count,
                "warn": warn_count,
                "fail": fail_count,
                "total": len(checks),
            },
            "checks": [asdict(item) for item in checks],
        }
    except Exception:
        logger.exception(
            "Exception running diagnostic script %s", sanitize_log_value(script_id)
        )
        return {
            "script_id": script_id,
            "status": "fail",
            "error": "Failed to execute check due to an internal server error.",
            "checks": [],
        }


def serialize_scripts() -> List[Dict[str, str]]:
    """Serialize scripts.

    Inputs: none. Output: `List[Dict[str, str]]`.
    """
    return [asdict(item) for item in list_diagnostic_scripts()]
