from __future__ import annotations

import json
from http.client import HTTPMessage
from types import SimpleNamespace

from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory

from omeroweb_admin_tools.views.index_view import (
    logs_data,
    resource_monitoring_data,
    _build_public_service_url,
    _build_target_service_status,
    _is_internal_hostname,
    _is_behind_reverse_proxy,
    _load_compose_service_names,
    _normalize_proxy_request_target,
    _proxy_http_request,
    _build_proxy_backend_urls,
    _cookie_path_for_proxy,
    _origin_from_url,
    _grafana_proxy_home_fallback_response,
    _rewrite_proxied_location,
)


def _make_headers(d: dict) -> HTTPMessage:
    """Build an HTTPMessage from a plain dict for test stubs."""
    msg = HTTPMessage()
    for key, value in d.items():
        msg[key] = value
    return msg


class _RequestsResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        payload: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = payload
        self.raw = SimpleNamespace(headers=_make_headers(self.headers))

    def json(self):
        return json.loads(self.content.decode("utf-8"))


def test_load_compose_service_names_reads_service_block(tmp_path, monkeypatch) -> None:
    compose_text = """
services:
  app:
    image: test
  db:
    image: postgres
networks:
  default:
""".strip()
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(compose_text, encoding="utf-8")

    names = _load_compose_service_names(str(compose_file))

    assert names == ["app", "db"]


def test_build_target_service_status_prefers_up() -> None:
    active_targets = [
        {"labels": {"job": "app"}, "health": "down"},
        {
            "labels": {"container_label_com_docker_compose_service": "app"},
            "health": "up",
        },
        {
            "discoveredLabels": {
                "__meta_docker_container_label_com_docker_compose_service": "db"
            },
            "health": "unknown",
        },
    ]

    statuses = _build_target_service_status(active_targets, ["app", "db", "redis"])

    assert statuses == [
        {"service": "app", "health": "up", "state": "unknown", "healthcheck": "none"},
        {
            "service": "db",
            "health": "unknown",
            "state": "unknown",
            "healthcheck": "none",
        },
        {
            "service": "redis",
            "health": "unknown",
            "state": "unknown",
            "healthcheck": "none",
        },
    ]


def test_build_target_service_status_resolves_container_name_variants() -> None:
    active_targets = [
        {
            "discoveredLabels": {
                "__meta_docker_container_name": "/omero_node-exporter_1"
            },
            "health": "up",
        },
        {
            "labels": {"job": "prometheus:9090"},
            "health": "down",
        },
    ]

    statuses = _build_target_service_status(
        active_targets,
        ["node-exporter", "prometheus"],
    )

    assert statuses == [
        {
            "service": "node-exporter",
            "health": "up",
            "state": "unknown",
            "healthcheck": "none",
        },
        {
            "service": "prometheus",
            "health": "down",
            "state": "unknown",
            "healthcheck": "none",
        },
    ]


def test_build_target_service_status_uses_recent_container_samples() -> None:
    active_targets = []

    statuses = _build_target_service_status(
        active_targets,
        ["database", "redis"],
        recently_seen_services=["database"],
    )

    assert statuses == [
        {
            "service": "database",
            "health": "up",
            "state": "unknown",
            "healthcheck": "none",
        },
        {
            "service": "redis",
            "health": "unknown",
            "state": "unknown",
            "healthcheck": "none",
        },
    ]


def test_origin_from_url_normalizes_scheme_and_host() -> None:
    assert _origin_from_url("https://grafana:3000/path?q=1") == "https://grafana:3000"
    assert _origin_from_url("https://example.org") == "https://example.org"
    assert _origin_from_url("not-a-url") == ""


def test_proxy_http_request_rewrites_origin_headers_when_enabled(monkeypatch) -> None:
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(
            200,
            headers={"Content-Type": "application/json"},
            payload=b'{"status":"ok"}',
        )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        fake_request,
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {
            "Origin": "https://omero.example.org",
            "Referer": "https://omero.example.org/omeroweb_admin_tools/resource-monitoring/",
        }

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "api/user",
        rewrite_origin_headers=True,
    )

    assert response.status_code == 200
    assert captured["method"] == "GET"
    assert captured["url"] == "https://grafana:3000/api/user"
    assert captured["headers"]["Origin"] == "https://grafana:3000"
    assert captured["headers"]["Referer"] == "https://grafana:3000/"


