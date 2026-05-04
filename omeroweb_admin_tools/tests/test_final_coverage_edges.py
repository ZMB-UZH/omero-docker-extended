from __future__ import annotations

from iter_test_helpers import next_or_fail

import json
import logging
import sys
from http.client import HTTPMessage
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from omeroweb_admin_tools import config as admin_config
from omeroweb_admin_tools.services import log_query, storage_quotas
from omeroweb_admin_tools.views import index_view, utils as view_utils


def _json_payload(response):
    """Return the JSON payload.

    Inputs: `response` response object. Output: `loads` result.
    """
    return json.loads(response.content.decode("utf-8"))


def _unwrap_view(func):
    """Return the unwrap view.

    Inputs: `func`. Output: `func`.
    """
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _User:
    """Test double for user behavior in this module."""

    def __init__(self, user_id, username):
        """Create `_User` with `user_id` and `username`.

        Inputs: `user_id`, `username`. Output: None.
        """
        self.id = _Value(user_id)
        self.omeName = _Value(username)

    def getId(self):
        """Return `_User`'s fake OMERO identifier.

        Inputs: none. Output: `self.id`.
        """
        return self.id

    def getOmeName(self):
        """Return the fake OMERO name.

        Inputs: none. Output: `self.omeName`.
        """
        return self.omeName


