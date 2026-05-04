from __future__ import annotations

import inspect
import json
from http.client import HTTPMessage
from types import SimpleNamespace
from urllib.parse import urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
import pytest

from omeroweb_admin_tools.views import index_view

GRAFANA_URL = "https://grafana.example.test:3000"
EXTERNAL_GRAFANA_URL = "https://grafana.example.org"


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self.val = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self.val`.
        """
        return self.val


class _User:
    """Test double for user behavior in this module."""

    def __init__(self, user_id, username, first_name="", last_name=""):
        """Create `_User` with `user_id`, `username`, `first_name`, and `last_name`.

        Inputs: `user_id`, `username`, `first_name`, `last_name`. Output: None.
        """
        self.id = _Value(user_id)
        self.omeName = _Value(username)
        self.firstName = _Value(first_name)
        self.lastName = _Value(last_name)

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

    def getFirstName(self):
        """Return the fake first name.

        Inputs: none. Output: `self.firstName`.
        """
        return self.firstName

    def getLastName(self):
        """Return the fake last name value used by this test double.

        Inputs: none. Output: `self.lastName`.
        """
        return self.lastName


class _Group:
    """Test double for group behavior in this module."""

    def __init__(self, group_id, name, permissions):
        """Create `_Group` with `group_id`, `name`, and `permissions`.

        Inputs: `group_id`, `name`, `permissions`. Output: None.
        """
        self.id = _Value(group_id)
        self.name = _Value(name)
        self.permissions = permissions

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

    def getDetails(self):
        """Return the details for `_Group`.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(getPermissions=lambda: self.permissions)


class _Permissions:
    """Test double for permissions behavior in this module."""

    def __init__(
        self,
        label,
        *,
        group_read=True,
        group_write=False,
        group_annotate=False,
    ):
        """Create `_Permissions` with `label`.

        Inputs: `label`, `group_read`, `group_write`, `group_annotate`. Output: None.
        """
        self._label = label
        self._group_read = group_read
        self._group_write = group_write
        self._group_annotate = group_annotate

    def __str__(self):
        """Return `_Permissions` as test-readable text.

        Inputs: none. Output: `self._label`.
        """
        return self._label

    def isGroupRead(self):
        """Return whether `_Permissions` grants group-read access.

        Inputs: none. Output: `self._group_read`.
        """
        return self._group_read

    def isGroupWrite(self):
        """Return whether `_Permissions` grants group-write access.

        Inputs: none. Output: `self._group_write`.
        """
        return self._group_write

    def isGroupAnnotate(self):
        """Return whether `_Permissions` grants group-annotate access.

        Inputs: none. Output: `self._group_annotate`.
        """
        return self._group_annotate


class _AdminService:
    """Test double for admin service behavior in this module."""

    def __init__(self, users, groups, groups_by_user, users_by_group):
        """Create `_AdminService` with `users`, `groups`, `groups_by_user`, and `users_by_group`.

        Inputs: `users`, `groups`, `groups_by_user`, `users_by_group`. Output: None.
        """
        self._users = users
        self._groups = groups
        self._groups_by_user = groups_by_user
        self._users_by_group = users_by_group

    def lookupExperimenters(self):
        """Return the lookup Experimenters for `_AdminService`.

        Inputs: none. Output: `list`.
        """
        return list(self._users)

    def lookupGroups(self):
        """Return the lookup Groups for `_AdminService`.

        Inputs: none. Output: `list`.
        """
        return list(self._groups)

    def containedGroups(self, *args):
        """Return the contained Groups for `_AdminService`.

        Inputs: `*args` positional arguments. Output: `list`.
        """
        identifier = args[0] if args else None
        if identifier is None:
            return list(self._groups)
        return list(self._groups_by_user.get(int(identifier), []))

    def containedExperimenters(self, *args):
        """Return the contained Experimenters for `_AdminService`.

        Inputs: `*args` positional arguments. Output: `list`.
        """
        identifier = args[0] if args else None
        if identifier is None:
            return list(self._users)
        return list(self._users_by_group.get(int(identifier), []))


def test_proxy_path_and_redirect_safety_helpers():
    """Verify the proxy path and redirect safety helpers safety boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions when proxy path and redirect safety helpers accepts unsafe input.
    """
    assert index_view._normalize_proxy_prefix(" /grafana/ ") == "/grafana"
    assert index_view._safe_redirect_segment("../escape", "fallback") == "fallback"
    assert (
        index_view._safe_redirect_segment("server-infra", "fallback") == "server-infra"
    )
    assert (
        index_view._safe_dashboard_uid("https://evil.example/x", "dashboard")
        == "dashboard"
    )
    assert (
        index_view._safe_dashboard_uid("folder/main-board", "dashboard") == "main-board"
    )
    assert index_view._normalize_proxy_request_target("/grafana/../api/health") == (
        "api/health",
        "",
    )
    try:
        index_view._normalize_proxy_request_target(
            "https://grafana.example.org/grafana/api/live?watch=1"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected absolute proxy target to be rejected")


def test_normalize_proxy_request_target_rejects_path_traversal():
    """Confirm normalize proxy request target rejects path traversal is rejected at the boundary.

    Inputs: admin-tool fixtures. Output: fails on regressions when normalize proxy request target rejects path traversal accepts unsafe input.
    """
    try:
        index_view._normalize_proxy_request_target("../../escape")
    except ValueError as exc:
        assert "Invalid proxy target" in str(exc)
    else:
        raise AssertionError("Expected ValueError for traversal")


def test_build_proxied_response_rewrites_html_locations_and_cookies():
    """Check build proxied response rewrites html locations and cookies renders the expected surface.

    Inputs: admin-tool fixtures. Output: fails on regressions in build proxied response rewrites html locations and cookies.
    """
    headers = HTTPMessage()
    headers.add_header("Content-Type", "text/html; charset=utf-8")
    headers.add_header("Location", f"{GRAFANA_URL}/login")
    headers.add_header(
        "Set-Cookie",
        "grafana_session=session; Path=/; HttpOnly; Secure; SameSite=Lax",
    )
    html = (
        '<a href="/dashboards">dash</a>'
        '<img src="/public/logo.svg">'
        '<form action="/login"></form>'
        '<script>{"appSubUrl":"","appUrl":"/"}</script>'
        f"{GRAFANA_URL}"
    ).encode("utf-8")

    response = index_view._build_proxied_response(
        html,
        status_code=200,
        headers=headers,
        base_url=GRAFANA_URL,
        proxy_prefix="/admin/grafana",
    )

    content = response.content.decode("utf-8")
    assert 'href="/admin/grafana/dashboards"' in content
    assert 'src="/admin/grafana/public/logo.svg"' in content
    assert 'action="/admin/grafana/login"' in content
    assert '"appSubUrl":"/admin/grafana"' in content
    assert '"appUrl":"/admin/grafana/"' in content
    assert response["Location"] == "/admin/grafana/login"
    assert response.cookies["grafana_session"]["path"] == "/admin/grafana/"


def test_proxy_backend_helpers_build_expected_urls_and_fallbacks(monkeypatch):
    """Verify proxy backend helpers build expected URLs and fallbacks.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in proxy backend helpers build expected URLs and fallbacks.
    """
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "infra")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "server-overview")

    assert index_view._cookie_path_for_proxy("/", "/admin/grafana") == "/admin/grafana/"
    assert index_view._origin_from_url("https://grafana.example.org:8443/app") == (
        "https://grafana.example.org:8443"
    )
    assert (
        index_view._rewrite_proxied_location(
            f"{GRAFANA_URL}/login",
            GRAFANA_URL,
            "/admin/grafana",
        )
        == "/admin/grafana/login"
    )
    assert index_view._build_proxy_backend_urls(
        GRAFANA_URL,
        EXTERNAL_GRAFANA_URL,
    ) == [GRAFANA_URL, EXTERNAL_GRAFANA_URL]

    home = index_view._grafana_proxy_home_fallback_response("/admin/grafana")
    prometheus_home = index_view._prometheus_proxy_home_fallback_response(
        "/admin/prometheus"
    )
    unavailable = index_view._grafana_unavailable_response(
        proxy_prefix="/admin/grafana",
        attempted_backends=[GRAFANA_URL, EXTERNAL_GRAFANA_URL],
        status_code=502,
    )

    assert home.status_code == 302
    assert home["Location"] == "/admin/grafana/d/infra/server-overview"
    assert prometheus_home.status_code == 302
    assert prometheus_home["Location"] == "/admin/prometheus/targets"
    assert unavailable.status_code == 503
    assert "grafana.example.test:3000" in unavailable.content.decode("utf-8")
    assert unavailable["Retry-After"] == "30"


def test_request_and_public_url_helpers_cover_reverse_proxy_cases():
    """Verify request and public URL helpers cover reverse proxy cases.

    Inputs: admin-tool fixtures. Output: fails on regressions in request and public URL helpers cover reverse proxy cases.
    """
    factory = RequestFactory()
    proxied = factory.get(
        "/",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_HOST="omero.example.org",
        HTTP_X_FORWARDED_FOR="198.51.100.10",
        HTTP_HOST="omero.example.org:4080",
    )
    direct = factory.get("/", HTTP_HOST="localhost:4080")
    ipv6_direct = factory.get("/", HTTP_HOST="[2001:db8::10]:4080")

    assert index_view._is_internal_hostname("grafana") is True
    assert index_view._is_internal_hostname("example.org") is False
    assert index_view._is_behind_reverse_proxy(proxied) is True
    assert index_view._safe_request_host(direct) == "localhost"
    assert index_view._safe_request_host(ipv6_direct) == "2001:db8::10"
    assert (
        index_view._build_public_service_url(
            f"{GRAFANA_URL}/grafana",
            "http",
            "omero.example.org",
            3000,
            is_proxied=True,
            forwarded_proto="https",
        )
        == "https://omero.example.org/grafana"
    )
    assert (
        index_view._build_public_service_url(
            GRAFANA_URL,
            "http",
            "2001:db8::1",
            3000,
        )
        == "https://[2001:db8::1]:3000"
    )


def test_grafana_dashboard_urls_sanitize_configured_dashboard_segments(
    monkeypatch,
) -> None:
    """Check that grafana dashboard URLs sanitize configured dashboard segments keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in grafana dashboard URLs sanitize configured dashboard segments.
    """
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "https://evil.example")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "../escape")

    urls = index_view._grafana_dashboard_urls(
        "https://monitor.example.org/grafana",
        "orgId=1",
    )

    assert (
        urls["dashboard_url"] == "/d/omero-infrastructure/server-infrastructure?orgId=1"
    )
    assert (
        urls["dashboard_external_url"]
        == "https://monitor.example.org/grafana/d/omero-infrastructure/server-infrastructure?orgId=1"
    )


def test_validation_and_identity_helpers_cover_remaining_guard_paths(monkeypatch):
    """Verify validation and identity helpers cover remaining guard paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in validation and identity helpers cover remaining guard paths.
    """
    with pytest.raises(ValueError):
        index_view._validated_http_url("grafana.example.test")
    with pytest.raises(ValueError):
        index_view._validated_http_url("https://user@grafana.example.test")
    with pytest.raises(ValueError):
        index_view._validated_http_url("https://grafana.example.test/#frag")
    with pytest.raises(ValueError):
        index_view._validated_http_url("https://grafana.example.test/?refresh=5s")

    assert (
        index_view._validated_http_url(
            "https://grafana.example.test/?refresh=5s",
            allow_query=True,
        )
        == "https://grafana.example.test?refresh=5s"
    )

    monkeypatch.setenv("ADMIN_TOOLS_INTERNAL_SERVICE_SCHEME", "ftp")
    internal_service_base_url = index_view._internal_service_base_url(
        "ADMIN_TOOLS_FAKE_URL",
        default_host="grafana",
        default_port=3000,
    )
    parsed_internal_service = urlsplit(internal_service_base_url)
    assert parsed_internal_service.scheme == "http"
    assert parsed_internal_service.netloc == "grafana:3000"

    assert index_view._safe_redirect_segment("", "fallback") == "fallback"
    assert (
        index_view._safe_redirect_segment("https://evil.example.test", "fallback")
        == "fallback"
    )
    assert index_view._safe_dashboard_uid("", "dashboard") == "dashboard"

    with pytest.raises(ValueError):
        index_view._normalize_proxy_request_target("/grafana/%00/api")

    assert (
        index_view._build_public_service_url(
            f"{GRAFANA_URL}/grafana",
            "http",
            "omero.example.org",
            3000,
        )
        == "https://omero.example.org:3000/grafana"
    )
    assert index_view._unwrap_rtype_value("raw") == "raw"
    assert index_view._safe_username(SimpleNamespace()) == ""
    assert index_view._safe_group_name(SimpleNamespace()) == ""
    assert index_view._safe_object_id(SimpleNamespace()) is None
    assert index_view._permission_flag(SimpleNamespace(), "missing") is False


def test_admin_listing_helpers_collect_users_groups_and_permissions():
    """Verify admin listing helpers collect users groups and permissions.

    Inputs: admin-tool fixtures. Output: fails on regressions in admin listing helpers collect users groups and permissions.
    """
    users = [
        _User(1, "alice", "Alice", "Admin"),
        _User(2, "bob", "Bob", "Builder"),
    ]
    groups = [
        _Group(10, "users_private", _Permissions("rw----")),
        _Group(11, "users_collab", _Permissions("rwra--", group_annotate=True)),
    ]
    admin_service = _AdminService(
        users=users,
        groups=groups,
        groups_by_user={
            1: [groups[0], groups[1]],
            2: [groups[1]],
        },
        users_by_group={
            10: [users[0]],
            11: [users[0], users[1]],
        },
    )
    conn = SimpleNamespace(getAdminService=lambda: admin_service)

    assert index_view._call_admin_listing(admin_service, "lookupGroups") == groups
    assert index_view._safe_object_id(groups[0]) == 10
    assert index_view._list_omero_group_names(conn) == ["users_collab", "users_private"]

    users_map, group_names, permissions, groups_by_user, users_by_group = (
        index_view._list_all_users_and_groups(conn)
    )

    assert users_map == {"alice": "Alice Admin", "bob": "Bob Builder"}
    assert group_names == {"users_private", "users_collab"}
    assert permissions["users_collab"] == "Read-annotate"
    assert groups_by_user["alice"] == {"users_private", "users_collab"}
    assert users_by_group["users_collab"] == {"alice", "bob"}


def test_admin_listing_helpers_skip_incomplete_memberships_and_runtime_state():
    """Verify admin listing helpers skip incomplete memberships and runtime state.

    Inputs: admin-tool fixtures. Output: fails on regressions in admin listing helpers skip incomplete memberships and runtime state.
    """
    missing_user = SimpleNamespace(
        getId=lambda: _Value(3),
        getOmeName=lambda: _Value(""),
    )
    unnamed_group = SimpleNamespace(
        getId=lambda: _Value(22),
        getName=lambda: _Value(""),
        getDetails=lambda: SimpleNamespace(
            getPermissions=lambda: _Permissions("rw----")
        ),
    )
    valid_group = _Group(23, "team", _Permissions("private", group_read=False))
    username_less_user = SimpleNamespace(
        getOmeName=lambda: _Value(""),
        getFirstName=lambda: _Value("Ghost"),
        getLastName=lambda: _Value("User"),
    )

    class _SparseAdminService:
        """Test double for sparse admin service behavior in this module."""

        @staticmethod
        def lookupExperimenters():
            """Return the lookup Experimenters for `_SparseAdminService`.

            Inputs: none. Output: `list`.
            """
            return [missing_user]

        @staticmethod
        def lookupGroups():
            """Return the lookup Groups for `_SparseAdminService`.

            Inputs: none. Output: `list`.
            """
            return [unnamed_group, valid_group]

        @staticmethod
        def containedGroups(*args):
            """Return the contained Groups for `_SparseAdminService`.

            Inputs: `*args` positional arguments. Output: `list`.
            """
            identifier = args[0] if args else None
            if identifier == 3:
                return [SimpleNamespace(getName=lambda: _Value(""))]
            return []

        @staticmethod
        def containedExperimenters(*args):
            """Return the contained Experimenters for `_SparseAdminService`.

            Inputs: `*args` positional arguments. Output: `list`.
            """
            identifier = args[0] if args else None
            if identifier == 23:
                return [username_less_user]
            return []

    users_map, group_names, permissions, groups_by_user, users_by_group = (
        index_view._list_all_users_and_groups(
            SimpleNamespace(getAdminService=_SparseAdminService)
        )
    )

    assert users_map == {}
    assert group_names == {"team"}
    assert permissions == {"team": "Private"}
    assert groups_by_user == {}
    assert users_by_group == {"team": set()}

    services = index_view._build_target_service_status(
        active_targets=[
            {
                "health": "unknown",
                "labels": {},
                "discoveredLabels": {
                    "__meta_docker_container_name": "stack_prometheus_server_1"
                },
            },
            {
                "health": "down",
                "labels": {"job": "/cadvisor"},
                "discoveredLabels": {},
            },
        ],
        expected_services=["Prometheus-Server", "cadvisor"],
        service_healthcheck_config={"Prometheus-Server": True, "cadvisor": False},
        runtime_health_by_service={
            "prometheus-server": {"state": "running", "health": ""},
            "cadvisor": {"state": "running", "health": ""},
        },
    )

    assert services == [
        {
            "service": "Prometheus-Server",
            "health": "up",
            "state": "running",
            "healthcheck": "",
        },
        {
            "service": "cadvisor",
            "health": "down",
            "state": "running",
            "healthcheck": "none",
        },
    ]


def test_admin_helper_fallbacks_cover_wrapped_values_and_compose_health(monkeypatch):
    """Verify admin helper fallbacks cover wrapped values and compose health.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in admin helper fallbacks cover wrapped values and compose health.
    Raises: RuntimeError, TypeError when validation or the called operation fails.
    """

    class _TextPermission:
        """Test double for text permission behavior in this module."""

        @staticmethod
        def isGroupRead():
            """Return whether `_TextPermission` grants group-read access.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("bad read")

        @staticmethod
        def isGroupWrite():
            """Return whether `_TextPermission` grants group-write access.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("bad write")

        @staticmethod
        def isGroupAnnotate():
            """Return whether `_TextPermission` grants group-annotate access.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("bad annotate")

        def __str__(self):
            """Return `_TextPermission` as test-readable text.

            Inputs: none. Output: 'read-only'.
            """
            return "read-only"

    def _fallback_group_details():
        """Return the fallback group details.

        Inputs: none. Output: `SimpleNamespace` result.
        """
        return SimpleNamespace(getPermissions=_TextPermission)

    fallback_group = SimpleNamespace(getDetails=_fallback_group_details)

    class _CallableListingService:
        """Test double for callable listing service behavior in this module."""

        @staticmethod
        def lookupGroups(*_args):
            """Return the lookup Groups for `_CallableListingService`.

            Inputs: `*_args`. Output: `list`.
            """
            return [_Group(12, "users_rw", _Permissions("rwrw--", group_write=True))]

        @staticmethod
        def containedGroups(*_args):
            """Record the contained groups call on `_CallableListingService` for later assertions.

            Inputs: `*_args`. Output: None. Raises: TypeError when validation or
            external operations fail.
            """
            raise TypeError("wrong signature")

    monkeypatch.setattr(
        index_view,
        "_docker_compose_json",
        lambda command: (
            {"services": {"web": {"healthcheck": {}}, "db": {}, "ignored": "bad"}}
            if command[2] == "config"
            else [
                {"Service": "web", "State": "running", "Health": "healthy"},
                {"Service": "db", "State": "exited", "Health": ""},
                "ignored",
            ]
        ),
    )

    assert index_view._unwrap_rtype_value(_Value("wrapped")) == "wrapped"
    assert (
        index_view._safe_full_name(_User(3, "carol", "Carol", "Curator"))
        == "Carol Curator"
    )
    assert (
        index_view._safe_username(SimpleNamespace(getOmeName=lambda: _Value("root")))
        == "root"
    )
    assert (
        index_view._safe_group_name(_Group(10, "users_private", _Permissions("rw----")))
        == "users_private"
    )
    assert (
        index_view._call_admin_listing(_CallableListingService(), "containedGroups")
        == []
    )
    assert index_view._safe_object_id(SimpleNamespace(id=_Value("bad"))) is None
    assert index_view._safe_group_permission_label(fallback_group) == "Read-only"
    assert index_view._load_compose_healthcheck_config() == {"web": True, "db": False}
    assert index_view._load_compose_runtime_health() == {
        "web": {"state": "running", "health": "healthy"},
        "db": {"state": "exited", "health": ""},
    }


def test_proxy_and_admin_post_views_cover_remaining_error_and_success_paths(
    monkeypatch,
):
    """Confirm proxy and admin post views cover remaining error and success paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when proxy and admin post views cover remaining error and success paths stops reporting the expected error.
    """
    factory = RequestFactory()
    conn = object()

    monkeypatch.setattr(index_view, "_require_root_user", lambda *_args: None)
    monkeypatch.setattr(index_view, "current_username", lambda *_args: "root")

    bad_grafana = inspect.unwrap(index_view.grafana_proxy)(
        factory.get("/grafana"), "../escape", conn=conn
    )
    assert bad_grafana.status_code == 400

    monkeypatch.setattr(index_view, "_build_proxy_backend_urls", lambda *_args: [])
    home = inspect.unwrap(index_view.grafana_proxy)(
        factory.get("/grafana/"), "", conn=conn
    )
    assert home.status_code == 302

    monkeypatch.setattr(
        index_view,
        "_build_proxy_backend_urls",
        lambda *_args: ["https://prometheus:9090"],
    )
    bad_prometheus = inspect.unwrap(index_view.prometheus_proxy)(
        factory.get("/prometheus"), "../escape", conn=conn
    )
    assert bad_prometheus.status_code == 400

    monkeypatch.setattr(index_view, "_build_proxy_backend_urls", lambda *_args: [])
    with pytest.raises(RuntimeError, match="No Prometheus backend URLs configured"):
        inspect.unwrap(index_view.prometheus_proxy)(
            factory.get("/prometheus"), "api/v1/query", conn=conn
        )

    storage_method = inspect.unwrap(index_view.storage_quota_import)(
        factory.get("/storage/import"), conn=conn
    )
    assert storage_method.status_code == 405
    missing_file = inspect.unwrap(index_view.storage_quota_import)(
        factory.post("/storage/import", data={}),
        conn=conn,
    )
    assert missing_file.status_code == 400

    invalid_encoding = inspect.unwrap(index_view.storage_quota_import)(
        factory.post(
            "/storage/import",
            data={
                "file": SimpleUploadedFile(
                    "quotas.csv", b"\xff", content_type="text/csv"
                )
            },
        ),
        conn=conn,
    )
    assert invalid_encoding.status_code == 400

    monkeypatch.setattr(
        index_view,
        "import_quotas_csv",
        lambda *_args: (_ for _ in ()).throw(index_view.CsvError("bad csv")),
    )
    invalid_csv = inspect.unwrap(index_view.storage_quota_import)(
        factory.post(
            "/storage/import",
            data={
                "file": SimpleUploadedFile(
                    "quotas.csv", b"group,quota\n", content_type="text/csv"
                )
            },
        ),
        conn=conn,
    )
    assert invalid_csv.status_code == 400

    monkeypatch.setattr(
        index_view, "import_quotas_csv", lambda *_args: {"quotas_gb": {"g": 1}}
    )
    monkeypatch.setattr(index_view, "_list_omero_group_names", lambda *_args: ["g"])
    monkeypatch.setattr(
        index_view, "reconcile_quotas", lambda groups: {"created": groups}
    )
    success = inspect.unwrap(index_view.storage_quota_import)(
        factory.post(
            "/storage/import",
            data={
                "file": SimpleUploadedFile(
                    "quotas.csv", b"group,quota\n", content_type="text/csv"
                )
            },
        ),
        conn=conn,
    )
    assert json.loads(success.content.decode("utf-8")) == {
        "quotas_gb": {"g": 1},
        "reconcile": {"created": ["g"]},
    }

    invalid_json = inspect.unwrap(index_view.server_database_testing_run)(
        factory.post("/diag/run", data=b"{bad", content_type="application/json"),
        conn=conn,
    )
    assert invalid_json.status_code == 400

    missing_scripts = inspect.unwrap(index_view.server_database_testing_run)(
        factory.post(
            "/diag/run",
            data=json.dumps({}).encode("utf-8"),
            content_type="application/json",
        ),
        conn=conn,
    )
    assert missing_scripts.status_code == 400

    empty_script_id = inspect.unwrap(index_view.server_database_testing_run)(
        factory.post(
            "/diag/run",
            data=json.dumps({"scripts": ["ok", " "]}).encode("utf-8"),
            content_type="application/json",
        ),
        conn=conn,
    )
    assert empty_script_id.status_code == 400

    class _RequestId:
        """Test double for request identifier behavior in this module."""

        def __str__(self):
            """Return `_RequestId` as test-readable text.

            Inputs: none. Output: 'req-1'.
            """
            return "req-1"

    monkeypatch.setattr(index_view.uuid, "uuid4", _RequestId)
    monkeypatch.setattr(
        index_view,
        "run_diagnostic_script",
        lambda script_id: {"id": script_id, "ok": True},
    )
    diagnostics = inspect.unwrap(index_view.server_database_testing_run)(
        factory.post(
            "/diag/run",
            data=json.dumps({"scripts": ["disk", "db"]}).encode("utf-8"),
            content_type="application/json",
        ),
        conn=conn,
    )
    assert diagnostics.status_code == 200
    assert json.loads(diagnostics.content.decode("utf-8"))["results"] == [
        {"id": "disk", "ok": True},
        {"id": "db", "ok": True},
    ]
