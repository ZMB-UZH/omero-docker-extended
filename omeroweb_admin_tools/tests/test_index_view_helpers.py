from __future__ import annotations

from http.client import HTTPMessage
from types import SimpleNamespace

from django.test import RequestFactory

from omeroweb_admin_tools.views import index_view


class _Value:
    def __init__(self, value):
        self.val = value

    def getValue(self):
        return self.val


class _User:
    def __init__(self, user_id, username, first_name="", last_name=""):
        self.id = _Value(user_id)
        self.omeName = _Value(username)
        self.firstName = _Value(first_name)
        self.lastName = _Value(last_name)

    def getId(self):
        return self.id

    def getOmeName(self):
        return self.omeName

    def getFirstName(self):
        return self.firstName

    def getLastName(self):
        return self.lastName


class _Group:
    def __init__(self, group_id, name, permissions):
        self.id = _Value(group_id)
        self.name = _Value(name)
        self.permissions = permissions

    def getId(self):
        return self.id

    def getName(self):
        return self.name

    def getDetails(self):
        return SimpleNamespace(getPermissions=lambda: self.permissions)


class _Permissions:
    def __init__(
        self,
        label,
        *,
        group_read=True,
        group_write=False,
        group_annotate=False,
    ):
        self._label = label
        self._group_read = group_read
        self._group_write = group_write
        self._group_annotate = group_annotate

    def __str__(self):
        return self._label

    def isGroupRead(self):
        return self._group_read

    def isGroupWrite(self):
        return self._group_write

    def isGroupAnnotate(self):
        return self._group_annotate


class _AdminService:
    def __init__(self, users, groups, groups_by_user, users_by_group):
        self._users = users
        self._groups = groups
        self._groups_by_user = groups_by_user
        self._users_by_group = users_by_group

    def lookupExperimenters(self):
        return list(self._users)

    def lookupGroups(self):
        return list(self._groups)

    def containedGroups(self, identifier=None, *_args):
        if identifier is None:
            return list(self._groups)
        return list(self._groups_by_user.get(int(identifier), []))

    def containedExperimenters(self, identifier=None, *_args):
        if identifier is None:
            return list(self._users)
        return list(self._users_by_group.get(int(identifier), []))


def test_proxy_path_and_redirect_safety_helpers():
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
    assert index_view._normalize_proxy_request_target(
        "https://grafana.example.org/grafana/api/live?watch=1"
    ) == ("grafana/api/live", "watch=1")


def test_normalize_proxy_request_target_rejects_path_traversal():
    try:
        index_view._normalize_proxy_request_target("../../escape")
    except ValueError as exc:
        assert "Invalid proxy target" in str(exc)
    else:
        raise AssertionError("Expected ValueError for traversal")


def test_build_proxied_response_rewrites_html_locations_and_cookies():
    headers = HTTPMessage()
    headers.add_header("Content-Type", "text/html; charset=utf-8")
    headers.add_header("Location", "http://grafana:3000/login")
    headers.add_header(
        "Set-Cookie",
        "grafana_session=session; Path=/; HttpOnly; Secure; SameSite=Lax",
    )
    html = (
        '<a href="/dashboards">dash</a>'
        '<img src="/public/logo.svg">'
        '<form action="/login"></form>'
        '<script>{"appSubUrl":"","appUrl":"/"}</script>'
        "http://grafana:3000"
    ).encode("utf-8")

    response = index_view._build_proxied_response(
        html,
        status_code=200,
        headers=headers,
        base_url="http://grafana:3000",
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
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_UID", "infra")
    monkeypatch.setenv("ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG", "server-overview")

    assert index_view._cookie_path_for_proxy("/", "/admin/grafana") == "/admin/grafana/"
    assert index_view._origin_from_url("https://grafana.example.org:8443/app") == (
        "https://grafana.example.org:8443"
    )
    assert (
        index_view._rewrite_proxied_location(
            "http://grafana:3000/login",
            "http://grafana:3000",
            "/admin/grafana",
        )
        == "/admin/grafana/login"
    )
    assert index_view._build_proxy_backend_urls(
        "http://grafana:3000",
        "https://grafana.example.org",
    ) == ["http://grafana:3000", "https://grafana.example.org"]

    home = index_view._grafana_proxy_home_fallback_response("/admin/grafana")
    unavailable = index_view._grafana_unavailable_response(
        proxy_prefix="/admin/grafana",
        attempted_backends=["http://grafana:3000", "https://grafana.example.org"],
        status_code=502,
    )

    assert home.status_code == 302
    assert home["Location"] == "/admin/grafana/d/infra/server-overview"
    assert unavailable.status_code == 503
    assert "grafana:3000" in unavailable.content.decode("utf-8")
    assert unavailable["Retry-After"] == "30"


def test_request_and_public_url_helpers_cover_reverse_proxy_cases():
    factory = RequestFactory()
    proxied = factory.get(
        "/",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_HOST="omero.example.org",
        HTTP_X_FORWARDED_FOR="198.51.100.10",
        HTTP_HOST="omero.example.org:4080",
    )
    direct = factory.get("/", HTTP_HOST="localhost:4080")

    assert index_view._is_internal_hostname("grafana") is True
    assert index_view._is_internal_hostname("example.org") is False
    assert index_view._is_behind_reverse_proxy(proxied) is True
    assert index_view._safe_request_host(direct) == "localhost"
    assert (
        index_view._build_public_service_url(
            "http://grafana:3000/grafana",
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
            "http://grafana:3000",
            "http",
            "2001:db8::1",
            3000,
        )
        == "http://[2001:db8::1]:3000"
    )


def test_admin_listing_helpers_collect_users_groups_and_permissions():
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
