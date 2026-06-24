from __future__ import annotations

import json
from http.client import HTTPMessage
from types import SimpleNamespace

from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory

from omeroweb_admin_tools.views.index_view import (
    CookieError,
    grafana_proxy,
    logs_data,
    prometheus_proxy,
    resource_monitoring_data,
    _GRAFANA_PROXY_METHODS,
    _build_proxy_request_target,
    _build_proxy_target_url,
    _build_public_service_url,
    _build_target_service_status,
    _collect_proxy_headers,
    _is_internal_hostname,
    _is_behind_reverse_proxy,
    _load_compose_service_names,
    _normalize_proxy_request_target,
    _proxy_http_request,
    _build_proxy_backend_urls,
    _cookie_path_for_proxy,
    _origin_from_url,
    _grafana_backend_auth_headers,
    _grafana_proxy_home_fallback_response,
    _inject_proxy_csrf_bridge,
    _filtered_proxy_cookie_header,
    _rewrite_proxied_location,
    _send_proxy_backend_request,
)


def _make_headers(d: dict) -> HTTPMessage:
    """An HTTPMessage from a plain dict for test stubs.

    Inputs: `d`. Output: `HTTPMessage`.
    """
    msg = HTTPMessage()
    for key, value in d.items():
        msg[key] = value
    return msg


class _RequestsResponse:
    """Test double for requests response behavior in this module."""

    def __init__(
        self,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        payload: bytes = b"",
    ) -> None:
        """Create `_RequestsResponse` with `status_code`.

        Inputs: `status_code`, `headers`, `payload`. Output: None.
        """
        self.status_code = status_code
        self.headers = headers or {}
        self.content = payload
        self.raw = SimpleNamespace(headers=_make_headers(self.headers))

    def json(self):
        """Return the JSON payload.

        Inputs: none. Output: `json.loads` result.
        """
        return json.loads(self.content.decode("utf-8"))

    @staticmethod
    def close() -> None:
        """Close `_RequestsResponse`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        return None


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


def test_load_compose_service_names_reads_service_block(tmp_path, monkeypatch) -> None:
    """Verify load compose service names reads service block.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in load compose service names reads service block.
    """
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
    """Verify build target service status prefers up.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status prefers up.
    """
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
    """Verify build target service status resolves container name variants.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status resolves container name variants.
    """
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
    """Verify build target service status uses recent container samples.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status uses recent container samples.
    """
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
    """Check origin from URL normalizes scheme and host parsing against the documented contract.

    Inputs: admin-tool fixtures. Output: fails on regressions in origin from URL normalizes scheme and host.
    """
    assert _origin_from_url("https://grafana:3000/path?q=1") == "https://grafana:3000"
    assert _origin_from_url("https://example.org") == "https://example.org"
    assert _origin_from_url("not-a-url") == ""


def test_proxy_http_request_rewrites_origin_headers_when_enabled(monkeypatch) -> None:
    """Verify proxy HTTP request rewrites origin headers when enabled.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request rewrites origin headers when enabled.
    """
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: `_RequestsResponse` result.
        """
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(
            200,
            headers={"Content-Type": "application/json"},
            payload=b'{"status":"ok"}',
        )

    _install_proxy_backend_stub(monkeypatch, fake_request)

    class DummyDjangoRequest:
        """Test double for dummy django request."""

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
    """Verify proxy HTTP request forwards post body.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request forwards post body.
    """
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: `_RequestsResponse` result.
        """
        captured["method"] = method
        captured["data"] = data
        captured["timeout"] = timeout
        return _RequestsResponse(
            200,
            headers={"Content-Type": "application/json"},
            payload=b'{"status":"ok"}',
        )

    _install_proxy_backend_stub(monkeypatch, fake_request)

    class DummyDjangoRequest:
        """Test double for dummy django request."""

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


def test_proxy_http_request_strips_browser_auth_and_unlisted_cookies(
    monkeypatch,
) -> None:
    """Verify proxy requests do not forward browser credentials to backends.

    Inputs: pytest provides `monkeypatch`. Output: fails on credential-forwarding
    regressions.
    """
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: `_RequestsResponse` result.
        """
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(
            200,
            headers={
                "Content-Type": "application/json",
                "Set-Cookie": "grafana_session=abc123; Path=/; HttpOnly",
            },
            payload=b'{"status":"ok"}',
        )

    _install_proxy_backend_stub(monkeypatch, fake_request)

    class DummyDjangoRequest:
        """Test double for dummy django request."""

        method = "GET"
        body = b""
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer test-token",
            "Cookie": "sessionid=omero-session; csrftoken=django-csrf",
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
    assert "Authorization" not in captured["headers"]
    assert "Cookie" not in captured["headers"]
    assert captured["headers"]["Origin"] == "https://omero.example.org"
    assert (
        captured["headers"]["Referer"]
        == "https://omero.example.org/omeroweb_admin_tools/resource-monitoring/"
    )


