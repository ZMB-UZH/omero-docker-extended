from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import time
import logging
from dataclasses import asdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


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


def _get_env(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return str(value).strip() or default


def _to_float_env(name: str, default: float) -> float:
    raw_value = _get_env(name, str(default))
    try:
        return float(raw_value)
    except ValueError:
        return default


def _elapsed_ms(start: float) -> int:
    return int(max(0.0, (time.monotonic() - start) * 1000.0))


def _run_command(cmd: Sequence[str], timeout_s: float = 8.0) -> Tuple[bool, str, str]:
    try:
        completed = subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return False, "", f"Command not available: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout_s:.1f}s"
    return completed.returncode == 0, completed.stdout.strip(), completed.stderr.strip()


def _resolve_hostname(check_id: str, label: str, host: str) -> DiagnosticCheckResult:
    start = time.monotonic()
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=f"Unable to resolve host {host}",
            details=str(exc),
        )
    unique_ips = sorted({entry[4][0] for entry in addresses if entry and entry[4]})
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
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=f"TCP connection failed ({host}:{port})",
            details=str(exc),
        )


def _http_probe(
    check_id: str, label: str, url: str, timeout_s: float
) -> DiagnosticCheckResult:
    start = time.monotonic()
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status_code = int(getattr(response, "status", 0) or 0)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=f"HTTP probe returned {status_code}",
            details=f"{url} returned HTTP {status_code}",
        )
    except urllib.error.URLError as exc:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary="HTTP probe failed",
            details=f"{url}: {exc.reason}",
        )
    status = "pass" if 200 <= status_code < 400 else "warn"
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=_elapsed_ms(start),
        summary=f"HTTP probe returned {status_code}",
        details=url,
    )


def _docker_compose_command() -> Optional[List[str]]:
    # Always use the project name 'omero' when running from inside the container
    # so docker compose knows what to target, since it's not running in the 
    # directory where the docker-compose.yml lives.
    for candidate in (("docker", "compose"), ("docker-compose",)):
        ok, _, _ = _run_command([*candidate, "version"], timeout_s=5.0)
        if ok:
            return [*candidate, "--project-name", "omero"]
    return None


def _compose_ps_health(
    check_id: str, label: str, service: str
) -> DiagnosticCheckResult:
    start = time.monotonic()
    compose_cmd = _docker_compose_command()
    if compose_cmd is None:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="warn",
            duration_ms=_elapsed_ms(start),
            summary="Docker compose command unavailable",
            details="Cannot inspect container state from this environment.",
        )
    ok, stdout, stderr = _run_command(
        [*compose_cmd, "ps", service, "--format", "json"], timeout_s=8.0
    )
    if not ok:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="warn",
            duration_ms=_elapsed_ms(start),
            summary=f"Unable to read compose state for {service}",
            details=stderr or stdout or "No compose output.",
        )
    if not stdout.strip():
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="warn",
            duration_ms=_elapsed_ms(start),
            summary=f"Service {service} not found in compose output",
            details="Empty response from docker compose ps.",
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="warn",
            duration_ms=_elapsed_ms(start),
            summary=f"Failed to parse compose output for {service}",
            details=f"JSON Decode Error: {exc}\nOutput: {stdout[:280]}",
        )
    records = payload if isinstance(payload, list) else [payload]
    if not records:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="warn",
            duration_ms=_elapsed_ms(start),
            summary=f"Service {service} missing from compose output",
            details=stdout[:280],
        )
    record = records[0]
    state = str(record.get("State") or "unknown")
    health = str(record.get("Health") or "unknown")
    status = (
        "pass"
        if state.lower() == "running"
        and health.lower() in {"", "healthy", "none", "unknown"}
        else "warn"
    )
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=_elapsed_ms(start),
        summary=f"Compose state: {state}, health: {health}",
        details=f"Service: {service}",
    )


