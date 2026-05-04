from __future__ import annotations

import json
import socket
from http.client import HTTPMessage

import requests
from omeroweb_admin_tools.views.index_view import _proxy_http_request


def _make_headers(values: dict[str, str]) -> HTTPMessage:
    """Create the headers.

    Inputs: `values` (dict[str, str]). Output: `HTTPMessage`.
    """
    message = HTTPMessage()
    for key, value in values.items():
        message[key] = value
    return message


class _DummyDjangoRequest:
    """Test double for dummy django request."""

    method = "GET"
    body = b""
    headers: dict[str, str] = {}


def _install_proxy_backend_stub(monkeypatch, handler) -> None:
    """Install the proxy backend stub.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `handler`. Output: None.
    """

    def fake_backend_request(
        *,
        base_url,
        method,
        request_target,
        data,
        headers,
        timeout_seconds,
    ):
        """Simulate backend request so the surrounding test controls that dependency.

        Inputs: `base_url` base URL, `method`, `request_target`, `data` payload,
        `headers`, `timeout_seconds`. Output: `handler` result.
        """
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
    """Verify proxy HTTP request suppresses prometheus live notification stream.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request suppresses prometheus live notification stream.
    AssertionError when validation or the called operation fails.
    """
    read_called = {"value": False}

    class DummyResponse:
        """Test double for dummy response."""

        status_code = 200
        headers = _make_headers({"Content-Type": "text/event-stream"})

        @property
        def content(self):
            """Return response content.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            external operations fail.
            """
            read_called["value"] = True
            raise AssertionError("streaming payload should not be fully read")

        @staticmethod
        def close():
            """Close `DummyResponse`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
    """Verify proxy HTTP request returns gateway timeout for backend timeout result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request returns gateway timeout for backend timeout.
    """

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: None. Raises: Timeout when validation or
        external operations fail.
        """
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
    """Verify proxy HTTP request returns gateway timeout for socket timeout result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request returns gateway timeout for socket timeout.
    """

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: None. Raises: timeout when validation or
        external operations fail.
        """
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
