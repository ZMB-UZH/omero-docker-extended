"""Managed-monitoring transport never bypasses peer or hostname verification."""

import ssl
from unittest.mock import Mock

import pytest
from django.test import RequestFactory

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.services import log_query, monitoring_tls
from omeroweb_admin_tools.views import index_view


def test_legacy_installation_retains_platform_verification(monkeypatch):
    """Inputs: unset managed CA. Output: unchanged verified platform defaults."""
    monkeypatch.delenv("ADMIN_TOOLS_TLS_CA_FILE", raising=False)
    assert monitoring_tls.request_options("https://metrics.example.test") == {}
    assert monitoring_tls.connection_options("https://metrics.example.test") == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://metrics.example.test",  # DevSkim: ignore DS137138 -- rejected plaintext fixture
        "https:///missing",
        "https://u:p@metrics.example.test",
        "https://@metrics.example.test",
    ],
)
def test_managed_client_rejects_plaintext_and_url_credentials(
    monkeypatch, tmp_path, url
):
    """Inputs: unsafe URL. Output: rejection before connecting or forwarding auth."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "trust.pem"))
    with pytest.raises(ValueError, match="require an HTTPS URL"):
        monitoring_tls.request_options(url)


def test_requests_use_explicit_ca_without_redirect_downgrades(monkeypatch, tmp_path):
    """Inputs: managed CA. Output: verified requests with redirects disabled."""
    authority = tmp_path / "trust.pem"
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(authority))
    assert monitoring_tls.request_options("https://metrics.example.test/api/query") == {
        "verify": str(authority),
        "allow_redirects": False,
    }


@pytest.mark.parametrize(
    "minimum",
    [
        ssl.TLSVersion.TLSv1_2,  # DevSkim: ignore DS440001 -- tests minimum policy
        ssl.TLSVersion.TLSv1_3,  # DevSkim: ignore DS440001 -- tests stricter platform policy
    ],
)
def test_proxy_uses_fresh_verified_context_on_each_connection(
    monkeypatch, tmp_path, minimum
):
    """Inputs: successive connections. Output: independent verified SSL contexts."""
    authority = tmp_path / "trust.pem"
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(authority))
    contexts = [
        ssl.SSLContext(
            ssl.PROTOCOL_TLS_CLIENT,  # DevSkim: ignore DS440072 -- verified negotiating client
        )
        for _ in range(2)
    ]
    for context in contexts:
        context.minimum_version = minimum
    factory = Mock(side_effect=contexts)
    monkeypatch.setattr(monitoring_tls.ssl, "create_default_context", factory)
    for expected in contexts:
        assert monitoring_tls.connection_options("https://metrics.example.test") == {
            "context": expected
        }
        assert expected.verify_mode == ssl.CERT_REQUIRED
        assert expected.check_hostname is True
        assert expected.minimum_version == minimum
    assert factory.call_count == 2
    factory.assert_called_with(cafile=str(authority))


def test_missing_bundle_never_disables_verification(monkeypatch, tmp_path):
    """Inputs: missing CA file. Output: explicit failure, never disabled verification."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "missing.pem"))
    with pytest.raises(FileNotFoundError):
        monitoring_tls.connection_options("https://metrics.example.test")


@pytest.mark.parametrize("scheme", [None, "", "invalid"])
def test_managed_backend_defaults_to_https(monkeypatch, tmp_path, scheme):
    """Inputs: managed CA and URLs. Output: HTTPS defaults, preserved explicit URLs."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "trust.pem"))
    monkeypatch.delenv("ADMIN_TOOLS_GRAFANA_URL", raising=False)
    monkeypatch.delenv("ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME", raising=False)
    if scheme is not None:
        monkeypatch.setenv("ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME", scheme)
    assert (
        index_view._internal_service_base_url(
            "ADMIN_TOOLS_GRAFANA_URL", default_host="grafana", default_port=3000
        )
        == "https://grafana:3000"
    )
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_URL", "https://custom.example.test:3443")
    assert (
        index_view._internal_service_base_url(
            "ADMIN_TOOLS_GRAFANA_URL", default_host="grafana", default_port=3000
        )
        == "https://custom.example.test:3443"
    )


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_proxy_fails_closed_for_plaintext_or_missing_trust(
    monkeypatch, tmp_path, scheme
):
    """Inputs: unsafe TLS setup. Output: controlled 502 without a network request."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "missing.pem"))
    connections = Mock(side_effect=AssertionError("Network request attempted"))
    monkeypatch.setattr(index_view, "HTTPConnection", connections)
    monkeypatch.setattr(index_view, "HTTPSConnection", connections)
    response = index_view._proxy_http_request(
        RequestFactory().get("/admin/grafana/api/health"),
        f"{scheme}://grafana.example.test",
        "api/health",
        "",
        proxy_prefix="/admin/grafana",
    )
    assert response.status_code == 502
    assert response.content == b'{"error": "Backend unreachable."}'
    connections.assert_not_called()


def test_probe_reports_unreadable_trust_without_crashing(monkeypatch, tmp_path):
    """Inputs: unreadable CA. Output: bounded connection-failure diagnostics."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "missing.pem"))
    monkeypatch.setattr(index_view.requests, "get", Mock(side_effect=OSError("CA")))
    result = index_view._probe_http_url("https://grafana.example.test")
    assert result == {"ok": False, "status": 0, "error": "Connection failed"}


def test_loki_plaintext_rejection_uses_existing_error_boundary(monkeypatch, tmp_path):
    """Inputs: plaintext Loki URL. Output: controlled error before any request."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "trust.pem"))
    request = Mock(side_effect=AssertionError("Plaintext request attempted"))
    monkeypatch.setattr(log_query.requests, "get", request)
    config = LogConfig(
        "http://loki",  # DevSkim: ignore DS137138 -- asserts no plaintext request occurs
        60,
        10,
        1.0,
        1024,
        10,
        1,
    )
    with pytest.raises(RuntimeError, match="Loki request failed"):
        log_query._execute_loki_query(config, '{job="fixture"}', 60, 10)
    request.assert_not_called()


def test_loki_unreadable_trust_uses_existing_error_boundary(monkeypatch, tmp_path):
    """Inputs: missing CA. Output: existing Loki error boundary with trust retained."""
    monkeypatch.setenv("ADMIN_TOOLS_TLS_CA_FILE", str(tmp_path / "missing.pem"))
    request = Mock(side_effect=OSError("CA"))
    monkeypatch.setattr(log_query.requests, "get", request)
    config = LogConfig("https://loki", 60, 10, 1.0, 1024, 10, 1)
    with pytest.raises(RuntimeError, match="Loki request failed"):
        log_query._execute_loki_query(config, '{job="fixture"}', 60, 10)
    assert request.call_args.kwargs["verify"] == str(tmp_path / "missing.pem")
