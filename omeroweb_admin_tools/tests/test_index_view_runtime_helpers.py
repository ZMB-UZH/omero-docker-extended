from __future__ import annotations

import inspect
import json
import socket
from http.client import HTTPMessage
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from django.http import HttpResponse
from django.test import RequestFactory

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.views import index_view

PROMETHEUS_URL = "https://prometheus.example.test:9090"
LOKI_URL = "https://loki.example.test:3100"


class _HttpResponseStub:
    """Represent HTTP response stub."""

    def __init__(self, status: int, payload: bytes):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        """Return read."""
        return self._payload


class _RequestsResponseStub:
    """Represent requests response stub."""

    def __init__(
        self,
        status_code: int,
        *,
        payload: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.content = payload
        self.headers = headers or {}
        raw_headers = HTTPMessage()
        for key, value in self.headers.items():
            raw_headers.add_header(key, value)
        self.raw = SimpleNamespace(headers=raw_headers)

    def json(self):
        """Handle JSON."""
        return json.loads(self.content.decode("utf-8"))


class _DockerConnection:
    """Represent docker connection."""

    def __init__(self, response=None, request_error: Exception | None = None):
        self._response = response
        self._request_error = request_error
        self.requested = None
        self.closed = False

    def request(self, method, path):
        """Handle request."""
        if self._request_error is not None:
            raise self._request_error
        self.requested = (method, path)

    def getresponse(self):
        """Return getresponse."""
        return self._response

    def close(self):
        """Handle close."""
        self.closed = True


def _payload(response):
    """Handle payload."""
    return json.loads(response.content.decode("utf-8"))


def test_env_probe_and_prometheus_helpers_cover_runtime_failures(monkeypatch) -> None:
    """Verify test env probe and prometheus helpers cover r behavior."""
    monkeypatch.setenv("ADMIN_TOOLS_SAMPLE_INT", "12")
    assert index_view._to_int_env("ADMIN_TOOLS_SAMPLE_INT", 5) == 12
    monkeypatch.setenv("ADMIN_TOOLS_SAMPLE_INT", "bad")
    assert index_view._to_int_env("ADMIN_TOOLS_SAMPLE_INT", 5) == 5

    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=2.5, allow_redirects=True, params=None: (
            _RequestsResponseStub(204)
        ),
    )
    assert index_view._probe_http_url("https://grafana.example.org") == {
        "ok": True,
        "status": 204,
        "error": "",
    }

    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=2.5, allow_redirects=True, params=None: (
            _RequestsResponseStub(503)
        ),
    )
    assert index_view._probe_http_url("https://grafana.example.org") == {
        "ok": False,
        "status": 503,
        "error": "",
    }

    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=2.5, allow_redirects=True, params=None: (
            _ for _ in ()
        ).throw(requests.ConnectionError("connection refused")),
    )
    assert index_view._probe_http_url("https://grafana.example.org") == {
        "ok": False,
        "status": 0,
        "error": "Connection failed",
    }

    query_payload = {
        "data": {"result": [{"value": [1711843200, "42.5"]}]},
    }
    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=5.0, allow_redirects=True, params=None: (
            _RequestsResponseStub(
                200,
                payload=json.dumps(query_payload).encode("utf-8"),
            )
        ),
    )
    assert index_view._prometheus_instant_query(PROMETHEUS_URL, "up") == 42.5

    seen = []

    def _query_metric(_base_url, expr):
        """Handle query metric."""
        seen.append(expr)
        if "network_receive" in expr:
            raise RuntimeError("probe failed")
        return 7.0

    monkeypatch.setattr(index_view, "_prometheus_instant_query", _query_metric)
    metrics = index_view._collect_system_metrics(PROMETHEUS_URL)
    assert metrics["cpu_usage_percent"] == 7.0
    assert metrics["network_receive_bps"] is None
    assert metrics["network_transmit_bps"] == 7.0
    assert len(seen) == 5