def test_build_proxy_headers_can_forward_explicit_auth_and_filters_bad_cookie():
    """Verify explicit auth forwarding remains opt-in and malformed cookies are dropped.

    Inputs: none. Output: asserts filtered proxy headers.
    """

    class DummyDjangoRequest:
        """Test double for proxy header extraction."""

        headers = {
            "Authorization": "Bearer backend-token",
            "Cookie": "broken-cookie-without-equals",
        }

    headers = _collect_proxy_headers(
        DummyDjangoRequest(),
        extra_forwarded_headers=(),
        forward_authorization=True,
        allowed_cookie_names=frozenset({"grafana_session"}),
    )

    assert headers == {"Authorization": "Bearer backend-token"}


def test_filtered_proxy_cookie_header_fails_closed_on_parse_error(monkeypatch) -> None:
    """Verify Cookie parsing errors are not forwarded to Grafana.

    Inputs: pytest monkeypatch fixture. Output: asserts malformed cookies are dropped.
    """

    class _BadCookie:
        """SimpleCookie replacement that raises the parser's documented error."""

        @staticmethod
        def load(_value):
            """Raise a cookie parse error.

            Inputs: ignored cookie value. Output: raises CookieError.
            """
            raise CookieError("bad cookie")

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.SimpleCookie",
        _BadCookie,
    )

    assert (
        _filtered_proxy_cookie_header(
            "grafana_session=value",
            allowed_cookie_names=frozenset({"grafana_session"}),
        )
        == ""
    )