def test_proxy_http_request_forwards_post_body(monkeypatch) -> None:
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        captured["method"] = method
        captured["data"] = data
        captured["timeout"] = timeout
        return _RequestsResponse(
            200,
            headers={"Content-Type": "application/json"},
            payload=b'{"status":"ok"}',
        )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        fake_request,
    )

    class DummyDjangoRequest:
        method = "POST"
        body = b'{"query":"up"}'
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

    django_request = DummyDjangoRequest()

    response = _proxy_http_request(
        django_request,
        "https://grafana:3000",
        "api/ds/query",
        "orgId=1",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}'
    assert captured == {
        "method": "POST",
        "data": b'{"query":"up"}',
        "timeout": 10.0,
    }


def test_proxy_http_request_forwards_auth_and_cookie_headers(monkeypatch) -> None:
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(
            200,
            headers={
                "Content-Type": "application/json",
                "Set-Cookie": "grafana_session=abc123; Path=/; HttpOnly",
            },
            payload=b'{"status":"ok"}',
        )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        fake_request,
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer test-token",
            "Cookie": "grafana_session=existing",
            "Origin": "https://omero.example.org",
            "Referer": "https://omero.example.org/omeroweb_admin_tools/resource-monitoring/",
        }

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "api/user",
    )

    assert response.status_code == 200
    assert "grafana_session" in response.cookies
    assert response.cookies["grafana_session"].value == "abc123"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["Cookie"] == "grafana_session=existing"
    assert captured["headers"]["Origin"] == "https://omero.example.org"
    assert (
        captured["headers"]["Referer"]
        == "https://omero.example.org/omeroweb_admin_tools/resource-monitoring/"
    )


def test_normalize_proxy_request_target_rejects_traversal() -> None:
    try:
        _normalize_proxy_request_target("../api/admin")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected traversal target to be rejected")


def test_normalize_proxy_request_target_strips_absolute_url_to_safe_path() -> None:
    path, query = _normalize_proxy_request_target(
        "https://grafana.example.org//api/../api/search?orgId=1"
    )

    assert path == "api/search"
    assert query == "orgId=1"


def test_proxy_http_request_rewrites_relative_location_header(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            _RequestsResponse(
                302,
                headers={
                    "Content-Type": "text/plain",
                    "Location": "/d/omero-infrastructure",
                },
                payload=b"redirect",
            )
        ),
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "d/omero-infrastructure",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 302
    assert (
        response["Location"]
        == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure"
    )


def test_rewrite_proxied_location_blocks_external_redirects() -> None:
    location = _rewrite_proxied_location(
        "https://evil.example.org/steal",
        "https://grafana:3000",
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert location == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"


def test_proxy_http_request_rewrites_non_root_relative_location_header(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            _RequestsResponse(
                302,
                headers={"Content-Type": "text/plain", "Location": "login"},
                payload=b"redirect",
            )
        ),
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 302
    assert (
        response["Location"]
        == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/login"
    )


def test_proxy_http_request_rejects_traversal_before_backend_call(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("requests.request should not run")
        ),
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "../api/admin",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 400


def test_grafana_proxy_home_fallback_response_sanitizes_dashboard_segments(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "../../bad uid")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "server dashboard")

    response = _grafana_proxy_home_fallback_response(
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy"
    )

    assert response.status_code == 302
    assert response["Location"] == (
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"
        "d/bad-uid/server-dashboard"
    )


def test_is_internal_hostname_handles_compose_and_local_hosts() -> None:
    assert _is_internal_hostname("grafana") is True
    assert _is_internal_hostname("localhost") is True
    assert _is_internal_hostname("127.0.0.1") is True
    assert _is_internal_hostname("prometheus") is True
    assert _is_internal_hostname("192.168.1.189") is False


def test_build_public_service_url_uses_request_host_and_public_port() -> None:
    built = _build_public_service_url(
        "https://grafana:3000",
        "http",
        "192.168.1.189",
        3000,
    )

    assert built == "https://192.168.1.189:3000"


def test_build_public_service_url_preserves_base_path() -> None:
    built = _build_public_service_url(
        "https://grafana:3000/grafana",
        "https",
        "example.org",
        4430,
    )

    assert built == "https://example.org:4430/grafana"


