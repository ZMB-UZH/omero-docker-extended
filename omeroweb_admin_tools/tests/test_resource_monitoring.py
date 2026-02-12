from __future__ import annotations

from django.test import RequestFactory

from omeroweb_admin_tools.views.index_view import (
    resource_monitoring_data,
    _build_public_service_url,
    _build_target_service_status,
    _is_internal_hostname,
    _load_compose_service_names,
    _proxy_http_request,
    _build_proxy_backend_urls,
)


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
    monkeypatch.chdir(tmp_path)

    names = _load_compose_service_names()

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


def test_proxy_http_request_forwards_post_body(monkeypatch) -> None:
    captured = {}

    class DummyResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status":"ok"}'

    def fake_urlopen(request, timeout=10.0):
        captured["method"] = request.get_method()
        captured["data"] = request.data
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    class DummyDjangoRequest:
        method = "POST"
        body = b'{"query":"up"}'
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

    django_request = DummyDjangoRequest()

    response = _proxy_http_request(
        django_request,
        "http://grafana:3000",
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


def test_proxy_http_request_rewrites_relative_location_header(monkeypatch) -> None:
    class DummyResponse:
        status = 302
        headers = {"Content-Type": "text/plain", "Location": "/d/omero-infrastructure"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"redirect"

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=10.0: DummyResponse()
    )

    class DummyDjangoRequest:
        method = "GET"
        body = b""
        headers = {}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "http://grafana:3000",
        "d/omero-infrastructure",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert response.status_code == 302
    assert (
        response["Location"]
        == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure"
    )


def test_is_internal_hostname_handles_compose_and_local_hosts() -> None:
    assert _is_internal_hostname("grafana") is True
    assert _is_internal_hostname("localhost") is True
    assert _is_internal_hostname("127.0.0.1") is True
    assert _is_internal_hostname("prometheus") is True
    assert _is_internal_hostname("192.168.1.189") is False


def test_build_public_service_url_uses_request_host_and_public_port() -> None:
    built = _build_public_service_url(
        "http://grafana:3000",
        "http",
        "192.168.1.189",
        3000,
    )

    assert built == "http://192.168.1.189:3000"


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

    class DummyResponse:
        def __init__(self, payload: str):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._payload.encode("utf-8")

    def fake_urlopen(url, timeout=5.0):
        if "api/v1/targets" in url:
            return DummyResponse('{"data": {"activeTargets": []}}')
        if "label/container_label_com_docker_compose_service/values" in url:
            return DummyResponse('{"status": "success", "data": []}')
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("GRAFANA_HOST_PORT", "3000")
    monkeypatch.setenv("PROMETHEUS_HOST_PORT", "9090")

    response = resource_monitoring_data(request, conn=None)

    assert response.status_code == 200
    import json

    payload = json.loads(response.content.decode("utf-8"))
    assert payload["grafana"]["dashboard_url"].startswith("/d/")
    assert payload["prometheus"]["targets_url"] == "http://testserver:9090/targets"
    assert payload["grafana"]["dashboard_proxy_url"].startswith("/")
    assert payload["prometheus"]["targets_proxy_url"].startswith("/")
    assert "containers" not in payload["prometheus"]["targets_overview"]


def test_resource_monitoring_data_keeps_external_urls_optional(monkeypatch) -> None:
    request = RequestFactory().get("/admin_tools/resource-monitoring/data/")

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

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status": "success", "data": []}'

    def fake_urlopen(url, timeout=5.0):
        if "api/v1/targets" in url:
            return type(
                "X",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, a, b, c: False,
                    "read": lambda self: b'{"data": {"activeTargets": []}}',
                },
            )()
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv(
        "ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "https://monitor.example.org/grafana"
    )
    monkeypatch.setenv(
        "ADMIN_TOOLS_PROMETHEUS_PUBLIC_URL", "https://monitor.example.org/prometheus"
    )

    response = resource_monitoring_data(request, conn=None)
    import json

    payload = json.loads(response.content.decode("utf-8"))

    assert payload["grafana"]["dashboard_external_url"].startswith(
        "https://monitor.example.org/grafana/d/"
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
    assert captured["base_url"] == "http://grafana:3000"
    assert captured["path"] == "d/omero-infrastructure/server-infrastructure"
    assert captured["query"] == "refresh=10s"
    assert captured["proxy_prefix"] == "/admin_tools/resource-monitoring/grafana-proxy"


def test_safe_request_host_falls_back_when_get_host_fails() -> None:
    from omeroweb_admin_tools.views.index_view import _safe_request_host

    class DummyRequest:
        META = {"HTTP_HOST": "172.23.208.90:4090"}

        @staticmethod
        def get_host() -> str:
            raise ValueError("invalid host header")

    assert _safe_request_host(DummyRequest()) == "172.23.208.90"


def test_build_proxy_backend_urls_prefers_internal_and_deduplicates() -> None:
    assert _build_proxy_backend_urls("http://grafana:3000", "") == [
        "http://grafana:3000"
    ]
    assert _build_proxy_backend_urls("http://grafana:3000/", "http://grafana:3000") == [
        "http://grafana:3000"
    ]
    assert _build_proxy_backend_urls(
        "http://grafana:3000", "http://130.60.107.205:3000"
    ) == [
        "http://grafana:3000",
        "http://130.60.107.205:3000",
    ]


def test_grafana_proxy_falls_back_to_public_url_on_backend_unreachable(
    monkeypatch,
) -> None:
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/grafana-proxy/d/omero-infrastructure/server-infrastructure",
        {"refresh": "10s"},
    )

    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_URL", "http://grafana:3000")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_PUBLIC_URL", "http://130.60.107.205:3000")
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
    ):
        attempts.append(base_url)
        if base_url == "http://grafana:3000":
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
    assert attempts == ["http://grafana:3000", "http://130.60.107.205:3000"]
