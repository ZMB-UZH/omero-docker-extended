from __future__ import annotations

import json
import socket
import requests

from omeroweb_admin_tools.services import system_diagnostics
from omeroweb_admin_tools.services.system_diagnostics import (
    DatabaseRuntimeProfile,
    DiagnosticCheckResult,
)


class _FakeResponse:
    """Test double for fake response."""

    def __init__(self, status, payload):
        """Create `_FakeResponse` with `status` and `payload`.

        Inputs: `status`, `payload`. Output: None.
        """
        self.status = status
        self.status_code = status
        self._payload = payload
        self.content = payload
        self.text = payload.decode("utf-8", errors="replace")

    def read(self):
        """Read data from the resource.

        Inputs: none. Output: `self._payload`.
        """
        return self._payload


class _FakeConnection:
    """Test double for fake connection."""

    def __init__(self, response=None, *, request_error=None):
        """Create `_FakeConnection` with `response`.

        Inputs: `response`, `request_error`. Output: None.
        """
        self.response = response
        self.request_error = request_error
        self.closed = False

    def request(self, method, path):
        """Request the request for `_FakeConnection`.

        Inputs: `method`, `path` path. Output: None. Raises: request_error when validation or the called operation fails.
        """
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self):
        """Return the HTTP response.

        Inputs: none. Output: `self.response`.
        """
        return self.response

    def close(self):
        """Close `_FakeConnection`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


class _Cursor:
    """Test double for cursor behavior in this module."""

    def __init__(self, row):
        """Create `_Cursor` with `row`.

        Inputs: `row`. Output: None.
        """
        self.row = row
        self.executed = []

    def execute(self, query):
        """Execute `_Cursor`'s captured query or command.

        Inputs: `query`. Output: None.
        """
        self.executed.append(query)

    def fetchone(self):
        """Return one result row from `_Cursor`.

        Inputs: none. Output: `self.row`.
        """
        return self.row

    def __enter__(self):
        """Enter `_Cursor`'s context-managed fake resource.

        Inputs: none. Output: `self`.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Exit `_Cursor`'s context-managed fake resource.

        Inputs: `exc_type`, `exc`, `tb`. Output: bool.
        """
        return False


class _PgConnection:
    """Test double for pg connection behavior in this module."""

    def __init__(self, row):
        """Create `_PgConnection` with `row`.

        Inputs: `row`. Output: None.
        """
        self.row = row
        self.closed = False

    def cursor(self):
        """Return a database cursor.

        Inputs: none. Output: `_Cursor` result.
        """
        return _Cursor(self.row)

    def close(self):
        """Close `_PgConnection`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


def _result(check_id: str, label: str) -> DiagnosticCheckResult:
    """Return the result.

    Inputs: `check_id` (str), `label` (str). Output: `DiagnosticCheckResult`.
    """
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status="pass",
        duration_ms=1,
        summary=label,
        details="details",
    )