def test_resource_monitoring_data_prefers_public_urls_from_request_host(
    monkeypatch,
) -> None:
    request = RequestFactory().get("/admin_tools/resource-monitoring/data/")

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._probe_http_url",
        lambda *args, **kwargs: {"ok": True, "status": 200, "error": ""},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._collect_system_metrics",
        lambda *args, **kwargs: {
            "cpu_usage_percent": None,
            "memory_usage_percent": None,
            "disk_usage_percent": None,
        },
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._load_compose_service_names",
        lambda: [],
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._load_compose_health_data",
        lambda: ({}, {}),
    )

    def fake_get(url, timeout=5.0, allow_redirects=True, params=None):
        if "api/v1/targets" in url:
            return _RequestsResponse(
                200,
                payload=b'{"data": {"activeTargets": []}}',
            )
        if "label/container_label_com_docker_compose_service/values" in url:
            return _RequestsResponse(
                200,
                payload=b'{"status": "success", "data": []}',
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.get",
        fake_get,
    )
    monkeypatch.setenv("GRAFANA_HOST_PORT", "3000")
    monkeypatch.setenv("PROMETHEUS_HOST_PORT", "9090")

    response = resource_monitoring_data(request, conn=None)

    assert response.status_code == 200

    payload = json.loads(response.content.decode("utf-8"))
    assert payload["grafana"]["dashboard_url"].startswith("/d/")
    assert (
        payload["prometheus"]["targets_url"]
        == "http://testserver:9090/targets"  # DevSkim: ignore DS137138
    )  # DevSkim: ignore DS137138 -- Django test request uses http by default
    assert payload["grafana"]["dashboard_proxy_url"].startswith("/")
    assert payload[
        "grafana"
    ][
        "database_dashboard_external_url"
    ].startswith(
        "http://testserver:3000/d/database-metrics/database"  # DevSkim: ignore DS137138 -- Django test request uses http by default
    )
    assert payload[
        "grafana"
    ][
        "plugin_database_dashboard_external_url"
    ].startswith(
        "http://testserver:3000/d/plugin-database-metrics/plugin-database"  # DevSkim: ignore DS137138 -- Django test request uses http by default
    )
    assert payload[
        "grafana"
    ][
        "redis_dashboard_external_url"
    ].startswith(
        "http://testserver:3000/d/redis-metrics/redis"  # DevSkim: ignore DS137138 -- Django test request uses http by default
    )
    assert payload["grafana"]["database_dashboard_proxy_url"].startswith("/")
    assert payload["grafana"]["plugin_database_dashboard_proxy_url"].startswith("/")
    assert payload["grafana"]["redis_dashboard_proxy_url"].startswith("/")
    assert payload["prometheus"]["targets_proxy_url"].startswith("/")
    assert "containers" not in payload["prometheus"]["targets_overview"]


def test_resource_monitoring_data_keeps_external_urls_optional(monkeypatch) -> None:
    request = RequestFactory().get("/admin_tools/resource-monitoring/data/")

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._probe_http_url",
        lambda *args, **kwargs: {"ok": True, "status": 200, "error": ""},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._collect_system_metrics",
        lambda *args, **kwargs: {
            "cpu_usage_percent": None,
            "memory_usage_percent": None,
            "disk_usage_percent": None,
        },
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._load_compose_service_names",
        lambda: [],
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._load_compose_health_data",
        lambda: ({}, {}),
    )

    def fake_get(url, timeout=5.0, allow_redirects=True, params=None):
        if "api/v1/targets" in url:
            return _RequestsResponse(
                200,
                payload=b'{"data": {"activeTargets": []}}',
            )
        return _RequestsResponse(
            200,
            payload=b'{"status": "success", "data": []}',
        )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.get",
        fake_get,
    )
    monkeypatch.setenv(
        "ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "https://monitor.example.org/grafana"
    )
    monkeypatch.setenv(
        "ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL", "https://monitor.example.org/prometheus"
    )

    response = resource_monitoring_data(request, conn=None)

    payload = json.loads(response.content.decode("utf-8"))

    assert payload["grafana"]["dashboard_external_url"].startswith(
        "https://monitor.example.org/grafana/d/"
    )
    assert payload["grafana"]["database_dashboard_external_url"].startswith(
        "https://monitor.example.org/grafana/d/database-metrics/database"
    )
    assert payload["grafana"]["plugin_database_dashboard_external_url"].startswith(
        "https://monitor.example.org/grafana/d/plugin-database-metrics/plugin-database"
    )
    assert payload["grafana"]["redis_dashboard_external_url"].startswith(
        "https://monitor.example.org/grafana/d/redis-metrics/redis"
    )
    assert payload["grafana"]["dashboard_url"].startswith("/d/")
    assert payload["grafana"]["dashboard_proxy_url"].startswith("/")
    assert (
        payload["prometheus"]["targets_url"]
        == "https://monitor.example.org/prometheus/targets"
    )


