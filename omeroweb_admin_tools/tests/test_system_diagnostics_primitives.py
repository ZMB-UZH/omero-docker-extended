from __future__ import annotations

import json
import socket
import urllib.error

from omeroweb_admin_tools.services import system_diagnostics
from omeroweb_admin_tools.services.system_diagnostics import (
    DatabaseRuntimeProfile,
    DiagnosticCheckResult,
)


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, response=None, *, request_error=None):
        self.response = response
        self.request_error = request_error
        self.closed = False

    def request(self, method, path):
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, query):
        self.executed.append(query)

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _PgConnection:
    def __init__(self, row):
        self.row = row
        self.closed = False

    def cursor(self):
        return _Cursor(self.row)

    def close(self):
        self.closed = True


def _result(check_id: str, label: str) -> DiagnosticCheckResult:
    return DiagnosticCheckResult(
        check_id=check_id,
        label=label,
        status="pass",
        duration_ms=1,
        summary=label,
        details="details",
    )


def test_environment_and_database_profile_helpers(monkeypatch):
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


def test_docker_api_json_and_runtime_inspection_handle_socket_and_payload_cases(
    monkeypatch,
):
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
    def _psycopg2_single_value():
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
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
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
        system_diagnostics.urllib.request,
        "urlopen",
        lambda request, timeout=1.0: _FakeResponse(200, b""),
    )
    http_pass = system_diagnostics._http_probe(
        "http", "Probe HTTP", "https://omeroserver", 1.0
    )
    assert http_pass.status == "pass"

    monkeypatch.setattr(
        system_diagnostics.urllib.request,
        "urlopen",
        lambda request, timeout=1.0: (_ for _ in ()).throw(
            urllib.error.URLError("offline")
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
        system_diagnostics.urllib.request,
        "urlopen",
        lambda request, timeout=1.0: _FakeResponse(503, b""),
    )
    http_warn = system_diagnostics._http_probe(
        "http", "Probe HTTP", "https://omeroserver", 1.0
    )
    assert http_warn.status == "warn"

    def _psycopg2_bad_value():
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
