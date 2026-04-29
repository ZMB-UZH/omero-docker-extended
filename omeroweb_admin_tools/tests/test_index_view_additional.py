from __future__ import annotations

import json
from http.client import HTTPMessage
from types import SimpleNamespace

import pytest
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory

from omeroweb_admin_tools.config import LogConfig
from omeroweb_admin_tools.services.log_query import LogEntry
from omeroweb_admin_tools.views import index_view


def _unwrap_view(func):
    """Handle unwrap view."""
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


def _payload(response):
    """Handle payload."""
    return json.loads(response.content.decode("utf-8"))


class _AttrUser:
    """Represent attr user."""

    def __init__(self, first_name, last_name, username):
        self.firstName = SimpleNamespace(val=first_name)
        self.lastName = SimpleNamespace(val=last_name)
        self.omeName = SimpleNamespace(val=username)


class _AttrGroup:
    """Represent attr group."""

    def __init__(self, name, permissions):
        self.name = SimpleNamespace(val=name)
        self._permissions = permissions

    def getDetails(self):
        """Return get details."""
        return SimpleNamespace(getPermissions=lambda: self._permissions)


class _PermissionText:
    """Represent permission text."""

    def __init__(self, text, *, read=False, write=False, annotate=False):
        self._text = text
        self._read = read
        self._write = write
        self._annotate = annotate

    def __str__(self):
        return self._text

    def isGroupRead(self):
        """Handle is group read."""
        return self._read

    def isGroupWrite(self):
        """Handle is group write."""
        return self._write

    def isGroupAnnotate(self):
        """Handle is group annotate."""
        return self._annotate


def test_proxy_helpers_cover_request_failures_and_cookie_edge_cases(
    monkeypatch,
) -> None:
    """Verify test proxy helpers cover request failures and behavior."""
    monkeypatch.setattr(
        index_view.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.RequestException("backend unavailable")
        ),
    )

    response = index_view._proxy_http_request(
        RequestFactory().get("/admin/grafana/api/health"),
        "https://grafana.example.test",
        "api/health",
        "",
        proxy_prefix="/admin/grafana",
    )

    assert response.status_code == 502
    assert _payload(response) == {"error": "Backend unreachable."}

    headers = HTTPMessage()
    headers.add_header("Content-Type", "text/html; charset=utf-8")
    headers.add_header(
        "Set-Cookie",
        "grafana_session=value; Path=/nested; Max-Age=invalid; HttpOnly",
    )
    headers.add_header("Location", "mailto:admin@example.test")
    proxied = index_view._build_proxied_response(
        b'\xff<a href="/dashboards">dash</a><script>{"appSubUrl":"","appUrl":"/"}</script>',
        status_code=200,
        headers=headers,
        base_url="https://grafana.example.test",
        proxy_prefix="/admin/grafana",
    )

    content = proxied.content.decode("utf-8")
    assert 'href="/admin/grafana/dashboards"' in content
    assert '"appSubUrl":"/admin/grafana"' in content
    assert '"appUrl":"/admin/grafana/"' in content
    assert proxied.cookies["grafana_session"]["path"] == "/admin/grafana/nested"
    assert proxied["Location"] == "mailto:admin@example.test"
    assert index_view._cookie_path_for_proxy("relative/path", "/admin/grafana") == (
        "relative/path"
    )
    assert index_view._origin_from_url("not-a-url") == ""
    assert (
        index_view._rewrite_proxied_location("login", "https://grafana.example", "")
        == "/login"
    )