def test_build_target_service_status_prefers_docker_healthcheck_status() -> None:
    active_targets = [
        {"labels": {"job": "db"}, "health": "up"},
        {"labels": {"job": "cache"}, "health": "up"},
        {"labels": {"job": "worker"}, "health": "down"},
    ]

    statuses = _build_target_service_status(
        active_targets,
        ["db", "cache", "worker", "api"],
        service_healthcheck_config={"db": True, "cache": True, "worker": True},
        runtime_health_by_service={
            "db": {"state": "running", "health": "healthy"},
            "cache": {"state": "running", "health": "unhealthy"},
            "worker": {"state": "exited", "health": ""},
            "api": {"state": "running", "health": ""},
        },
    )

    assert statuses == [
        {
            "service": "db",
            "health": "healthy",
            "state": "running",
            "healthcheck": "healthy",
        },
        {
            "service": "cache",
            "health": "unhealthy",
            "state": "running",
            "healthcheck": "unhealthy",
        },
        {"service": "worker", "health": "down", "state": "exited", "healthcheck": ""},
        {"service": "api", "health": "up", "state": "running", "healthcheck": "none"},
    ]


def test_build_target_service_status_uses_runtime_health_when_config_unavailable() -> (
    None
):
    statuses = _build_target_service_status(
        active_targets=[{"labels": {"job": "db"}, "health": "up"}],
        expected_services=["db", "api"],
        service_healthcheck_config={},
        runtime_health_by_service={
            "db": {"state": "running", "health": "healthy"},
            "api": {"state": "running", "health": "unhealthy"},
        },
    )

    assert statuses == [
        {
            "service": "db",
            "health": "healthy",
            "state": "running",
            "healthcheck": "healthy",
        },
        {
            "service": "api",
            "health": "unhealthy",
            "state": "running",
            "healthcheck": "unhealthy",
        },
    ]


def test_build_target_service_status_reports_starting_healthcheck_state() -> None:
    statuses = _build_target_service_status(
        active_targets=[{"labels": {"job": "db"}, "health": "up"}],
        expected_services=["db"],
        service_healthcheck_config={"db": True},
        runtime_health_by_service={"db": {"state": "running", "health": "starting"}},
    )

    assert statuses == [
        {
            "service": "db",
            "health": "starting",
            "state": "running",
            "healthcheck": "starting",
        }
    ]


def test_build_target_service_status_preserves_running_up_without_runtime_health() -> (
    None
):
    statuses = _build_target_service_status(
        active_targets=[{"labels": {"job": "db"}, "health": "up"}],
        expected_services=["db"],
        service_healthcheck_config={"db": True},
        runtime_health_by_service={"db": {"state": "running", "health": ""}},
    )

    assert statuses == [
        {
            "service": "db",
            "health": "up",
            "state": "running",
            "healthcheck": "",
        }
    ]


def test_grafana_proxy_forwards_subpath_and_query(monkeypatch) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure/server-infrastructure",
        {"refresh": "10s"},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    captured = {}

    def fake_proxy_http_request(
        django_request,
        base_url,
        path,
        query="",
        *,
        proxy_prefix="",
        rewrite_origin_headers=False,
        extra_forwarded_headers=(),
    ):
        captured.update(
            {
                "base_url": base_url,
                "path": path,
                "query": query,
                "proxy_prefix": proxy_prefix,
            }
        )

        class DummyResponse:
            status_code = 200
            content = b"{}"

        return DummyResponse()

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        fake_proxy_http_request,
    )

    from omeroweb_admin_tools.views.index_view import grafana_proxy

    response = grafana_proxy(
        request,
        "d/omero-infrastructure/server-infrastructure",
        conn=None,
    )

    assert response.status_code == 200
    assert (
        captured["base_url"] == "http://grafana:3000"  # DevSkim: ignore DS137138
    )  # DevSkim: ignore DS137138 -- production default for internal Docker service
    assert captured["path"] == "d/omero-infrastructure/server-infrastructure"
    assert captured["query"] == "refresh=10s"
    assert captured["proxy_prefix"] == "/admin_tools/resource-monitoring/grafana-proxy"