def test_internal_service_base_url_builds_valid_defaults(monkeypatch) -> None:
    """Verify test internal service base URL builds valid d behavior."""
    monkeypatch.delenv("ADMIN_TOOLS_GRAFANA_URL", raising=False)
    monkeypatch.delenv("ADMIN_TOOLS_PROMETHEUS_URL", raising=False)
    monkeypatch.delenv("ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME", raising=False)
    default_url = index_view._internal_service_base_url(
        "ADMIN_TOOLS_PROMETHEUS_URL",
        default_host="prometheus",
        default_port=9090,
    )
    parsed_default = urlsplit(default_url)
    assert parsed_default.scheme == "http"
    assert parsed_default.netloc == "prometheus:9090"

    monkeypatch.setenv("ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME", "https")
    assert (
        index_view._internal_service_base_url(
            "ADMIN_TOOLS_GRAFANA_URL",
            default_host="grafana",
            default_port=3000,
        )
        == "https://grafana:3000"
    )

    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_URL", "https://grafana.internal:3443")
    assert (
        index_view._internal_service_base_url(
            "ADMIN_TOOLS_GRAFANA_URL",
            default_host="grafana",
            default_port=3000,
        )
        == "https://grafana.internal:3443"
    )


def test_collect_recently_seen_services_and_parse_since_ns() -> None:
    """Verify test collect recently seen services and parse behavior."""
    response = _RequestsResponseStub(
        200,
        payload=json.dumps(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {
                                "container_label_com_docker_compose_service": "redis"
                            }
                        },
                        {
                            "metric": {
                                "container_label_com_docker_compose_service": "database"
                            }
                        },
                    ]
                },
            }
        ).encode("utf-8"),
    )
    original = index_view.requests.get
    index_view.requests.get = (
        lambda url, timeout=5.0, allow_redirects=True, params=None: response
    )
    try:
        assert index_view._collect_recently_seen_services(PROMETHEUS_URL) == [
            "database",
            "redis",
        ]
    finally:
        index_view.requests.get = original

    assert index_view._parse_since_ns("1711843200000000000") == 1711843200000000000
    assert index_view._parse_since_ns("2026-03-30T06:56:57Z") > 0


def test_logs_view_and_internal_log_labels_cover_configuration_paths(
    monkeypatch,
) -> None:
    """Verify test logs view and internal log labels cover behavior."""
    request = RequestFactory().get("/admin_tools/logs/")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )

    monkeypatch.setattr(
        index_view,
        "optional_log_config",
        lambda: LogConfig(
            loki_url=LOKI_URL,
            lookback_seconds=60,
            max_entries=100,
            timeout_seconds=5.0,
            cache_max_bytes=1024,
            internal_file_batch_size=12,
            max_parallel_queries=4,
        ),
    )
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: HttpResponse(
            json.dumps(context, sort_keys=True),
            content_type="application/json",
        ),
    )

    response = index_view.logs_view(request, conn=None)
    assert response.status_code == 200
    payload = _payload(response)
    assert json.loads(payload["log_config"])["loki_url"] == LOKI_URL
    assert payload["table_row_cap"] == index_view.LOG_TABLE_ROW_CAP
    assert payload["log_sources"][0]["container"] == "omeroserver"

    monkeypatch.setattr(index_view, "_require_root_user", lambda request, conn: None)
    monkeypatch.setattr(index_view, "optional_log_config", lambda: None)
    invalid_response = index_view.internal_log_labels(
        RequestFactory().get(
            "/admin_tools/internal-log-labels/",
            data={"service": "bad-service"},
        ),
        conn=None,
    )
    assert invalid_response.status_code == 503

    monkeypatch.setattr(
        index_view,
        "optional_log_config",
        lambda: LogConfig(
            loki_url=LOKI_URL,
            lookback_seconds=60,
            max_entries=100,
            timeout_seconds=5.0,
            cache_max_bytes=1024,
            internal_file_batch_size=12,
            max_parallel_queries=4,
        ),
    )
    monkeypatch.setattr(
        index_view,
        "fetch_internal_log_labels",
        lambda config, service: (_ for _ in ()).throw(RuntimeError("backend exploded")),
    )
    valid_response = index_view.internal_log_labels(
        RequestFactory().get(
            "/admin_tools/internal-log-labels/",
            data={"service": "omeroweb_internal"},
        ),
        conn=None,
    )
    assert valid_response.status_code == 200
    assert _payload(valid_response) == {"service": "omeroweb_internal", "labels": []}