def test_root_gated_views_cover_simple_render_and_guard_paths(monkeypatch) -> None:
    """Verify test root gated views cover simple render and behavior."""
    factory = RequestFactory()
    sentinel = JsonResponse({"error": "root required"}, status=403)

    monkeypatch.setattr(
        index_view,
        "render",
        lambda request, template, context: HttpResponse(
            json.dumps({"template": template, "context": context}),
            content_type="application/json",
        ),
    )

    view_response = _unwrap_view(index_view.resource_monitoring_view)(
        factory.get("/admin/resource-monitoring/"),
        conn=None,
    )
    assert _payload(view_response)["template"] == (
        "omeroweb_admin_tools/resource_monitoring.html"
    )

    storage_view_response = _unwrap_view(index_view.storage_view)(
        factory.get("/admin/storage/"),
        conn=None,
    )
    assert _payload(storage_view_response)["template"] == (
        "omeroweb_admin_tools/storage.html"
    )

    monkeypatch.setattr(index_view, "serialize_scripts", lambda: [{"id": "disk"}])
    diagnostics_view_response = _unwrap_view(index_view.server_database_testing_view)(
        factory.get("/admin/diagnostics/"),
        conn=None,
    )
    diagnostics_payload = _payload(diagnostics_view_response)
    assert diagnostics_payload["template"] == (
        "omeroweb_admin_tools/server_database_testing.html"
    )
    assert json.loads(diagnostics_payload["context"]["diagnostic_scripts"]) == [
        {"id": "disk"}
    ]

    monkeypatch.setattr(index_view, "_require_root_user", lambda *_args: sentinel)
    assert (
        _unwrap_view(index_view.resource_monitoring_data)(
            factory.get("/admin/resource-monitoring/data/"),
            conn=None,
        ).status_code
        == 403
    )
    assert (
        _unwrap_view(index_view.prometheus_proxy)(
            factory.get("/admin/prometheus/api/v1/status/runtimeinfo"),
            "api/v1/status/runtimeinfo",
            conn=None,
        ).status_code
        == 403
    )
    assert (
        _unwrap_view(index_view.storage_data)(
            factory.get("/admin/storage/data/"),
            conn=None,
        ).status_code
        == 403
    )
    assert (
        _unwrap_view(index_view.storage_quota_update)(
            factory.post("/admin/storage/quota/update/"),
            conn=None,
        ).status_code
        == 403
    )
    assert (
        _unwrap_view(index_view.storage_quota_import)(
            factory.post("/admin/storage/quota/import/"),
            conn=None,
        ).status_code
        == 403
    )
    assert (
        _unwrap_view(index_view.server_database_testing_run)(
            factory.post(
                "/admin/diagnostics/run/",
                data=json.dumps({"scripts": ["disk"]}).encode("utf-8"),
                content_type="application/json",
            ),
            conn=None,
        ).status_code
        == 403
    )