def test_grafana_proxy_root_path_forwards_empty_subpath(monkeypatch) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/grafana-proxy/",
        {"refresh": "10s"},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    captured = {}

    def fake_proxy_http_request(
        django_request,
        base_url,
        path,
        query="",
        *,
        proxy_prefix="",
        rewrite_origin_headers=False,
        extra_forwarded_headers=(),
    ):
        captured.update(
            {
                "base_url": base_url,
                "path": path,
                "query": query,
                "proxy_prefix": proxy_prefix,
            }
        )

        class DummyResponse:
            status_code = 200
            content = b"{}"

        return DummyResponse()

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        fake_proxy_http_request,
    )

    from omeroweb_admin_tools.views.index_view import grafana_proxy

    response = grafana_proxy(request, "", conn=None)

    assert response.status_code == 302
    assert "/admin_tools/resource-monitoring/grafana-proxy/d/" in response["Location"]


def test_prometheus_proxy_root_path_forwards_empty_subpath(monkeypatch) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/prometheus-proxy/",
        {"query": "up"},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    captured = {}

    def fake_proxy_http_request(
        django_request,
        base_url,
        path,
        query="",
        *,
        proxy_prefix="",
        rewrite_origin_headers=False,
        extra_forwarded_headers=(),
    ):
        captured.update(
            {
                "base_url": base_url,
                "path": path,
                "query": query,
                "proxy_prefix": proxy_prefix,
            }
        )

        class DummyResponse:
            status_code = 200
            content = b"{}"

        return DummyResponse()

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        fake_proxy_http_request,
    )

    from omeroweb_admin_tools.views.index_view import prometheus_proxy

    response = prometheus_proxy(request, "", conn=None)

    assert response.status_code == 302
    assert (
        "/admin_tools/resource-monitoring/prometheus-proxy/d/" in response["Location"]
    )


def test_safe_request_host_falls_back_when_get_host_fails() -> None:
    from omeroweb_admin_tools.views.index_view import _safe_request_host

    class DummyRequest:
        META = {"HTTP_HOST": "172.23.208.90:4090"}

        @staticmethod
        def get_host() -> str:
            raise ValueError("invalid host header")

    assert _safe_request_host(DummyRequest()) == "172.23.208.90"


def test_build_proxy_backend_urls_prefers_internal_and_deduplicates() -> None:
    assert _build_proxy_backend_urls("https://grafana:3000", "") == [
        "https://grafana:3000"
    ]
    assert _build_proxy_backend_urls(
        "https://grafana:3000/", "https://grafana:3000"
    ) == ["https://grafana:3000"]
    assert _build_proxy_backend_urls(
        "https://grafana:3000",
        "https://130.60.107.205:3000",
    ) == [
        "https://grafana:3000",
        "https://130.60.107.205:3000",
    ]


def test_grafana_unavailable_response_has_actionable_metadata() -> None:
    from omeroweb_admin_tools.views.index_view import _grafana_unavailable_response

    response = _grafana_unavailable_response(
        proxy_prefix="/admin_tools/resource-monitoring/grafana-proxy",
        attempted_backends=["https://grafana:3000", "https://130.60.107.205:3000"],
        status_code=502,
    )

    content = response.content.decode("utf-8")
    assert response.status_code == 503
    assert response["Cache-Control"] == "no-store"
    assert response["Retry-After"] == "30"
    assert "Grafana is temporarily unavailable" in content
    assert "grafana:3000" in content