def test_proxy_http_request_forced_headers_override_browser_auth(monkeypatch) -> None:
    """Backend-only auth replaces browser auth before forwarding.

    Inputs: pytest provides `monkeypatch`. Output: asserts forwarded header selection.
    """
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Capture headers from the proxy backend request.

        Inputs: `method`, `url`, `data`, `headers`, `timeout`, `allow_redirects`.
        Output: `_RequestsResponse`.
        """
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(
            200,
            headers={"Content-Type": "application/json"},
            payload=b'{"status":"ok"}',
        )

    _install_proxy_backend_stub(monkeypatch, fake_request)

    class DummyDjangoRequest:
        """Test double for dummy django request."""

        method = "GET"
        body = b""
        headers = {"Authorization": "Bearer browser-token"}

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "api/user",
        forced_backend_headers={"Authorization": "Basic backend-token"},
    )

    assert response.status_code == 200
    assert captured["headers"]["Authorization"] == "Basic backend-token"


def test_grafana_backend_auth_headers_use_configured_secret(monkeypatch) -> None:
    """Grafana proxy credentials are prepared for backend requests only.

    Inputs: pytest provides `monkeypatch`. Output: asserts generated Basic header.
    """
    monkeypatch.setenv("GF_SECURITY_ADMIN_USER", "admin")
    monkeypatch.setenv("GF_SECURITY_ADMIN_PASSWORD", "secret")

    assert _grafana_backend_auth_headers() == {
        "Authorization": "Basic YWRtaW46c2VjcmV0"
    }


def test_normalize_proxy_request_target_rejects_traversal() -> None:
    """Confirm normalize proxy request target rejects traversal is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in normalize proxy request target rejects traversal.
    """
    try:
        _normalize_proxy_request_target("../api/admin")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected traversal target to be rejected")


def test_normalize_proxy_request_target_rejects_absolute_url() -> None:
    """Confirm normalize proxy request target rejects absolute URL is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in normalize proxy request target rejects absolute URL.
    """
    try:
        _normalize_proxy_request_target(
            "https://grafana.example.org//api/../api/search?orgId=1"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected absolute proxy target to be rejected")


def test_build_proxy_target_url_rejects_query_or_fragment_in_path() -> None:
    """Confirm build proxy target URL rejects query or fragment in path is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions when build proxy target URL rejects query or fragment in path accepts unsafe input.
    """
    for path in ("api/search?orgId=1", "api/search#fragment"):
        try:
            _build_proxy_target_url("https://grafana:3000", path, "")
        except ValueError:
            pass
        else:
            raise AssertionError("Expected unsafe proxy path to be rejected")

    try:
        _build_proxy_target_url("https://grafana:3000", "api/search", "orgId=1\n")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected unsafe proxy query to be rejected")


def test_build_proxy_target_url_rejects_backend_without_hostname() -> None:
    """Confirm build proxy target URL rejects backend without hostname is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in build proxy target URL rejects backend without hostname.
    """
    try:
        _build_proxy_target_url("https://:3000", "api/search", "")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected hostname-less proxy backend to be rejected")


def test_build_proxy_target_url_rejects_origin_drift(monkeypatch) -> None:
    """Confirm build proxy target URL rejects origin drift is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in build proxy target URL rejects origin drift.
    AssertionError when validation or the called operation fails.
    """
    urlunparse_results = iter(
        ("https://grafana:3000", "https://unexpected.example/api/search")
    )
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.urllib.parse.urlunparse",
        lambda _parts: next(urlunparse_results, ""),
    )

    try:
        _build_proxy_target_url("https://grafana:3000", "api/search", "")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected proxy target origin drift to be rejected")


def test_build_proxy_target_url_quotes_path_and_preserves_query() -> None:
    """Check that build proxy target URL quotes path and preserves query remains stable.

    Inputs: admin-tool fixtures. Output: fails on regressions when build proxy target URL quotes path and preserves query accepts unsafe input.
    """
    path, target_url = _build_proxy_target_url(
        "https://grafana:3000/root/",
        "api/search with space",
        "?orgId=1&query=a%2Fb",
    )

    assert path == "api/search%20with%20space"
    assert (
        target_url
        == "https://grafana:3000/root/api/search%20with%20space?orgId=1&query=a%2Fb"
    )
    assert (
        _build_proxy_request_target(target_url)
        == "/root/api/search%20with%20space?orgId=1&query=a%2Fb"
    )


def test_build_proxy_request_target_rejects_control_characters() -> None:
    """Confirm build proxy request target rejects control characters is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in build proxy request target rejects control characters.
    """
    try:
        _build_proxy_request_target("https://grafana:3000/api/search?query=up\x7f")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected unsafe request target to be rejected")


def test_send_proxy_backend_request_uses_validated_origin_and_request_target(
    monkeypatch,
) -> None:
    """Verify send proxy backend request uses validated origin and request target.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in send proxy backend request uses validated origin and request target.
    """
    captured = {}

    class DummyRawResponse:
        """Test double for dummy raw response."""

        status = 202

        def __init__(self):
            """Create `DummyRawResponse` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.msg = _make_headers({"Content-Type": "application/json"})

        @staticmethod
        def read():
            """Read data from the resource.

            Inputs: none. Output: b'{"ok":true}'.
            """
            return b'{"ok":true}'

    class DummyConnection:
        """Test double for dummy connection."""

        def __init__(self, host, *, port, timeout):
            """Create `DummyConnection` with `host`.

            Inputs: `host`, `port`, `timeout`. Output: None.
            """
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout
            self.closed = False

        @staticmethod
        def request(method, target, *, body, headers):
            """Request the request for `DummyConnection`.

            Inputs: `method`, `target`, `body`, `headers`. Output: None.
            """
            captured["method"] = method
            captured["target"] = target
            captured["body"] = body
            captured["headers"] = dict(headers)

        @staticmethod
        def getresponse():
            """Return the HTTP response.

            Inputs: none. Output: `DummyRawResponse` result.
            """
            return DummyRawResponse()

        def close(self):
            """Close `DummyConnection`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self.closed = True
            captured["closed"] = True

    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view.HTTPSConnection",
        DummyConnection,
    )

    response = _send_proxy_backend_request(
        base_url="https://grafana.example.test:3443/grafana",
        method="POST",
        request_target="/grafana/api/search?q=up",
        data=b"payload",
        headers={"Accept": "application/json"},
        timeout_seconds=7.5,
    )

    assert response.status_code == 202
    assert response.content == b'{"ok":true}'
    response.close()
    assert captured == {
        "host": "grafana.example.test",
        "port": 3443,
        "timeout": 7.5,
        "method": "POST",
        "target": "/grafana/api/search?q=up",
        "body": b"payload",
        "headers": {"Accept": "application/json"},
        "closed": True,
    }


def test_send_proxy_backend_request_rejects_backend_without_hostname() -> None:
    """Confirm send proxy backend request rejects backend without hostname is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in send proxy backend request rejects backend without hostname.
    """
    try:
        _send_proxy_backend_request(
            base_url="https://:3000",
            method="GET",
            request_target="/api/search",
            data=None,
            headers={},
            timeout_seconds=1.0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected hostname-less proxy backend to be rejected")


def test_proxy_http_request_rewrites_relative_location_header(monkeypatch) -> None:
    """Verify proxy HTTP request rewrites relative location header.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request rewrites relative location header.
    """
    _install_proxy_backend_stub(
        monkeypatch,
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
        """Test double for dummy django request."""

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
    """Confirm rewrite proxied location blocks external redirects is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions in rewrite proxied location blocks external redirects.
    """
    location = _rewrite_proxied_location(
        "https://evil.example.org/steal",
        "https://grafana:3000",
        "/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
    )

    assert location == "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/"


def test_proxy_http_request_rewrites_non_root_relative_location_header(
    monkeypatch,
) -> None:
    """Verify proxy HTTP request rewrites non root relative location header.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request rewrites non root relative location header.
    """
    _install_proxy_backend_stub(
        monkeypatch,
        lambda method, url, data=None, headers=None, timeout=10.0, allow_redirects=False: (
            _RequestsResponse(
                302,
                headers={"Content-Type": "text/plain", "Location": "login"},
                payload=b"redirect",
            )
        ),
    )

    class DummyDjangoRequest:
        """Test double for dummy django request."""

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
    """Confirm proxy HTTP request rejects traversal before backend call is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request rejects traversal before backend call.
    """
    monkeypatch.setattr(
        "omeroweb_admin_tools.views.index_view._send_proxy_backend_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("_send_proxy_backend_request should not run")
        ),
    )

    class DummyDjangoRequest:
        """Test double for dummy django request."""

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
    """Check that grafana proxy home fallback response sanitizes dashboard segments keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana proxy home fallback response sanitizes dashboard segments.
    """
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
    """Verify is internal hostname handles compose and local hosts.

    Inputs: admin-tool fixtures. Output: fails on regressions in is internal hostname handles compose and local hosts.
    """
    assert _is_internal_hostname("grafana") is True
    assert _is_internal_hostname("localhost") is True
    assert _is_internal_hostname("127.0.0.1") is True
    assert _is_internal_hostname("prometheus") is True
    assert _is_internal_hostname("198.51.100.42") is False


def test_build_public_service_url_uses_request_host_and_public_port() -> None:
    """Verify build public service URL uses request host and public port.

    Inputs: admin-tool fixtures. Output: fails on regressions in build public service URL uses request host and public port.
    """
    built = _build_public_service_url(
        "https://grafana:3000",
        "http",
        "198.51.100.42",
        3000,
    )

    assert built == "https://198.51.100.42:3000"


def test_build_public_service_url_preserves_base_path() -> None:
    """Check that build public service URL preserves base path remains stable.

    Inputs: admin-tool fixtures. Output: fails on regressions when build public service URL preserves base path accepts unsafe input.
    """
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
    """Verify resource monitoring data prefers public URLs from request host.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resource monitoring data prefers public URLs from request host.
    AssertionError when validation or the called operation fails.
    """
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
        """Simulate get so the surrounding test controls that dependency.

        Inputs: `url` URL, `timeout` timeout seconds, `allow_redirects`, `params` SQL
        parameters. Output: `_RequestsResponse` result. Raises: AssertionError when validation or the called operation fails.
        """
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
    """Check that resource monitoring data keeps external URLs optional remains stable.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resource monitoring data keeps external URLs optional.
    """
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
        """Simulate get so the surrounding test controls that dependency.

        Inputs: `url` URL, `timeout` timeout seconds, `allow_redirects`, `params` SQL
        parameters. Output: `_RequestsResponse` result.
        """
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
    """Verify build target service status prefers docker healthcheck status.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status prefers docker healthcheck status.
    """
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
    """Verify build target service status uses runtime health when config unavailable.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status uses runtime health when config unavailable.
    """
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
    """Verify build target service status reports starting healthcheck state.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status reports starting healthcheck state.
    """
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
    """Check that build target service status preserves running up without runtime health remains stable.

    Inputs: admin-tool fixtures. Output: fails on regressions in build target service status preserves running up without runtime health.
    """
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
    """Verify grafana proxy forwards subpath and query.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana proxy forwards subpath and query.
    """
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
        forced_backend_headers=None,
        allowed_cookie_names=(),
        allowed_cookie_prefixes=(),
        forward_authorization=False,
    ):
        """Simulate proxy HTTP request so the surrounding test controls that dependency.

        Inputs: `django_request`, `base_url` base URL, `path` path, `query`,
        `proxy_prefix`, `rewrite_origin_headers`, `extra_forwarded_headers`,
        `forced_backend_headers`. Output: `DummyResponse` result.
        """
        captured.update(
            {
                "base_url": base_url,
                "path": path,
                "query": query,
                "proxy_prefix": proxy_prefix,
            }
        )

        return HttpResponse(b"{}", status=200)

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
    """Verify the grafana proxy root path forwards empty subpath safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when grafana proxy root path forwards empty subpath accepts unsafe input.
    """
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
        forced_backend_headers=None,
        allowed_cookie_names=(),
        allowed_cookie_prefixes=(),
        forward_authorization=False,
    ):
        """Simulate proxy HTTP request so the surrounding test controls that dependency.

        Inputs: `django_request`, `base_url` base URL, `path` path, `query`,
        `proxy_prefix`, `rewrite_origin_headers`, `extra_forwarded_headers`,
        `forced_backend_headers`. Output: `DummyResponse` result.
        """
        captured.update(
            {
                "base_url": base_url,
                "path": path,
                "query": query,
                "proxy_prefix": proxy_prefix,
            }
        )

        class DummyResponse:
            """Test double for dummy response."""

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
    """Verify the prometheus proxy root path forwards empty subpath safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when prometheus proxy root path forwards empty subpath accepts unsafe input.
    """
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
        forced_backend_headers=None,
        allowed_cookie_names=(),
        allowed_cookie_prefixes=(),
        forward_authorization=False,
    ):
        """Simulate proxy HTTP request so the surrounding test controls that dependency.

        Inputs: `django_request`, `base_url` base URL, `path` path, `query`,
        `proxy_prefix`, `rewrite_origin_headers`, `extra_forwarded_headers`,
        `forced_backend_headers`. Output: `DummyResponse` result.
        """
        captured.update(
            {
                "base_url": base_url,
                "path": path,
                "query": query,
                "proxy_prefix": proxy_prefix,
            }
        )

        class DummyResponse:
            """Test double for dummy response."""

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
        response["Location"]
        == "/admin_tools/resource-monitoring/prometheus-proxy/targets"
    )


def test_safe_request_host_falls_back_when_get_host_fails() -> None:
    """Confirm safe request host falls back when get host fails exposes the expected failure.

    Inputs: admin-tool fixtures. Output: fails on regressions in safe request host falls back when get host fails.
    """
    from omeroweb_admin_tools.views.index_view import _safe_request_host

    class DummyRequest:
        """Test double for dummy request."""

        META = {"HTTP_HOST": "198.51.100.90:4090"}

        @staticmethod
        def get_host() -> str:
            """Return the host for `DummyRequest`.

            Inputs: none. Output: `str`. Raises: ValueError for the exercised failure path.
            """
            raise ValueError("invalid host header")

    assert _safe_request_host(DummyRequest()) == "198.51.100.90"


def test_build_proxy_backend_urls_prefers_internal_and_deduplicates() -> None:
    """Verify build proxy backend URLs prefers internal and deduplicates.

    Inputs: admin-tool fixtures. Output: fails on regressions in build proxy backend URLs prefers internal and deduplicates.
    """
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
    """Verify grafana unavailable response has actionable metadata result shape.

    Inputs: admin-tool fixtures. Output: fails on regressions in grafana unavailable response has actionable metadata.
    """
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
    """Verify grafana proxy falls back to public URL on backend unreachable.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana proxy falls back to public URL on backend unreachable.
    """
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

    def fake_proxy_http_request(
        django_request,
        base_url,
        path,
        query="",
        *,
        proxy_prefix="",
        rewrite_origin_headers=False,
        extra_forwarded_headers=(),
        forced_backend_headers=None,
        allowed_cookie_names=(),
        allowed_cookie_prefixes=(),
        forward_authorization=False,
    ):
        """Simulate proxy HTTP request so the surrounding test controls that dependency.

        Inputs: `django_request`, `base_url` base URL, `path` path, `query`,
        `proxy_prefix`, `rewrite_origin_headers`, `extra_forwarded_headers`,
        `forced_backend_headers`. Output: `DummyResponse` result.
        """
        attempts.append(base_url)
        if base_url == "https://grafana:3000":
            return HttpResponse(b"{}", status=502)
        return HttpResponse(b"{}", status=200)

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
    """Check grafana proxy renders custom unavailable page for gateway errors renders the expected surface.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana proxy renders custom unavailable page for gateway errors.
    """
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
        """Test double for dummy response."""

        def __init__(self, status_code: int):
            """Create `DummyResponse` with `status_code`.

            Inputs: `status_code`. Output: None.
            """
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
    """Verify is behind reverse proxy detects forwarded proto.

    Inputs: admin-tool fixtures. Output: fails on regressions in is behind reverse proxy detects forwarded proto.
    """
    request = RequestFactory().get("/test/", HTTP_X_FORWARDED_PROTO="https")
    assert _is_behind_reverse_proxy(request) is True


def test_is_behind_reverse_proxy_returns_false_for_direct_access() -> None:
    """Verify is behind reverse proxy returns false for direct access result shape.

    Inputs: admin-tool fixtures. Output: fails on regressions in is behind reverse proxy returns false for direct access.
    """
    request = RequestFactory().get("/test/")
    assert _is_behind_reverse_proxy(request) is False


def test_build_public_service_url_omits_port_when_proxied() -> None:
    """Verify build public service URL omits port when proxied.

    Inputs: admin-tool fixtures. Output: fails on regressions in build public service URL omits port when proxied.
    """
    built = _build_public_service_url(
        "https://grafana:3000",
        "https",
        "omero.example.org",
        3000,
        is_proxied=True,
    )
    assert built == "https://omero.example.org"


def test_build_public_service_url_uses_forwarded_proto() -> None:
    """Verify build public service URL uses forwarded proto.

    Inputs: admin-tool fixtures. Output: fails on regressions in build public service URL uses forwarded proto.
    """
    built = _build_public_service_url(
        "https://grafana:3000",
        "http",
        "omero.example.org",
        3000,
        forwarded_proto="https",
    )
    assert built == "https://omero.example.org:3000"


def test_build_public_service_url_direct_access_unchanged() -> None:
    """Verify build public service URL direct access unchanged.

    Inputs: admin-tool fixtures. Output: fails on regressions in build public service URL direct access unchanged.
    """
    built = _build_public_service_url(
        "https://grafana:3000",
        "http",
        "198.51.100.42",
        3000,
    )
    assert built == "https://198.51.100.42:3000"


def test_proxy_rewrites_app_sub_url_for_grafana(monkeypatch) -> None:
    """Verify proxy rewrites app sub URL for grafana.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy rewrites app sub URL for grafana.
    """
    _install_proxy_backend_stub(
        monkeypatch,
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
        """Test double for dummy django request."""

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
    assert "admin-tools-proxy-csrf-bridge" in content
    assert "X-CSRFToken" in content
    assert "function isProxyRequest(input)" in content
    assert "parsedUrl.origin === window.location.origin" in content
    assert "parsedUrl.pathname.indexOf(proxyPrefix()) === 0" in content


def test_proxy_csrf_bridge_injection_is_idempotent() -> None:
    """Verify the Grafana proxy CSRF bridge is injected only once.

    Inputs: none. Output: asserts existing bridge markers are preserved.
    """
    html = (
        '<html><head><script id="admin-tools-proxy-csrf-bridge"></script></head>'
        "<body></body></html>"
    )

    assert _inject_proxy_csrf_bridge(html) == html


def test_proxy_rewrites_app_url_for_grafana(monkeypatch) -> None:
    """Verify proxy rewrites app URL for grafana.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy rewrites app URL for grafana.
    """
    _install_proxy_backend_stub(
        monkeypatch,
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
        """Test double for dummy django request."""

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
    """Verify grafana proxy root redirects to default dashboard.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana proxy root redirects to default dashboard.
    AssertionError when validation or the called operation fails.
    """
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
        """Fail immediately when an unexpected branch invokes this helper.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        None. Raises: AssertionError when validation or the called operation fails.
        """
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


def test_prometheus_proxy_root_redirects_to_targets(monkeypatch) -> None:
    """Verify prometheus proxy root redirects to targets.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in prometheus proxy root redirects to targets.
    """
    from omeroweb_admin_tools.views.index_view import prometheus_proxy

    request = RequestFactory().get(
        "/omeroweb_admin_tools/resource-monitoring/prometheus-proxy/"
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
        "omeroweb_admin_tools.views.index_view._proxy_http_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("root path should redirect before proxying")
        ),
    )

    response = prometheus_proxy(request, subpath="")

    assert response.status_code == 302
    assert (
        response["Location"]
        == "/omeroweb_admin_tools/resource-monitoring/prometheus-proxy/targets"
    )


def test_grafana_proxy_root_redirect_sanitizes_env_segments(monkeypatch) -> None:
    """Check that grafana proxy root redirect sanitizes env segments keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana proxy root redirect sanitizes env segments.
    """
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
    """Confirm logs data runtime error is sanitized exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when logs data runtime error is sanitized stops reporting the expected error.
    """
    request = RequestFactory().get(
        "/omeroweb_admin_tools/logs/data/",
        data={"container": ["omeroweb"]},
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
    """Verify logs data filters entries and validates inputs.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in logs data filters entries and validates inputs.
    """
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
        """Return the fake fetch.

        Inputs: `log_config`, `containers`, `lookback_seconds`, `max_entries`,
        `internal_files`, `since_ns`, `text_query`. Output: `list`.
        """
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
    """Confirm logs data rejects invalid query parameters is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in logs data rejects invalid query parameters.
    """
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
    invalid_container = logs_data(
        RequestFactory().get(
            "/omeroweb_admin_tools/logs/data/",
            data={"container": ['omeroweb"} |~ ".+']},
        ),
        conn=None,
    )
    invalid_internal_file = logs_data(
        RequestFactory().get(
            "/omeroweb_admin_tools/logs/data/",
            data=[
                ("container", "omeroserver_internal"),
                ("internal_file", "redis/dump.rdb"),
            ],
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
    assert (
        json.loads(invalid_container.content)["error"]
        == "Invalid log container selection."
    )
    assert invalid_container.status_code == 400
    assert (
        json.loads(invalid_internal_file.content)["error"]
        == "Invalid internal log selection."
    )
    assert invalid_internal_file.status_code == 400


def test_resource_monitoring_suppresses_external_url_behind_proxy(monkeypatch) -> None:
    """Verify resource monitoring suppresses external URL behind proxy.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resource monitoring suppresses external URL behind proxy.
    AssertionError when validation or the called operation fails.
    """
    request = RequestFactory().get(
        "/admin_tools/resource-monitoring/data/",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_HOST="omero.example.org",
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
        """Simulate get so the surrounding test controls that dependency.

        Inputs: `url` URL, `timeout` timeout seconds, `allow_redirects`, `params` SQL
        parameters. Output: `_RequestsResponse` result. Raises: AssertionError when validation or the called operation fails.
        """
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
    """Verify the cookie path for proxy rewrites root to proxy prefix safety boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions when cookie path for proxy rewrites root to proxy prefix accepts unsafe input.
    """
    assert (
        _cookie_path_for_proxy("/", "/admin_tools/resource-monitoring/grafana-proxy")
        == "/admin_tools/resource-monitoring/grafana-proxy/"
    )


def test_proxy_rewrites_set_cookie_path_for_grafana(monkeypatch) -> None:
    """Verify the proxy rewrites set cookie path for grafana safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when proxy rewrites set cookie path for grafana accepts unsafe input.
    """
    _install_proxy_backend_stub(
        monkeypatch,
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
        """Test double for dummy django request."""

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
    """Verify proxy HTTP request forwards extra headers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request forwards extra headers.
    """
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: `_RequestsResponse` result.
        """
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(200, payload=b'{"ok":true}')

    _install_proxy_backend_stub(monkeypatch, fake_request)

    class DummyDjangoRequest:
        """Test double for dummy django request."""

        method = "POST"
        body = b'{"user":"admin","credential":"test-value"}'
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": (
                "sessionid=omero-session; grafana_csrf_token=tok123; "
                "grafana_session=sess456"
            ),
            "X-Grafana-Csrf-Token": "tok123",
        }

    response = _proxy_http_request(
        DummyDjangoRequest(),
        "https://grafana:3000",
        "login",
        extra_forwarded_headers=("X-Grafana-Csrf-Token",),
        allowed_cookie_prefixes=("grafana_",),
    )

    assert response.status_code == 200
    assert captured["headers"]["X-Grafana-Csrf-Token"] == "tok123"
    assert (
        captured["headers"]["Cookie"]
        == "grafana_csrf_token=tok123; grafana_session=sess456"
    )