def test_identity_group_and_permission_helpers_cover_attribute_fallbacks() -> None:
    """Verify test identity group and permission helpers co behavior."""
    attr_user = _AttrUser("Ada", "Lovelace", "ada")
    attr_group = _AttrGroup("scientists", _PermissionText("rwra--"))
    bad_id = SimpleNamespace(getId=lambda: SimpleNamespace(getValue=lambda: "bad-id"))
    broken_permissions = SimpleNamespace(
        isGroupRead=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    non_root_request = RequestFactory().get("/admin")

    assert index_view._unwrap_rtype_value(None, default="fallback") == "fallback"
    assert index_view._unwrap_rtype_value(SimpleNamespace(val="wrapped")) == "wrapped"
    assert (
        index_view._unwrap_rtype_value(SimpleNamespace(getValue=lambda: "getter"))
        == "getter"
    )
    assert index_view._safe_full_name(attr_user) == "Ada Lovelace"
    assert index_view._safe_username(attr_user) == "ada"
    assert index_view._safe_group_name(attr_group) == "scientists"
    assert index_view._call_admin_listing(object(), "missing_method") == []
    assert index_view._safe_object_id(None) is None
    assert index_view._safe_object_id(bad_id) is None
    assert index_view._list_omero_group_names(None) == []
    assert (
        index_view._list_omero_group_names(
            SimpleNamespace(
                getAdminService=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
        )
        == []
    )
    assert index_view._permission_flag(None, "isGroupRead") is False
    assert index_view._permission_flag(broken_permissions, "isGroupRead") is False
    assert index_view._safe_group_permission_label(attr_group) == "Read-annotate"
    assert (
        index_view._safe_group_permission_label(
            _AttrGroup(
                "writers",
                _PermissionText("read-write", read=False, write=False),
            )
        )
        == "Read-write"
    )
    assert (
        index_view._safe_group_permission_label(
            _AttrGroup(
                "readers",
                _PermissionText("read-only", read=False, write=False),
            )
        )
        == "Read-only"
    )
    assert (
        index_view._safe_group_permission_label(
            _AttrGroup("private", _PermissionText("private", read=False, write=False))
        )
        == "Private"
    )

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            index_view, "current_username", lambda request, conn: "root"
        )
        assert index_view._require_root_user(non_root_request, conn=None) is None
        monkeypatch.setattr(
            index_view,
            "current_username",
            lambda request, conn: "alice",
        )
        response = index_view._require_root_user(non_root_request, conn=None)
        assert response.status_code == 403
    finally:
        monkeypatch.undo()


def test_logs_views_and_compose_helpers_cover_validation_paths(
    monkeypatch,
    tmp_path,
) -> None:
    """Verify test logs views and compose helpers cover val behavior."""
    log_config = LogConfig(
        loki_url="https://loki.example.test:3100",
        lookback_seconds=900,
        max_entries=5000,
        timeout_seconds=5.0,
        cache_max_bytes=1024,
        internal_file_batch_size=12,
        max_parallel_queries=4,
    )
    entries = [
        LogEntry(
            timestamp="2026-03-30T07:00:00+00:00",
            container="omeroserver",
            level="error",
            message="failed needle",
        ),
        LogEntry(
            timestamp="2026-03-30T07:01:00+00:00",
            container="omeroserver",
            level="info",
            message="healthy",
        ),
    ]
    captured = {}

    monkeypatch.setattr(index_view, "_require_root_user", lambda request, conn: None)
    monkeypatch.setattr(index_view, "optional_log_config", lambda: log_config)

    def _fetch_logs(
        config,
        containers,
        lookback_seconds,
        max_entries,
        *,
        internal_files=None,
        since_ns=None,
        text_query=None,
    ):
        """Handle fetch logs."""
        captured["containers"] = containers
        captured["internal_files"] = internal_files
        captured["since_ns"] = since_ns
        captured["text_query"] = text_query
        return list(entries)

    monkeypatch.setattr(index_view, "fetch_loki_logs", _fetch_logs)

    logs_data = _unwrap_view(index_view.logs_data)
    response = logs_data(
        RequestFactory().get(
            "/admin_tools/logs-data/",
            data={
                "container": ["omeroserver"],
                "internal_file": ["omeroserver_internal/Blitz-0.log", "invalid"],
                "lookback": "60",
                "limit": "5",
                "level": "error",
                "query": "needle",
                "since": "2026-03-30T06:56:57Z",
            },
        ),
        conn=None,
    )

    assert response.status_code == 200
    assert _payload(response) == {
        "entries": [
            {
                "timestamp": "2026-03-30T07:00:00+00:00",
                "container": "omeroserver",
                "level": "error",
                "message": "failed needle",
            }
        ]
    }
    assert captured["containers"] == ["omeroserver"]
    assert captured["internal_files"] == {
        "omeroserver_internal": {"Blitz-0.log"},
    }
    assert captured["text_query"] == "needle"
    assert captured["since_ns"] > 0

    assert (
        logs_data(
            RequestFactory().get(
                "/admin_tools/logs-data/",
                data={"container": ["omeroserver"], "lookback": "bad"},
            ),
            conn=None,
        ).status_code
        == 400
    )
    assert (
        logs_data(
            RequestFactory().get(
                "/admin_tools/logs-data/",
                data={"container": ["omeroserver"], "since": "not-a-date"},
            ),
            conn=None,
        ).status_code
        == 400
    )
    assert (
        logs_data(
            RequestFactory().get(
                "/admin_tools/logs-data/",
                data={"container": ["omeroserver"], "level": "verbose"},
            ),
            conn=None,
        ).status_code
        == 400
    )
    assert _payload(
        logs_data(RequestFactory().get("/admin_tools/logs-data/"), conn=None)
    ) == {"entries": []}

    monkeypatch.setattr(
        index_view,
        "fetch_loki_logs",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("backend exploded")),
    )
    assert (
        logs_data(
            RequestFactory().get(
                "/admin_tools/logs-data/",
                data={"container": ["omeroserver"]},
            ),
            conn=None,
        ).status_code
        == 502
    )

    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "root")
    root_status = _unwrap_view(index_view.root_status)
    assert _payload(
        root_status(RequestFactory().get("/admin_tools/root/"), conn=None)
    ) == {"is_root_user": True}
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    assert _payload(
        root_status(RequestFactory().get("/admin_tools/root/"), conn=None)
    ) == {"is_root_user": False}

    internal_log_labels = _unwrap_view(index_view.internal_log_labels)
    assert (
        internal_log_labels(
            RequestFactory().get(
                "/admin_tools/internal-log-labels/",
                data={"service": "bad-service"},
            ),
            conn=None,
        ).status_code
        == 400
    )

    missing_compose = index_view._load_compose_service_names(
        compose_file=str(tmp_path / "missing.yml")
    )
    assert missing_compose == []

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        "services:\n"
        "  redis:\n"
        "    image: redis:7\n"
        "  omeroserver:\n"
        "    image: server:1\n"
        "volumes:\n"
        "  data:\n",
        encoding="utf-8",
    )
    assert index_view._load_compose_service_names(str(compose_file)) == [
        "redis",
        "omeroserver",
    ]

    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            json=lambda: {"data": {"result": []}},
        ),
    )
    assert (
        index_view._prometheus_instant_query(
            "https://prometheus.example.test:9090",
            "up",
        )
        is None
    )