def test_grafana_proxy_falls_back_to_public_url_on_backend_unreachable(
    monkeypatch,
) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure/server-infrastructure",
        {"refresh": "10s"},
    )

    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_URL", "https://grafana:3000")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "https://130.60.107.205:3000")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    attempts = []

    class DummyResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.content = b"{}"

    def fake_proxy_http_request(
        django_request,
        base_url,
        path,
        query="",
        *,
        proxy_prefix="",
        rewrite_origin_headers=False,
        extra_forwarded_headers=(),
    ):
        attempts.append(base_url)
        if base_url == "https://grafana:3000":
            return DummyResponse(status_code=502)
        return DummyResponse(status_code=200)

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        fake_proxy_http_request,
    )

    from omeroweb_admin_tools.views.index_view import grafana_proxy

    response = grafana_proxy(
        request,
        "d/omero-infrastructure/server-infrastructure",
        conn=None,
    )

    assert response.status_code == 200
    assert attempts == ["https://grafana:3000", "https://130.60.107.205:3000"]


def test_grafana_proxy_renders_custom_unavailable_page_for_gateway_errors(
    monkeypatch,
) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure/server-infrastructure",
    )

    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_URL", "https://grafana:3000")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "https://130.60.107.205:3000")
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    class DummyResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.content = b"{}"

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        lambda *a, **k: DummyResponse(status_code=502),
    )

    from omeroweb_admin_tools.views.index_view import grafana_proxy

    response = grafana_proxy(
        request,
        "d/omero-infrastructure/server-infrastructure",
        conn=None,
    )

    content = response.content.decode("utf-8")
    assert response.status_code == 503
    assert "Grafana is temporarily unavailable" in content
    assert "grafana:3000" in content


def test_is_behind_reverse_proxy_detects_forwarded_proto() -> None:
    request = RequestFactory().get("/test/", HTTP_X_FORWARDED_PROTO="https")
    assert _is_behind_reverse_proxy(request) is True


def test_is_behind_reverse_proxy_returns_false_for_direct_access() -> None:
    request = RequestFactory().get("/test/")
    assert _is_behind_reverse_proxy(request) is False


def test_build_public_service_url_omits_port_when_proxied() -> None:
    built = _build_public_service_url(
        "https://grafana:3000",
        "https",
        "omero.core.uzh.ch",
        3000,
        is_proxied=True,
    )
    assert built == "https://omero.core.uzh.ch"


def test_build_public_service_url_uses_forwarded_proto() -> None:
    built = _build_public_service_url(
        "https://grafana:3000",
        "http",
        "omero.core.uzh.ch",
        3000,
        forwarded_proto="https",
    )
    assert built == "https://omero.core.uzh.ch:3000"


def test_build_public_service_url_direct_access_unchanged() -> None:
    built = _build_public_service_url(
        "https://grafana:3000",
        "http",
        "192.168.1.189",
        3000,
    )
    assert built == "https://192.168.1.189:3000"


def test_proxy_rewrites_app_sub_url_for_grafana(monkeypatch) -> None:
    """The proxy should rewrite Grafana appSubUrl to the proxy prefix."""

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            _RequestsResponse(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                payload=(
                    b"<html><head><script>"
                    b'window.grafanaBootData={"settings":{"appSubUrl":""}};'
                    b"</script></head><body></body></html>"
                ),
            )
        ),
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "d/omero-infrastructure/server-infrastructure",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert (
        '"appSubUrl":"/omeroweb_admin_tools/resource-monitoring/grafana-proxy"'
        in content
    )


def test_proxy_rewrites_app_url_for_grafana(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            _RequestsResponse(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                payload=(
                    b"<html><head><script>"
                    b'window.grafanaBootData={"settings":{"appUrl":"https://grafana:3000/"}};'
                    b"</script></head><body></body></html>"
                ),
            )
        ),
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "d/omero-infrastructure/server-infrastructure",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert (
        '"appUrl":"/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"' in content
    )


def test_grafana_proxy_root_redirects_to_default_dashboard(monkeypatch) -> None:
    from omeroweb_admin_tools.views.index_view import grafana_proxy

    request = RequestFactory().get(
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "_proxy_http_request should not be called for Grafana root"
        )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        fail_if_called,
    )

    response = grafana_proxy(request, subpath="")

    assert response.status_code == 302
    assert response["Location"].startswith(
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/d/"
    )


def test_grafana_proxy_root_redirect_sanitizes_env_segments(monkeypatch) -> None:
    from omeroweb_admin_tools.views.index_view import (
        _grafana_proxy_home_fallback_response,
    )

    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "https://evil.example")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "../escape")

    response = _grafana_proxy_home_fallback_response(
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy"
    )

    assert response.status_code == 302
    assert (
        response["Location"]
        == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure/server-infrastructure"
    )