def test_environment_and_database_profile_helpers(monkeypatch):
    """Verify environment and database profile helpers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in environment and database profile helpers.
    AssertionError when validation or the called operation fails.
    """
    monkeypatch.setenv("ADMIN_TOOLS_PLUGIN_DB_HOST", "plugin-db")
    monkeypatch.setenv("ADMIN_TOOLS_PLUGIN_DB_PORT", "5544")
    monkeypatch.setenv("ADMIN_TOOLS_PLUGIN_DB_USER", "plugin-user")
    monkeypatch.setenv("ADMIN_TOOLS_PLUGIN_DB_PASSWORD", "plugin-pass")
    monkeypatch.setenv("ADMIN_TOOLS_PLUGIN_DB_NAME", "plugin-name")

    assert system_diagnostics._get_env("MISSING_ENV", "fallback") == "fallback"
    monkeypatch.setenv("FLOAT_ENV", "2.5")
    assert system_diagnostics._to_float_env("FLOAT_ENV", 1.0) == 2.5
    monkeypatch.setenv("PRIMARY_ENV", "")
    monkeypatch.setenv("SECONDARY_ENV", "value")
    assert (
        system_diagnostics._first_present_env(
            ("PRIMARY_ENV", "SECONDARY_ENV"), "fallback"
        )
        == "value"
    )
    profile = system_diagnostics._plugin_database_profile()
    assert profile == DatabaseRuntimeProfile(
        host="plugin-db",
        port=5544,
        user="plugin-user",
        password="plugin-pass",
        dbname="plugin-name",
    )

    monkeypatch.setenv("BROKEN_PORT", "bad")
    try:
        system_diagnostics._resolve_db_profile(
            host_names=("ADMIN_TOOLS_PLUGIN_DB_HOST",),
            port_names=("BROKEN_PORT",),
            user_names=("ADMIN_TOOLS_PLUGIN_DB_USER",),
            password_names=("ADMIN_TOOLS_PLUGIN_DB_PASSWORD",),
            db_names=("ADMIN_TOOLS_PLUGIN_DB_NAME",),
            default_host="database",
            default_port="5432",
            default_user="user",
            default_dbname="db",
        )
    except RuntimeError as exc:
        assert "Invalid PostgreSQL port value" in str(exc)
    else:
        raise AssertionError("expected invalid port runtime error")


def test_runtime_port_parser_rejects_non_numeric_and_out_of_range_values() -> None:
    """Confirm runtime port parser rejects non numeric and out of range values is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in runtime port parser rejects non numeric and out of range values.
    """
    for raw_port in ("bad", "70000"):
        try:
            system_diagnostics._parse_runtime_port(raw_port, ("TEST_PORT",))
        except RuntimeError as exc:
            assert raw_port in str(exc)
        else:
            raise AssertionError("expected invalid runtime port")


def test_docker_api_json_and_runtime_inspection_handle_socket_and_payload_cases(
    monkeypatch,
):
    """Verify docker API JSON and runtime inspection handle socket and payload cases result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in docker API JSON and runtime inspection handle socket and payload cases.
    """
    monkeypatch.setattr(system_diagnostics.os.path, "exists", lambda path: False)
    ok, payload, error = system_diagnostics._docker_api_json("/containers/json")
    assert ok is False
    assert payload is None
    assert "Docker socket not found" in error

    containers_payload = json.dumps(
        [
            {"Id": "old", "Created": 1, "Names": ["/old"]},
            {"Id": "new", "Created": 2, "Names": ["/new"]},
        ]
    ).encode("utf-8")
    inspect_payload = json.dumps(
        {
            "Name": "/new",
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
        }
    ).encode("utf-8")
    connections = [
        _FakeConnection(_FakeResponse(200, containers_payload)),
        _FakeConnection(_FakeResponse(200, inspect_payload)),
    ]

    monkeypatch.setattr(system_diagnostics.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        system_diagnostics,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: connections.pop(0),
    )

    runtime, error = system_diagnostics._inspect_docker_service_runtime("omeroserver")

    assert error == ""
    assert runtime == {
        "container_id": "new",
        "container_name": "new",
        "state": "running",
        "health": "healthy",
    }

    permission_connection = _FakeConnection(request_error=PermissionError("denied"))
    monkeypatch.setattr(
        system_diagnostics,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: permission_connection,
    )
    ok, payload, error = system_diagnostics._docker_api_json("/containers/json")
    assert ok is False
    assert payload is None
    assert "Permission denied accessing Docker socket" in error

    invalid_json_connection = _FakeConnection(_FakeResponse(200, b"not-json"))
    monkeypatch.setattr(
        system_diagnostics,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: invalid_json_connection,
    )
    ok, payload, error = system_diagnostics._docker_api_json("/containers/json")
    assert ok is False
    assert payload is None
    assert "invalid JSON" in error

    bad_status_connection = _FakeConnection(_FakeResponse(503, b"{}"))
    monkeypatch.setattr(
        system_diagnostics,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: bad_status_connection,
    )
    ok, payload, error = system_diagnostics._docker_api_json("/containers/json")
    assert ok is False
    assert payload is None
    assert "HTTP 503" in error