def test_proxy_http_request_ignores_absent_extra_headers(monkeypatch) -> None:
    """Verify proxy HTTP request ignores absent extra headers.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy HTTP request ignores absent extra headers.
    """
    captured = {}

    def fake_request(
        method, url, data=None, headers=None, timeout=10.0, allow_redirects=False
    ):
        """Simulate request so the surrounding test controls that dependency.

        Inputs: `method`, `url` URL, `data` payload, `headers`, `timeout` timeout
        seconds, `allow_redirects`. Output: `_RequestsResponse` result.
        """
        captured["headers"] = dict(headers or {})
        return _RequestsResponse(200, payload=b'{"ok":true}')

    _install_proxy_backend_stub(monkeypatch, fake_request)

    class DummyDjangoRequest:
        """Test double for dummy django request."""

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


def test_grafana_proxy_post_requires_django_csrf_token() -> None:
    """Verify grafana proxy post requires Django csrf token.

    Inputs: admin-tool fixtures. Output: fails on regressions in grafana proxy csrf behavior.
    """
    view_func = grafana_proxy
    assert getattr(view_func, "csrf_exempt", False) is False
    assert "POST" in _GRAFANA_PROXY_METHODS

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
    """Verify prometheus proxy is not csrf exempt.

    Inputs: admin-tool fixtures. Output: fails on regressions in prometheus proxy is not csrf exempt.
    """
    view_func = prometheus_proxy
    assert getattr(view_func, "csrf_exempt", False) is False, (
        "prometheus_proxy must not be decorated with @csrf_exempt"
    )