def test_proxy_quota_and_diagnostics_views_cover_error_paths(monkeypatch) -> None:
    """Verify test proxy quota and diagnostics views cover behavior."""
    grafana_proxy = _unwrap_view(index_view.grafana_proxy)
    prometheus_proxy = _unwrap_view(index_view.prometheus_proxy)
    storage_quota_data = _unwrap_view(index_view.storage_quota_data)
    storage_quota_update = _unwrap_view(index_view.storage_quota_update)
    storage_quota_import = _unwrap_view(index_view.storage_quota_import)
    storage_quota_template = _unwrap_view(index_view.storage_quota_template)
    diagnostics_run = _unwrap_view(index_view.server_database_testing_run)

    denied = JsonResponse({"error": "denied"}, status=403)
    monkeypatch.setattr(index_view, "_require_root_user", lambda request, conn: denied)
    assert (
        grafana_proxy(
            RequestFactory().get("/admin_tools/grafana/api/health"),
            "api/health",
            conn=None,
        ).status_code
        == 403
    )
    assert (
        storage_quota_data(
            RequestFactory().get("/admin_tools/storage/quota-data/"),
            conn=None,
        ).status_code
        == 403
    )
    assert (
        storage_quota_template(
            RequestFactory().get("/admin_tools/storage/quota-template/"),
            conn=None,
        ).status_code
        == 403
    )

    monkeypatch.setattr(index_view, "_require_root_user", lambda request, conn: None)

    grafana_method = grafana_proxy(
        RequestFactory().delete("/admin_tools/grafana/api/health"),
        "api/health",
        conn=None,
    )
    assert grafana_method.status_code == 405
    assert grafana_method["Allow"] == "GET, HEAD, OPTIONS, POST"
    assert _payload(grafana_method) == {
        "error": "Method not allowed",
        "allowed_methods": ["GET", "HEAD", "OPTIONS", "POST"],
    }

    prometheus_method = prometheus_proxy(
        RequestFactory().post("/admin_tools/prometheus/api/v1/query"),
        "api/v1/query",
        conn=None,
    )
    assert prometheus_method.status_code == 405
    assert prometheus_method["Allow"] == "GET, HEAD, OPTIONS"
    assert _payload(prometheus_method) == {
        "error": "Method not allowed",
        "allowed_methods": ["GET", "HEAD", "OPTIONS"],
    }

    monkeypatch.setattr(
        index_view,
        "_build_proxy_backend_urls",
        lambda *args, **kwargs: ["https://grafana.example.test"],
    )
    monkeypatch.setattr(
        index_view,
        "_proxy_http_request",
        lambda *args, **kwargs: HttpResponse(status=503),
    )
    unavailable = grafana_proxy(
        RequestFactory().get("/admin_tools/grafana/api/health"),
        "api/health",
        conn=None,
    )
    assert unavailable.status_code == 503

    monkeypatch.setattr(
        index_view,
        "_proxy_http_request",
        lambda *args, **kwargs: HttpResponse(status=404),
    )
    assert (
        prometheus_proxy(
            RequestFactory().get("/admin_tools/prometheus/api/v1/query"),
            "api/v1/query",
            conn=None,
        ).status_code
        == 404
    )

    assert (
        storage_quota_update(
            RequestFactory().get("/admin_tools/storage/quota-update/"),
            conn=None,
        ).status_code
        == 405
    )
    assert (
        storage_quota_update(
            RequestFactory().post(
                "/admin_tools/storage/quota-update/",
                data=json.dumps({"updates": {}}),
                content_type="application/json",
            ),
            conn=None,
        ).status_code
        == 400
    )
    monkeypatch.setattr(
        index_view,
        "upsert_quotas",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert (
        storage_quota_update(
            RequestFactory().post(
                "/admin_tools/storage/quota-update/",
                data=json.dumps({"updates": [{"group": "users", "quota_gb": 1}]}),
                content_type="application/json",
            ),
            conn=None,
        ).status_code
        == 500
    )

    assert (
        storage_quota_import(
            RequestFactory().post("/admin_tools/storage/quota-import/"),
            conn=None,
        ).status_code
        == 400
    )
    bad_encoding_request = RequestFactory().post("/admin_tools/storage/quota-import/")
    bad_encoding_request.FILES["file"] = SimpleUploadedFile(
        "group-quotas.csv",
        b"\xff",
        content_type="text/csv",
    )
    assert storage_quota_import(bad_encoding_request, conn=None).status_code == 400

    valid_import_request = RequestFactory().post("/admin_tools/storage/quota-import/")
    valid_import_request.FILES["file"] = SimpleUploadedFile(
        "group-quotas.csv",
        b"Group,Quota [GB]\nusers,5\n",
        content_type="text/csv",
    )
    monkeypatch.setattr(
        index_view,
        "import_quotas_csv",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert storage_quota_import(valid_import_request, conn=None).status_code == 500

    assert (
        diagnostics_run(
            RequestFactory().get("/admin_tools/diagnostics/run/"),
            conn=None,
        ).status_code
        == 405
    )
    assert (
        diagnostics_run(
            RequestFactory().post(
                "/admin_tools/diagnostics/run/",
                data="{broken",
                content_type="application/json",
            ),
            conn=None,
        ).status_code
        == 400
    )
    assert (
        diagnostics_run(
            RequestFactory().post(
                "/admin_tools/diagnostics/run/",
                data=json.dumps({"scripts": []}),
                content_type="application/json",
            ),
            conn=None,
        ).status_code
        == 400
    )
    assert (
        diagnostics_run(
            RequestFactory().post(
                "/admin_tools/diagnostics/run/",
                data=json.dumps({"scripts": [""]}),
                content_type="application/json",
            ),
            conn=None,
        ).status_code
        == 400
    )

    monkeypatch.setattr(
        index_view,
        "current_username",
        lambda request, conn: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        index_view,
        "run_diagnostic_script",
        lambda script_id: (_ for _ in ()).throw(RuntimeError("runner exploded")),
    )
    response = diagnostics_run(
        RequestFactory().post(
            "/admin_tools/diagnostics/run/",
            data=json.dumps({"scripts": ["disk-check"]}),
            content_type="application/json",
        ),
        conn=None,
    )
    assert response.status_code == 500
    assert "request_id" in _payload(response)