def test_docker_compose_and_api_helpers_cover_json_and_socket_errors(
    monkeypatch,
    tmp_path,
) -> None:
    """Verify test docker compose and API helpers cover JSO behavior."""
    monkeypatch.setattr(
        index_view.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            index_view.subprocess.CalledProcessError(1, ["docker"])
        ),
    )
    assert index_view._docker_compose_json(["docker", "compose", "ps"]) is None

    monkeypatch.setattr(
        index_view.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="{broken"),
    )
    assert index_view._docker_compose_json(["docker", "compose", "ps"]) is None

    socket_path = tmp_path / "docker.sock"
    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", str(socket_path))
    monkeypatch.setattr(index_view.os.path, "exists", lambda path: True)

    ok_connection = _DockerConnection(
        _HttpResponseStub(200, b'{"containers": ["omeroserver"]}')
    )
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: ok_connection,
    )
    assert index_view._docker_api_json("/containers/json") == {
        "containers": ["omeroserver"]
    }
    assert ok_connection.requested == ("GET", "/containers/json")
    assert ok_connection.closed is True

    denied_connection = _DockerConnection(request_error=PermissionError("denied"))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: denied_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None

    bad_status_connection = _DockerConnection(_HttpResponseStub(503, b"{}"))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: bad_status_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None

    invalid_json_connection = _DockerConnection(_HttpResponseStub(200, b"{broken"))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: invalid_json_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None


def test_docker_diagnostics_and_compose_health_helpers_cover_inspection_paths(
    monkeypatch,
) -> None:
    """Verify test docker diagnostics and compose health he behavior."""
    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    monkeypatch.setattr(index_view.os.path, "exists", lambda path: True)
    monkeypatch.setattr(index_view.os, "access", lambda path, mode: True)
    monkeypatch.setattr(index_view.os, "getuid", lambda: 1001)
    monkeypatch.setattr(index_view.os, "getgroups", lambda: [998, 999])
    monkeypatch.setattr(
        index_view.os,
        "stat",
        lambda path: SimpleNamespace(st_uid=0, st_gid=999, st_mode=0o140660),
    )

    def _docker_api(path, timeout_seconds=3.0):
        """Handle docker API."""
        if path == "/containers/json?all=1":
            return [
                {
                    "Id": "db1",
                    "Labels": {"com.docker.compose.service": "database"},
                    "State": "running",
                    "Status": "Up 5 minutes (healthy)",
                },
                {
                    "Id": "cache1",
                    "Labels": {"com.docker.compose.service": "redis"},
                    "State": "running",
                    "Status": "Up 1 minute",
                },
            ]
        if path == "/containers/cache1/json":
            return {
                "Config": {"Healthcheck": {"Test": ["CMD", "redis-cli", "ping"]}},
                "State": {"Health": {"Status": "starting"}},
            }
        raise AssertionError(f"unexpected docker api path: {path}")

    monkeypatch.setattr(index_view, "_docker_api_json", _docker_api)

    diagnostics = index_view._diagnose_docker_health()
    health_config, runtime = index_view._load_compose_health_data()

    assert diagnostics["api_reachable"] is True
    assert diagnostics["containers_with_health"] == 1
    assert diagnostics["process_in_socket_group"] is True
    assert diagnostics["sample_statuses"][0]["parsed_health"] == "healthy"

    assert health_config == {"database": True, "redis": True}
    assert runtime == {
        "database": {"state": "running", "health": "healthy"},
        "redis": {"state": "running", "health": "starting"},
    }

    monkeypatch.setattr(index_view, "_docker_api_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        index_view, "_load_compose_healthcheck_config", lambda: {"grafana": True}
    )
    monkeypatch.setattr(
        index_view,
        "_load_compose_runtime_health",
        lambda: {"grafana": {"state": "running", "health": "healthy"}},
    )
    assert index_view._load_compose_health_data() == (
        {"grafana": True},
        {"grafana": {"state": "running", "health": "healthy"}},
    )