def _compose_pg_test(check_id: str, label: str, service: str) -> DiagnosticCheckResult:
    start = time.monotonic()
    compose_cmd = _docker_compose_command()
    if compose_cmd is None:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="warn",
            duration_ms=_elapsed_ms(start),
            summary="Docker compose command unavailable",
            details="Cannot execute in-container PostgreSQL checks.",
        )
    shell_cmd = (
        'db_name="${POSTGRES_DB:-postgres}"; '
        'db_user="${POSTGRES_USER:-postgres}"; '
        'pg_isready -d "$db_name" -U "$db_user" && '
        'psql -d "$db_name" -U "$db_user" -tAc "SELECT 1"'
    )
    cmd = [*compose_cmd, "exec", "-T", service, "sh", "-lc", shell_cmd]
    ok, stdout, stderr = _run_command(cmd, timeout_s=10.0)
    if not ok:
        return DiagnosticCheckResult(
            check_id=check_id,
            label=label,
            status="fail",
            duration_ms=_elapsed_ms(start),
            summary=f"In-container SQL test failed ({service})",
            details=stderr or stdout or "No output.",
        )
    sql_result = stdout.splitlines()[-1].strip() if stdout else ""
    status = "pass" if sql_result == "1" else "warn"
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status=status,
        duration_ms=_elapsed_ms(start),
        summary=f"In-container SQL check completed ({service})",
        details=stdout or "No output.",
    )


def list_diagnostic_scripts() -> List[DiagnosticScript]:
    return [
        DiagnosticScript(
            script_id="omero_server_core",
            label="OMERO.server core connectivity",
            description="DNS resolution, Blitz TCP ports, web health probe, and compose state.",
            category="OMERO.server",
        ),
        DiagnosticScript(
            script_id="omero_database",
            label="OMERO database deep check",
            description="Host resolution, TCP connectivity, compose status, pg_isready and SQL probe.",
            category="Database",
        ),
        DiagnosticScript(
            script_id="plugin_database",
            label="Plugin database deep check",
            description="Host resolution, TCP connectivity, compose status, pg_isready and SQL probe.",
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
    host = _get_env("ADMIN_TOOLS_OMERO_SERVER_HOST", "omeroserver")
    blitz_port = int(_get_env("ADMIN_TOOLS_OMERO_BLITZ_PORT", "4064"))
    secure_port = int(_get_env("ADMIN_TOOLS_OMERO_SECURE_PORT", "4063"))
    web_url = _get_env(
        "ADMIN_TOOLS_OMERO_WEB_HEALTH_URL", "http://omeroweb:4080/webclient/"
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
    script_prefix: str, label_prefix: str, host_env: str, port_env: str, service: str
) -> List[DiagnosticCheckResult]:
    host = _get_env(host_env, service)
    port = int(_get_env(port_env, "5432"))
    timeout_s = _to_float_env("ADMIN_TOOLS_DIAGNOSTIC_TIMEOUT_SECONDS", 3.5)

    return [
        _resolve_hostname(
            f"{script_prefix}_dns", f"Resolve {label_prefix} hostname", host
        ),
        _tcp_connect(
            f"{script_prefix}_tcp",
            f"Connect to {label_prefix} PostgreSQL TCP endpoint",
            host,
            port,
            timeout_s,
        ),
        _compose_ps_health(
            f"{script_prefix}_compose_state",
            f"Inspect {label_prefix} compose state",
            service,
        ),
        _compose_pg_test(
            f"{script_prefix}_sql",
            f"Run in-container SQL sanity test ({label_prefix})",
            service,
        ),
    ]


def run_diagnostic_script(script_id: str) -> Dict[str, object]:
    script_map: Dict[str, Callable[[], List[DiagnosticCheckResult]]] = {
        "omero_server_core": _run_omero_server_core,
        "omero_database": lambda: _run_database_checks(
            "omero_database",
            "OMERO database",
            "ADMIN_TOOLS_OMERO_DB_HOST",
            "ADMIN_TOOLS_OMERO_DB_PORT",
            "database",
        ),
        "plugin_database": lambda: _run_database_checks(
            "plugin_database",
            "plugin database",
            "ADMIN_TOOLS_PLUGIN_DB_HOST",
            "ADMIN_TOOLS_PLUGIN_DB_PORT",
            "database_plugin",
        ),
    }

    try:
        if script_id == "platform_end_to_end":
            checks: List[DiagnosticCheckResult] = []
            for child_script in ("omero_server_core", "omero_database", "plugin_database"):
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

        return {
            "script_id": script_id,
            "status": status,
            "summary": {
                "pass": pass_count,
                "warn": warn_count,
                "fail": fail_count,
                "total": len(checks),
            },
            "checks": [asdict(item) for item in checks],
        }
    except Exception as exc:
        logger.exception(f"Exception running diagnostic script {script_id}")
        return {
            "script_id": script_id,
            "status": "fail",
            "error": f"Failed to execute check: {exc}",
            "checks": [],
        }


def serialize_scripts() -> List[Dict[str, str]]:
    return [asdict(item) for item in list_diagnostic_scripts()]