def test_logs_data_runtime_error_is_sanitized(monkeypatch) -> None:
    request = RequestFactory().get(
        "/omeroweb_admin_tools/logs/data/",
        data={"container": ["omero-omeroweb-1"]},
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.optional_log_config",
        lambda: SimpleNamespace(lookback_seconds=60, max_entries=50),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.fetch_loki_logs",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("secret loki details")
        ),
    )

    response = logs_data(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 502
    assert payload["error"] == "Failed to fetch logs."


def test_logs_data_filters_entries_and_validates_inputs(monkeypatch) -> None:
    captured = {}

    def _fake_fetch(
        log_config,
        containers,
        lookback_seconds,
        max_entries,
        *,
        internal_files,
        since_ns,
        text_query,
    ):
        captured.update(
            {
                "containers": containers,
                "lookback_seconds": lookback_seconds,
                "max_entries": max_entries,
                "internal_files": internal_files,
                "since_ns": since_ns,
                "text_query": text_query,
            }
        )
        return [
            SimpleNamespace(
                container="omeroserver",
                level="error",
                message="Managed repository error",
            ),
            SimpleNamespace(
                container="omeroweb",
                level="info",
                message="background worker ready",
            ),
        ]

    request = RequestFactory().get(
        "/omeroweb_admin_tools/logs/data/",
        data=[
            ("container", "omeroserver"),
            ("container", "omeroweb"),
            ("internal_file", "omeroserver_internal/master.err"),
            ("internal_file", "omeroweb_internal/web.log"),
            ("internal_file", "bad-entry"),
            ("internal_file", "redis/dump.rdb"),
            ("lookback", "120"),
            ("limit", "25"),
            ("query", "error"),
            ("level", "error"),
            ("since", "2026-03-30T06:56:57Z"),
        ],
    )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.optional_log_config",
        lambda: SimpleNamespace(lookback_seconds=60, max_entries=50),
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.fetch_loki_logs",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.serialize_entries",
        lambda entries: [
            {
                "container": entry.container,
                "level": entry.level,
                "message": entry.message,
            }
            for entry in entries
        ],
    )

    response = logs_data(request, conn=None)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload == {
        "entries": [
            {
                "container": "omeroserver",
                "level": "error",
                "message": "Managed repository error",
            }
        ]
    }
    assert captured["containers"] == ["omeroserver", "omeroweb"]
    assert captured["lookback_seconds"] == 120
    assert captured["max_entries"] == 25
    assert captured["internal_files"] == {
        "omeroserver_internal": {"master.err"},
        "omeroweb_internal": {"web.log"},
    }
    assert captured["since_ns"] > 0
    assert captured["text_query"] == "error"


def test_logs_data_rejects_invalid_query_parameters(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.optional_log_config",
        lambda: SimpleNamespace(lookback_seconds=60, max_entries=50),
    )

    invalid_limit = logs_data(
        RequestFactory().get(
            "/omeroweb_admin_tools/logs/data/",
            data={"container": ["omeroweb"], "lookback": "bad"},
        ),
        conn=None,
    )
    invalid_since = logs_data(
        RequestFactory().get(
            "/omeroweb_admin_tools/logs/data/",
            data={"container": ["omeroweb"], "since": "definitely-not-a-date"},
        ),
        conn=None,
    )
    invalid_level = logs_data(
        RequestFactory().get(
            "/omeroweb_admin_tools/logs/data/",
            data={"container": ["omeroweb"], "level": "verbose"},
        ),
        conn=None,
    )

    assert (
        json.loads(invalid_limit.content)["error"] == "Invalid lookback or limit value."
    )
    assert invalid_limit.status_code == 400
    assert json.loads(invalid_since.content)["error"] == "Invalid since value."
    assert invalid_since.status_code == 400
    assert json.loads(invalid_level.content)["error"] == "Invalid log level."
    assert invalid_level.status_code == 400