def test_unix_socket_connection_and_docker_runtime_helpers_cover_remaining_edges(
    monkeypatch,
    tmp_path,
) -> None:
    """Verify test unix socket connection and docker runtim behavior."""
    events = {}
    socket_path = tmp_path / "docker.sock"

    class _SocketStub:
        """Represent socket stub."""

        def __init__(self, family, sock_type):
            events["created"] = (family, sock_type)

        @staticmethod
        def settimeout(timeout):
            """Store settimeout."""
            events["timeout"] = timeout

        @staticmethod
        def connect(path):
            """Handle connect."""
            events["path"] = path

    monkeypatch.setattr(index_view.socket, "socket", _SocketStub)
    connection = index_view._UnixSocketHTTPConnection(str(socket_path), timeout=4.5)
    connection.connect()
    assert events == {
        "created": (socket.AF_UNIX, socket.SOCK_STREAM),
        "timeout": 4.5,
        "path": str(socket_path),
    }

    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", "/var/run/docker.sock")
    monkeypatch.setattr(index_view.os.path, "exists", lambda path: True)
    monkeypatch.setattr(index_view.os, "access", lambda path, mode: True)
    monkeypatch.setattr(
        index_view.os,
        "getuid",
        lambda: (_ for _ in ()).throw(RuntimeError("uid failed")),
    )
    monkeypatch.setattr(
        index_view.os,
        "stat",
        lambda path: (_ for _ in ()).throw(OSError("stat failed")),
    )
    monkeypatch.setattr(
        index_view, "_docker_api_json", lambda *args, **kwargs: {"ok": True}
    )
    diagnostics = index_view._diagnose_docker_health()
    assert diagnostics["current_user"] == "error"
    assert diagnostics["socket_stat"] == "stat unavailable"
    assert diagnostics["api_error"] == "unexpected type: dict"

    monkeypatch.setattr(index_view, "_docker_api_json", lambda *args, **kwargs: [42])
    diagnostics = index_view._diagnose_docker_health()
    assert diagnostics["api_reachable"] is True
    assert diagnostics["sample_statuses"] == []

    monkeypatch.setattr(
        index_view,
        "_docker_api_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    diagnostics = index_view._diagnose_docker_health()
    assert diagnostics["api_error"] == "Docker API request failed"

    def docker_api(path, timeout_seconds=3.0):
        """Handle docker API."""
        if path == "/containers/json?all=1":
            return [
                42,
                {"Labels": "bad"},
                {"Labels": {}, "State": "running", "Status": "Up"},
                {
                    "Labels": {"com.docker.compose.service": "worker"},
                    "State": "running",
                    "Status": "Up",
                },
                {
                    "Id": "db1",
                    "Labels": {"com.docker.compose.service": "db"},
                    "State": "running",
                    "Status": "Up",
                },
            ]
        if path == "/containers/db1/json":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(index_view, "_docker_api_json", docker_api)
    health_config, runtime = index_view._load_compose_health_data()
    assert health_config == {"worker": False, "db": False}
    assert runtime == {
        "worker": {"state": "running", "health": ""},
        "db": {"state": "running", "health": ""},
    }

    monkeypatch.setattr(index_view, "_docker_compose_json", lambda command: [])
    assert index_view._load_compose_healthcheck_config() == {}
    monkeypatch.setattr(
        index_view,
        "_docker_compose_json",
        lambda command: {"services": []},
    )
    assert index_view._load_compose_healthcheck_config() == {}

    monkeypatch.setattr(index_view, "_docker_compose_json", lambda command: {})
    assert index_view._load_compose_runtime_health() == {}
    monkeypatch.setattr(
        index_view,
        "_docker_compose_json",
        lambda command: [
            "bad",
            {"Service": "", "State": "running", "Health": "healthy"},
            {"Service": "db", "State": "running", "Health": "healthy"},
        ],
    )
    assert index_view._load_compose_runtime_health() == {
        "db": {"state": "running", "health": "healthy"}
    }


def test_index_helper_functions_cover_render_permissions_and_time_parsing(
    monkeypatch,
) -> None:
    """Verify test index helper functions cover render perm behavior."""
    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: SimpleNamespace(
            content=template.encode("utf-8")
        ),
    )
    response = index_view.index(RequestFactory().get("/admin/"), conn=None)
    assert response.content.decode("utf-8") == "omeroweb_admin_tools/index.html"

    assert index_view._call_admin_listing(SimpleNamespace(), "missing") == []
    assert index_view._first_admin_listing(SimpleNamespace(), ("missing",)) == []
    assert (
        index_view._build_public_service_url(
            "https://grafana:3000",
            "https",
            "[2001:db8::1]",
            3000,
        )
        == "https://[2001:db8::1]:3000"
    )

    class _Permissions:
        """Represent permissions."""

        @staticmethod
        def isGroupRead():
            """Handle is group read."""
            return True

        @staticmethod
        def isGroupWrite():
            """Handle is group write."""
            return True

        @staticmethod
        def isGroupAnnotate():
            """Handle is group annotate."""
            return False

    def _read_write_group_details():
        """Handle read write group details."""
        return SimpleNamespace(getPermissions=_Permissions)

    read_write_group = SimpleNamespace(getDetails=_read_write_group_details)
    assert index_view._safe_group_permission_label(read_write_group) == "Read-write"

    broken_group = SimpleNamespace(
        getDetails=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert index_view._safe_group_permission_label(broken_group) == "Private"

    with pytest.raises(ValueError, match="empty since value"):
        index_view._parse_since_ns(" ")
    assert index_view._parse_since_ns("2026-03-30T06:56:57") > 0


def test_refactored_monitoring_helpers_preserve_guard_branch_contracts(
    monkeypatch,
) -> None:
    """Verify test refactored monitoring helpers preserve g behavior."""
    headers = {"Origin": "https://omero.example.org"}
    index_view._rewrite_origin_headers(headers, "not-a-url")
    assert headers == {"Origin": "https://omero.example.org"}
    assert (
        index_view._unsupported_event_stream_response(
            "api/v1/notifications/live",
            "application/json",
            "https://prometheus.example.test/api/v1/notifications/live",
        )
        is None
    )

    entries = [
        SimpleNamespace(container="omeroserver", level="error", message="failure"),
        SimpleNamespace(container="omeroweb", level="info", message="ready"),
    ]
    assert index_view._filter_log_entries(entries, level="error", query="") == [
        entries[0]
    ]

    diagnostics = {"socket_exists": False, "socket_stat": ""}
    index_view._docker_socket_diagnostics(diagnostics, "/missing.sock", [998])
    assert diagnostics == {"socket_exists": False, "socket_stat": ""}

    assert index_view._inspected_health_status({"State": {"Health": "bad-shape"}}) == ""
    assert (
        index_view._inspected_health_status({"State": {"Health": {"Status": "paused"}}})
        == ""
    )

    calls = []

    def _docker_api(path, timeout_seconds=3.0):
        """Handle docker API."""
        calls.append((path, timeout_seconds))
        return {"Config": {}, "State": {"Health": {"Status": "healthy"}}}

    monkeypatch.setattr(index_view, "_docker_api_json", _docker_api)
    runtime_health = {"redis": {"state": "running", "health": ""}}
    healthcheck_config: dict[str, bool] = {}
    index_view._apply_container_inspect_health(
        "redis",
        "redis1",
        healthcheck_config,
        runtime_health,
    )
    assert calls == [("/containers/redis1/json", 3.0)]
    assert healthcheck_config == {}
    assert runtime_health == {"redis": {"state": "running", "health": ""}}

    assert (
        index_view._public_monitoring_base_url(
            configured_public_url="",
            internal_url="https://grafana.example.org",
            request_scheme="https",
            request_host="omero.example.org",
            host_port=3000,
            proxied=False,
        )
        == ""
    )


def test_logs_compose_prometheus_and_proxy_helpers_cover_remaining_runtime_guards(
    monkeypatch,
    tmp_path,
) -> None:
    """Verify test logs compose prometheus and proxy helper behavior."""
    root_error = HttpResponse("root-only", status=403)
    monkeypatch.setattr(
        index_view, "_require_root_user", lambda request, conn: root_error
    )
    assert (
        inspect.unwrap(index_view.logs_data)(
            RequestFactory().get("/admin/logs/"),
            conn=None,
        )
        is root_error
    )
    assert (
        inspect.unwrap(index_view.internal_log_labels)(
            RequestFactory().get(
                "/admin/internal/", data={"service": "omeroweb_internal"}
            ),
            conn=None,
        )
        is root_error
    )

    monkeypatch.setattr(index_view, "_require_root_user", lambda request, conn: None)
    monkeypatch.setattr(index_view, "optional_log_config", lambda: None)
    assert (
        inspect.unwrap(index_view.logs_data)(
            RequestFactory().get("/admin/logs/"),
            conn=None,
        ).status_code
        == 503
    )

    compose_path = tmp_path / "compose.yml"
    compose_path.write_text(
        "name: demo\nservices:\n  omeroweb:\n    image: web\nnetworks:\n  default:\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(index_view, "_REPO_ROOT", str(tmp_path))
    assert index_view._load_compose_service_names("compose.yml") == ["omeroweb"]

    monkeypatch.setattr(
        index_view.process_utils,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    assert index_view._docker_compose_json(["docker", "compose", "ps"]) is None
    monkeypatch.setattr(
        index_view.process_utils,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="   "),
    )
    assert index_view._docker_compose_json(["docker", "compose", "ps"]) is None

    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", str(tmp_path / "docker.sock"))
    monkeypatch.setattr(index_view.os.path, "exists", lambda path: True)
    empty_payload_connection = _DockerConnection(_HttpResponseStub(200, b""))
    monkeypatch.setattr(
        index_view,
        "_UnixSocketHTTPConnection",
        lambda socket_path, timeout=3.0: empty_payload_connection,
    )
    assert index_view._docker_api_json("/containers/json") is None

    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=5.0, allow_redirects=True, params=None: (
            _RequestsResponseStub(
                200,
                payload=json.dumps({"data": {"result": []}}).encode("utf-8"),
            )
        ),
    )
    assert index_view._prometheus_instant_query(PROMETHEUS_URL, "up") is None
    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=5.0, allow_redirects=True, params=None: (
            _RequestsResponseStub(
                200,
                payload=json.dumps(
                    {"data": {"result": [{"value": [1711843200]}]}}
                ).encode("utf-8"),
            )
        ),
    )
    assert index_view._prometheus_instant_query(PROMETHEUS_URL, "up") is None
    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda url, timeout=5.0, allow_redirects=True, params=None: (
            _RequestsResponseStub(
                200,
                payload=json.dumps({"status": "error", "data": {"result": []}}).encode(
                    "utf-8"
                ),
            )
        ),
    )
    assert index_view._collect_recently_seen_services(PROMETHEUS_URL) == []

    monkeypatch.setattr(
        index_view,
        "_internal_service_base_url",
        lambda *args, **kwargs: "https://service",
    )
    monkeypatch.setattr(
        index_view, "_build_proxy_backend_urls", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        index_view, "_normalize_proxy_request_target", lambda subpath: ("dash", "")
    )

    with pytest.raises(RuntimeError, match="No Grafana backend URLs configured"):
        inspect.unwrap(index_view.grafana_proxy)(
            RequestFactory().get("/admin/grafana/dash"),
            "dash",
            conn=None,
        )

    with pytest.raises(RuntimeError, match="No Prometheus backend URLs configured"):
        inspect.unwrap(index_view.prometheus_proxy)(
            RequestFactory().get("/admin/prometheus/dash"),
            "dash",
            conn=None,
        )


def test_docker_api_json_returns_none_when_socket_missing(
    monkeypatch, tmp_path
) -> None:
    """_docker_api_json returns None when the Docker socket does not exist."""
    monkeypatch.setenv("ADMIN_TOOLS_DOCKER_SOCKET", str(tmp_path / "missing.sock"))
    result = index_view._docker_api_json("/containers/json")
    assert result is None


def test_diagnose_docker_health_reports_api_none(monkeypatch) -> None:
    """_diagnose_docker_health sets api_error when _docker_api_json returns None."""
    monkeypatch.setattr(index_view, "_docker_api_json", lambda *a, **kw: None)
    diag = index_view._diagnose_docker_health()
    assert diag["api_error"] == "API returned None (connection or permission error)"


def test_diagnose_docker_health_handles_unknown_uid(monkeypatch) -> None:
    """_diagnose_docker_health reports uid when pwd.getpwuid raises KeyError."""
    import pwd

    monkeypatch.setattr(
        pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid))
    )
    monkeypatch.setattr(index_view, "_docker_api_json", lambda *a, **kw: [])
    diag = index_view._diagnose_docker_health()
    assert diag["current_user"].startswith("uid=")
