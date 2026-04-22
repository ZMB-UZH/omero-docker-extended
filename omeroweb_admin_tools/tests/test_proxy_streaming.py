from __future__ import annotations

import json
import socket
from http.client import HTTPMessage

import requests
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


def _install_proxy_backend_stub(monkeypatch, handler) -> None:
    def fake_backend_request(
        *,
        base_url,
        method,
        request_target,
        data,
        headers,
        timeout_seconds,
    ):
        return handler(
            method,
            f"{base_url.rstrip('/')}{request_target}",
            data=data,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=False,
        )

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._send_proxy_backend_request",
        fake_backend_request,
    )


def test_proxy_http_request_suppresses_prometheus_live_notification_stream(
    monkeypatch,
) -> None:
    read_called = {"value": False}

    class DummyResponse:
        status_code = 200
        headers = _make_headers({"Content-Type": "text/event-stream"})

        @property
        def content(self):
            read_called["value"] = True
            raise AssertionError("streaming payload should not be fully read")

        @staticmethod
        def close():
            return None

    _install_proxy_backend_stub(
        monkeypatch,
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            DummyResponse()
        ),
    )

    response = _proxy_http_request(
        _DummyDjangoRequest(),
        "https://prometheus:9090",
        "api/v1/notifications/live",
        proxy_prefix="/omeroweb_admin_tools/resource-monitoring/prometheus-proxy",
    )

    assert response.status_code == 204
    assert response["Cache-Control"] == "no-store"
    assert read_called["value"] is False


def test_proxy_http_request_returns_gateway_timeout_for_backend_timeout(
    monkeypatch,
) -> None:
    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        raise requests.Timeout("timed out")

    _install_proxy_backend_stub(monkeypatch, fake_request)

    response = _proxy_http_request(
        _DummyDjangoRequest(),
        "https://prometheus:9090",
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
    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        raise socket.timeout("socket timed out")

    _install_proxy_backend_stub(monkeypatch, fake_request)

    response = _proxy_http_request(
        _DummyDjangoRequest(),
        "https://prometheus:9090",
        "api/v1/query",
        "query=up",
    )

    assert response.status_code == 504
    assert json.loads(response.content.decode("utf-8")) == {
        "error": "Backend timed out."
    }
