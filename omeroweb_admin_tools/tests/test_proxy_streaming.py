from __future__ import annotations

import json
import socket
from http.client import HTTPMessage

from omeroweb_admin_tools.views.index_view import _proxy_http_request


def _make_headers(values: dict[str, str]) -> HTTPMessage:
    message = HTTPMessage()
    for key, value in values.items():
        message[key] = value
    return message


class _DummyDjangoRequest:
    method = "GET"
    body = b""
    headers: dict[str, str] = {}


def test_proxy_http_request_suppresses_prometheus_live_notification_stream(
    monkeypatch,
) -> None:
    read_called = {"value": False}

    class DummyResponse:
        status = 200
        headers = _make_headers({"Content-Type": "text/event-stream"})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            read_called["value"] = True
            raise AssertionError("streaming payload should not be fully read")

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=10.0: DummyResponse()
    )

    response = _proxy_http_request(
        _DummyDjangoRequest(),
        "http://prometheus:9090",
        "api/v1/notifications/live",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/prometheus-proxy",
    )

    assert response.status_code == 204
    assert response["Cache-Control"] == "no-store"
    assert read_called["value"] is False


def test_proxy_http_request_returns_gateway_timeout_for_backend_timeout(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout=10.0):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = _proxy_http_request(
        _DummyDjangoRequest(),
        "http://prometheus:9090",
        "api/v1/query",
        "query=up",
    )

    assert response.status_code == 504
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Backend timed out."
    }


def test_proxy_http_request_returns_gateway_timeout_for_socket_timeout(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout=10.0):
        raise socket.timeout("socket timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = _proxy_http_request(
        _DummyDjangoRequest(),
        "http://prometheus:9090",
        "api/v1/query",
        "query=up",
    )

    assert response.status_code == 504
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Backend timed out."
    }