def test_resource_monitoring_suppresses_external_url_behind_proxy(monkeypatch) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/data/",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_HOST="omero.core.uzh.ch",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.utils.current_username",
        lambda request, conn: "root",
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._require_root_user",
        lambda request, conn: None,
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._probe_http_url",
        lambda *a, **k: {"ok": True, "status": 200, "error": ""},
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._collect_system_metrics",
        lambda *a, **k: {
            "cpu_usage_percent": None,
            "memory_usage_percent": None,
            "disk_usage_percent": None,
        },
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._load_compose_service_names", lambda: []
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._load_compose_health_data",
        lambda: ({}, {}),
    )

    def fake_get(url, timeout=5.0, allow_redirects=True, params=None):
        if "api/v1/targets" in url:
            return _RequestsResponse(
                200,
                payload=b'{"data": {"activeTargets": []}}',
            )
        if "label/" in url:
            return _RequestsResponse(
                200,
                payload=b'{"status": "success", "data": []}',
            )
        raise AssertionError(url)

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.get",
        fake_get,
    )
    monkeypatch.setenv("GRAFANA_HOST_PORT", "3000")
    monkeypatch.delenv("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", raising=False)

    response = resource_monitoring_data(request, conn=None)

    payload = json.loads(response.content.decode())

    # Behind proxy: external URLs suppressed, proxy URLs work
    assert payload["grafana"]["dashboard_external_url"] == ""
    assert payload["grafana"]["dashboard_proxy_url"].startswith("/")


def test_cookie_path_for_proxy_rewrites_root_to_proxy_prefix() -> None:
    assert (
        _cookie_path_for_proxy("/", "/admin_tools/resource-monitoring/grafana-proxy")
        == "/admin_tools/resource-monitoring/grafana-proxy/"
    )


def test_proxy_rewrites_set_cookie_path_for_grafana(monkeypatch) -> None:
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            _RequestsResponse(
                200,
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "Set-Cookie": "grafana_session=abc123; Path=/; HttpOnly; SameSite=Lax",
                },
                payload=b"<html><body>ok</body></html>",
            )
        ),
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "d/omero-infrastructure/server-infrastructure",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 200
    assert "grafana_session" in response.cookies
    assert (
        response.cookies["grafana_session"]["path"]
        == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"
    )


def test_proxy_http_request_forwards_extra_headers(monkeypatch) -> None:
    """extra_forwarded_headers passes backend-specific headers like X-Grafana-Csrf-Token."""
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(200, payload=b'{"ok":true}')

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        fake_request,
    )

    class DummyDjangoRequest:
        method = "POST"
        body = b'{"user":"admin","credential":"test-value"}'
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": "grafana_csrf_token=tok123; grafana_session=sess456",
            "X-Grafana-Csrf-Token": "tok123",
        }

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "login",
        extra_forwarded_headers=("X-Grafana-Csrf-Token",),
    )

    assert response.status_code == 200
    assert captured["headers"]["X-Grafana-Csrf-Token"] == "tok123"
    assert (
        captured["headers"]["Cookie"]
        == "grafana_csrf_token=tok123; grafana_session=sess456"
    )


def test_proxy_http_request_ignores_absent_extra_headers(monkeypatch) -> None:
    """Extra headers that are absent in the request are silently skipped."""
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(200, payload=b'{"ok":true}')

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.requests.request",
        fake_request,
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {"Accept": "text/html"}

    _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "login",
        extra_forwarded_headers=("X-Grafana-Csrf-Token",),
    )

    assert "X-Grafana-Csrf-Token" not in captured["headers"]


def test_grafana_proxy_post_is_protected_by_django_csrf_middleware() -> None:
    """Grafana proxy POSTs must keep Django CSRF enforcement enabled."""
    from omeroweb_admin_tools.views import index_view

    view_func = index_view.grafana_proxy
    assert getattr(view_func, "csrf_exempt", False) is False
    assert "POST" in index_view._GRAFANA_PROXY_METHODS

    request = RequestFactory().post(
        "/admin_tools/resource-monitoring/grafana-proxy/api/login",
        data=b'{"user":"root"}',
        content_type="application/json",
    )
    middleware = CsrfViewMiddleware(lambda _request: None)

    response = middleware.process_view(request, view_func, (), {"subpath": "api/login"})

    assert response is not None
    assert response.status_code == 403


def test_prometheus_proxy_is_not_csrf_exempt() -> None:
    """Prometheus proxy must NOT be csrf_exempt — it only allows safe methods."""
    from omeroweb_admin_tools.views import index_view

    view_func = index_view.prometheus_proxy
    assert getattr(view_func, "csrf_exempt", False) is False, (
        "prometheus_proxy must not be decorated with @csrf_exempt"
    )