class _Group:
    """Test double for group behavior in this module."""

    def __init__(self, group_id, name):
        """Create `_Group` with `group_id` and `name`.

        Inputs: `group_id`, `name`. Output: None.
        """
        self.id = _Value(group_id)
        self.name = _Value(name)

    def getId(self):
        """Return `_Group`'s fake OMERO identifier.

        Inputs: none. Output: `self.id`.
        """
        return self.id

    def getName(self):
        """Return `_Group`'s fake object name.

        Inputs: none. Output: `self.name`.
        """
        return self.name

    @staticmethod
    def getDetails():
        """Return the details for `_Group`.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(getPermissions=lambda: "rw----")


def test_admin_config_and_root_user_decorator_cover_remaining_validation_edges(
    monkeypatch,
):
    """Verify admin config and root user decorator cover remaining validation edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in admin config and root user decorator cover remaining validation edges.
    """
    monkeypatch.setattr(
        admin_config,
        "require_env",
        lambda name, env_file=None, hint=None: "https://loki:3100/",
    )
    int_values = {
        "ADMIN_TOOLS_LOG_LOOKBACK_SECONDS": 30,
        "ADMIN_TOOLS_LOG_MAX_ENTRIES": 50,
        "ADMIN_TOOLS_LOG_CACHE_MAX_MB": 0,
        "ADMIN_TOOLS_LOG_INTERNAL_FILE_BATCH_SIZE": 12,
        "ADMIN_TOOLS_LOG_MAX_PARALLEL_QUERIES": 4,
    }
    monkeypatch.setattr(
        admin_config,
        "get_int_env",
        lambda name, env_file=None: int_values[name],
    )
    monkeypatch.setattr(
        admin_config,
        "get_float_env",
        lambda name, env_file=None: 2.5,
    )
    with pytest.raises(ValueError, match="positive integer"):
        admin_config.build_log_config()

    int_values["ADMIN_TOOLS_LOG_CACHE_MAX_MB"] = 128
    int_values["ADMIN_TOOLS_LOG_MAX_ENTRIES"] = 0
    with pytest.raises(ValueError, match="MAX_ENTRIES"):
        admin_config.build_log_config()

    int_values["ADMIN_TOOLS_LOG_MAX_ENTRIES"] = 50
    monkeypatch.setattr(
        admin_config,
        "get_float_env",
        lambda name, env_file=None: 0,
    )
    with pytest.raises(ValueError, match="TIMEOUT_SECONDS"):
        admin_config.build_log_config()

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")

    @view_utils.require_root_user
    def _sentinel(_request, *args, **kwargs):
        """Return the sentinel.

        Inputs: `_request`, `*args` positional arguments, `**kwargs` keyword arguments.
        Output: Django `HttpResponse`.
        """
        return HttpResponse("ok")

    response = _sentinel(RequestFactory().get("/admin/"), conn=None)

    assert response.status_code == 403
    assert _json_payload(response)["error"].startswith("PLEASE LOGIN AS ROOT USER")


def test_storage_quota_and_cache_helpers_cover_cleanup_and_type_guard_edges(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Check storage quota and cache helpers cover cleanup and type guard edges cleanup behavior.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` (Path) temporary path
    fixture, `caplog` (pytest.LogCaptureFixture) pytest log capture fixture. Output:
    `real_unlink` result. Raises: OSError when validation or the called operation fails.
    """
    monkeypatch.setenv(storage_quotas.MIN_GROUP_QUOTA_ENV, "0.10")
    monkeypatch.setenv(storage_quotas.DEFAULT_GROUP_QUOTA_ENV, "0.25")
    monkeypatch.setenv(storage_quotas.AUTO_GROUP_QUOTA_ENV, "false")

    path = tmp_path / "state.json"
    legacy_tmp = path.with_suffix(f"{path.suffix}.tmp")
    real_unlink = Path.unlink

    def _patched_unlink(self, missing_ok=False):
        """Return the patched unlink.

        Inputs: `missing_ok`. Output: `real_unlink` result. Raises: OSError when validation or the called operation fails.
        """
        if self == legacy_tmp:
            raise OSError("legacy cleanup blocked")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _patched_unlink, raising=False)
    monkeypatch.setattr(
        storage_quotas.os,
        "chmod",
        lambda target, mode: (_ for _ in ()).throw(RuntimeError("chmod failed")),
    )
    caplog.set_level(logging.DEBUG, logger=storage_quotas.logger.name)
    with pytest.raises(RuntimeError, match="chmod failed"):
        storage_quotas._write_state(path, {"quotas_gb": {}, "logs": []})
    assert list(tmp_path.glob("state.json.tmp_*")) == []
    assert any(
        record.levelname == "DEBUG" and "storage_quotas.py" in record.message
        for record in caplog.records
    )

    state_path = tmp_path / "quotas.json"
    state_path.write_text(
        json.dumps(
            {
                storage_quotas.STATE_SCHEMA_VERSION_KEY: storage_quotas.STATE_SCHEMA_VERSION,
                "quotas_gb": [],
                "logs": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOOLS_QUOTA_STATE_PATH", str(state_path))
    with pytest.raises(TypeError, match="Expected 'quotas_gb' to be a dict"):
        storage_quotas.upsert_quotas([("group-a", 1.0)])

    state = storage_quotas.get_state()
    assert state["quotas_gb"] == {}
    assert state["logs"] == []

    cache = log_query._InMemoryTTLCache(
        ttl_seconds=5.0,
        max_items=4,
        max_bytes=64,
        size_estimator=lambda value: len(str(value)),
    )

    def _loader():
        """Return the loader.

        Inputs: none. Output: `str`.
        """
        cache._values["key"] = log_query._CacheRecord(
            value="old",
            expires_at=999.0,
            size_bytes=3,
        )
        cache._total_size_bytes = 3
        return "new"

    assert cache.get_or_load("key", _loader) == "new"
    assert cache._values["key"].value == "new"
    assert cache._total_size_bytes == 3


def test_admin_index_helpers_and_views_cover_remaining_proxy_compose_and_quota_edges(
    monkeypatch,
):
    """Verify admin index helpers and views cover remaining proxy compose and quota edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in admin index helpers and views cover remaining proxy compose and quota edges.
    RuntimeError when validation or the called operation fails.
    """
    headers = HTTPMessage()
    headers.add_header("Content-Type", "text/html; charset=utf-8")
    headers.add_header("Cache-Control", "no-store")
    proxied = index_view._build_proxied_response(
        b"<html></html>",
        status_code=200,
        headers=headers,
        base_url="https://grafana.example.test",
        proxy_prefix="/admin/grafana",
    )
    assert proxied["Cache-Control"] == "no-store"

    unavailable = index_view._grafana_unavailable_response(
        proxy_prefix="/admin/grafana",
        attempted_backends=[],
        status_code=502,
    )
    assert "configured Grafana endpoints" in unavailable.content.decode("utf-8")

    blank_group = _Group(1, "")
    valid_group = _Group(2, "scientists")
    user = _User(5, "alice")

    class _AdminService:
        """Test double for admin service behavior in this module."""

        @staticmethod
        def lookupExperimenters():
            """Return the lookup Experimenters for `_AdminService`.

            Inputs: none. Output: `list`.
            """
            return [user]

        @staticmethod
        def lookupGroups():
            """Return the lookup Groups for `_AdminService`.

            Inputs: none. Output: `list`.
            """
            return [blank_group, valid_group]

        @staticmethod
        def containedGroups(*args):
            """Return the contained Groups for `_AdminService`.

            Inputs: `*args` positional arguments. Output: contained groups result.
            """
            identifier = args[0] if args else None
            return [blank_group] if identifier is not None else [valid_group]

        @staticmethod
        def containedExperimenters(*args):
            """Record the contained experimenters call on `_AdminService` for later assertions.

            Inputs: `*args` positional arguments. Output: None. Raises: RuntimeError
            when validation or the called operation fails.
            """
            raise RuntimeError("enumeration failed")

    principals = index_view._list_all_users_and_groups(
        SimpleNamespace(getAdminService=_AdminService)
    )
    assert principals[0]["alice"] == ""
    assert principals[1] == {"scientists"}

    monkeypatch.setattr(
        index_view,
        "_docker_compose_json",
        lambda command: {"services": []},
    )
    assert index_view._load_compose_healthcheck_config() == {}
    monkeypatch.setattr(
        index_view,
        "_docker_compose_json",
        lambda command: {"services": ["invalid"]},
    )
    assert index_view._load_compose_healthcheck_config() == {}

    services = index_view._build_target_service_status(
        [{"labels": {"job": "folder/MYSERVICE"}, "health": "up"}],
        ["myservice"],
    )
    assert services[0]["health"] == "up"
    services = index_view._build_target_service_status(
        [{"labels": {"job": "folder/OMERO_WEB"}, "health": "up"}],
        ["omero-web"],
    )
    assert services[0]["service"] == "omero-web"

    factory = RequestFactory()
    monkeypatch.setattr(index_view, "_require_root_user", lambda *_args: None)
    monkeypatch.setattr(
        index_view.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            index_view.requests.RequestException("offline")
        ),
    )
    monitoring = _unwrap_view(index_view.resource_monitoring_data)(
        factory.get("/admin/resource-monitoring/data/"),
        conn=SimpleNamespace(),
    )
    assert monitoring.status_code == 200
    assert _json_payload(monitoring)["prometheus"]["targets_overview"]["active"] == 0

    responses = iter([HttpResponse(status=502), HttpResponse(status=504)])
    monkeypatch.setattr(
        index_view,
        "_internal_service_base_url",
        lambda *args, **kwargs: "https://prometheus.example.test",
    )
    monkeypatch.setattr(
        index_view,
        "_build_proxy_backend_urls",
        lambda *args, **kwargs: ["https://primary", "https://secondary"],
    )
    monkeypatch.setattr(
        index_view,
        "_normalize_proxy_request_target",
        lambda subpath: (subpath, ""),
    )
    monkeypatch.setattr(
        index_view,
        "_proxy_http_request",
        lambda *args, **kwargs: next_or_fail(responses),
    )
    proxy_response = _unwrap_view(index_view.prometheus_proxy)(
        factory.get("/admin/prometheus/api/v1/targets"),
        "api/v1/targets",
        conn=SimpleNamespace(),
    )
    assert proxy_response.status_code == 504

    responses = iter(
        [HttpResponse("bad-1", status=502), HttpResponse("bad-2", status=502)]
    )
    fallback_proxy_response = _unwrap_view(index_view.prometheus_proxy)(
        factory.get("/admin/prometheus/api/v1/query"),
        "api/v1/query",
        conn=SimpleNamespace(),
    )
    assert fallback_proxy_response.status_code == 502
    assert fallback_proxy_response.content == b"bad-2"

    query_service = SimpleNamespace(
        projection=lambda *args, **kwargs: [
            [None, "alice", None, "scientists", 1024],
        ]
    )
    storage_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=lambda value: None),
        getQueryService=lambda: query_service,
    )
    monkeypatch.setattr(
        index_view,
        "_list_all_users_and_groups",
        lambda conn: (
            {"alice": "Alice Example"},
            {"scientists"},
            {"scientists": "Private"},
            {"alice": {"scientists"}},
            {"scientists": {"alice"}},
        ),
    )
    monkeypatch.setattr(
        index_view.shutil,
        "disk_usage",
        lambda path: (_ for _ in ()).throw(RuntimeError("disk usage failed")),
    )
    monkeypatch.setattr(
        index_view,
        "reconcile_quotas",
        lambda known_groups: (_ for _ in ()).throw(RuntimeError("quota failure")),
    )
    monkeypatch.setattr(
        index_view,
        "is_quota_enforcement_available",
        lambda: (_ for _ in ()).throw(RuntimeError("marker failure")),
    )
    storage = _unwrap_view(index_view.storage_data)(
        factory.get("/admin/storage/data/"),
        conn=storage_conn,
    )
    storage_payload = _json_payload(storage)
    assert storage_payload["totals"]["data_root_total_bytes"] is None
    assert storage_payload["quotas"]["quota_enforcement_available"] is False

    monkeypatch.setattr(
        index_view,
        "get_quota_state",
        lambda: {"quotas_gb": {"scientists": 5.0}, "logs": ["state-log"]},
    )
    monkeypatch.setattr(
        index_view,
        "_list_omero_group_names",
        lambda conn: ["scientists"],
    )
    quota_data = _unwrap_view(index_view.storage_quota_data)(
        factory.get("/admin/storage/quotas/"),
        conn=storage_conn,
    )
    assert (
        _json_payload(quota_data)["reconcile"]["quota_enforcement_available"] is False
    )

    update = _unwrap_view(index_view.storage_quota_update)(
        factory.post(
            "/admin/storage/quota/update/",
            data=json.dumps({"updates": [123]}),
            content_type="application/json",
        ),
        conn=storage_conn,
    )
    assert update.status_code == 400


def test_system_diagnostics_import_success_path_caches_psycopg2_module(
    monkeypatch,
):
    """Verify the system diagnostics import success path caches psycopg2 module safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when system diagnostics import success path caches psycopg2 module accepts unsafe input.
    """
    from omeroweb_admin_tools.services import system_diagnostics

    fake_psycopg2 = SimpleNamespace(connect=lambda *args, **kwargs: None)
    previous_cached = system_diagnostics._get_cached_psycopg2_module()
    previous_module = sys.modules.get("psycopg2")
    try:
        system_diagnostics._set_cached_psycopg2_module(
            system_diagnostics._PSYCOPG2_UNSET
        )
        sys.modules["psycopg2"] = fake_psycopg2
        assert system_diagnostics._load_psycopg2() is fake_psycopg2
    finally:
        system_diagnostics._set_cached_psycopg2_module(previous_cached)
        if previous_module is None:
            sys.modules.pop("psycopg2", None)
        else:
            sys.modules["psycopg2"] = previous_module
