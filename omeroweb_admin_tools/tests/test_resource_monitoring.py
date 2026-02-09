from __future__ import annotations

from omeroweb_admin_tools.views.index_view import (
    _build_target_service_status,
    _load_compose_service_names,
    _proxy_http_request,
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
        {"service": "app", "health": "up"},
        {"service": "db", "health": "unknown"},
        {"service": "redis", "health": "unknown"},
    ]


def test_build_target_service_status_resolves_container_name_variants() -> None:
    active_targets = [
        {
            "discoveredLabels": {"__meta_docker_container_name": "/omero_node-exporter_1"},
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
        {"service": "node-exporter", "health": "up"},
        {"service": "prometheus", "health": "down"},
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