def test_sql_and_network_primitives_report_success_and_failure(monkeypatch):
    """Verify SQL and network primitives report success and failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in SQL and network primitives report success and failure.
    """

    def _psycopg2_single_value():
        """Return the psycopg2 single value.

        Inputs: none. Output: psycopg2 single value result.
        """
        return type(
            "Psycopg2",
            (),
            {"connect": staticmethod(lambda **kwargs: _PgConnection((1,)))},
        )()

    monkeypatch.setattr(
        system_diagnostics,
        "_load_psycopg2",
        _psycopg2_single_value,
    )
    value, error = system_diagnostics._execute_sql_sanity_query(
        DatabaseRuntimeProfile("database", 5432, "omero", "secret", "omero")
    )
    assert (value, error) == (1, "")

    monkeypatch.setattr(
        system_diagnostics.socket,
        "getaddrinfo",
        lambda host, port: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    resolved = system_diagnostics._resolve_hostname("dns", "Resolve host", "database")
    assert resolved.status == "pass"

    class _SocketContext:
        """Test double for socket context behavior in this module."""

        def __enter__(self):
            """Enter `_SocketContext`'s context-managed fake resource.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit `_SocketContext`'s context-managed fake resource.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

    monkeypatch.setattr(
        system_diagnostics.socket,
        "create_connection",
        lambda target, timeout: _SocketContext(),
    )
    tcp_pass = system_diagnostics._tcp_connect(
        "tcp", "Connect TCP", "database", 5432, 1.0
    )
    assert tcp_pass.status == "pass"

    monkeypatch.setattr(
        system_diagnostics.requests,
        "get",
        lambda url, timeout=1.0, allow_redirects=True: _FakeResponse(200, b""),
    )
    http_pass = system_diagnostics._http_probe(
        "http", "Probe HTTP", "https://omeroserver", 1.0
    )
    assert http_pass.status == "pass"

    monkeypatch.setattr(
        system_diagnostics.requests,
        "get",
        lambda url, timeout=1.0, allow_redirects=True: (_ for _ in ()).throw(
            requests.RequestException("offline")
        ),
    )
    http_fail = system_diagnostics._http_probe(
        "http", "Probe HTTP", "https://omeroserver", 1.0
    )
    assert http_fail.status == "fail"

    monkeypatch.setattr(
        system_diagnostics.socket,
        "create_connection",
        lambda target, timeout: (_ for _ in ()).throw(OSError("refused")),
    )
    tcp_fail = system_diagnostics._tcp_connect(
        "tcp", "Connect TCP", "database", 5432, 1.0
    )
    assert tcp_fail.status == "fail"

    monkeypatch.setattr(
        system_diagnostics.socket,
        "getaddrinfo",
        lambda host, port: (_ for _ in ()).throw(socket.gaierror("bad dns")),
    )
    dns_fail = system_diagnostics._resolve_hostname("dns", "Resolve host", "database")
    assert dns_fail.status == "fail"

    monkeypatch.setattr(
        system_diagnostics.requests,
        "get",
        lambda url, timeout=1.0, allow_redirects=True: _FakeResponse(503, b""),
    )
    http_warn = system_diagnostics._http_probe(
        "http", "Probe HTTP", "https://omeroserver", 1.0
    )
    assert http_warn.status == "warn"
    invalid_http = system_diagnostics._http_probe(
        "http", "Probe HTTP", "file:///tmp/not-allowed", 1.0
    )
    assert invalid_http.status == "fail"

    def _psycopg2_bad_value():
        """Return the psycopg2 bad value.

        Inputs: none. Output: psycopg2 bad value result.
        """
        return type(
            "Psycopg2",
            (),
            {"connect": staticmethod(lambda **kwargs: _PgConnection(("bad",)))},
        )()

    monkeypatch.setattr(
        system_diagnostics,
        "_load_psycopg2",
        _psycopg2_bad_value,
    )
    value, error = system_diagnostics._execute_sql_sanity_query(
        DatabaseRuntimeProfile("database", 5432, "omero", "secret", "omero")
    )
    assert value is None
    assert "unexpected payload" in error


def test_diagnostic_aggregators_return_expected_checks(monkeypatch):
    """Verify diagnostic aggregators return expected checks.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in diagnostic aggregators return expected checks.
    """
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_SERVER_HOST", "omeroserver")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_BLITZ_PORT", "4064")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_SECURE_PORT", "4063")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_WEB_HOST", "omeroweb")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_WEB_PORT", "4090")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_WEB_PATH", "/webclient/")
    monkeypatch.setattr(
        system_diagnostics,
        "_resolve_hostname",
        lambda *args: _result(args[0], args[1]),
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_tcp_connect",
        lambda *args: _result(args[0], args[1]),
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_http_probe",
        lambda *args: _result(args[0], args[1]),
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_compose_ps_health",
        lambda *args: _result(args[0], args[1]),
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_direct_pg_test",
        lambda *args: _result(args[0], args[1]),
    )
    monkeypatch.setattr(
        system_diagnostics,
        "_omero_database_profile",
        lambda: DatabaseRuntimeProfile("database", 5432, "omero", "secret", "omero"),
    )

    core_checks = system_diagnostics._run_omero_server_core()
    db_checks = system_diagnostics._run_database_checks(
        "omero_database",
        "OMERO database",
        "database",
        system_diagnostics._omero_database_profile,
    )

    assert len(core_checks) == 5
    assert len(db_checks) == 4
    assert core_checks[0].check_id == "omero_host_dns"
    assert db_checks[-1].check_id == "omero_database_sql"


def test_omero_server_core_reports_missing_runtime_config(monkeypatch):
    """Verify OMERO server core reports missing runtime config.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in OMERO server core reports missing runtime config.
    """
    for name in (
        "ADMIN_TOOLS_OMERO_SERVER_HOST",
        "OMEROHOST",
        "CONFIG_omero_host",
        "ADMIN_TOOLS_OMERO_BLITZ_PORT",
        "OMERO_PORT",
        "OMERO_CLI_PORT",
        "ADMIN_TOOLS_OMERO_SECURE_PORT",
        "OMERO_SECURE_PORT",
        "ADMIN_TOOLS_OMERO_WEB_HOST",
        "ADMIN_TOOLS_OMERO_WEB_PORT",
        "CONFIG_omero_web_application__server_port",
        "ADMIN_TOOLS_OMERO_WEB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    checks = system_diagnostics._run_omero_server_core()

    assert len(checks) == 1
    assert checks[0].check_id == "omero_runtime_config"
    assert checks[0].status == "fail"
    assert "Missing required runtime environment" in checks[0].details


def test_omero_server_core_reports_invalid_runtime_ports(monkeypatch):
    """Verify OMERO server core reports invalid runtime ports.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in OMERO server core reports invalid runtime ports.
    """
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_SERVER_HOST", "omeroserver")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_BLITZ_PORT", "bad")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_SECURE_PORT", "4063")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_WEB_HOST", "omeroweb")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_WEB_PORT", "4090")
    monkeypatch.setenv("ADMIN_TOOLS_OMERO_WEB_PATH", "/webclient/")

    checks = system_diagnostics._run_omero_server_core()

    assert checks[0].check_id == "omero_runtime_config"
    assert checks[0].status == "fail"
    assert "Invalid OMERO runtime diagnostic port configuration" in checks[0].summary
