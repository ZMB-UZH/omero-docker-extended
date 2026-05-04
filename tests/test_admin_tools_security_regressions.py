import json
import os
import stat
import sys
import tempfile
import types
from pathlib import Path
from unittest import TestCase, mock, main as unittest_main


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _BaseResponse:
    """Test double for base response behavior in this module."""

    def __init__(self, content="", status=200, content_type=None):
        """Create `_BaseResponse` with `content`, `status`, and `content_type`.

        Inputs: `content`, `status`, `content_type`. Output: None.
        """
        self.status_code = status
        self.content_type = content_type
        self.headers = {}
        if isinstance(content, bytes):
            self.content = content
        else:
            self.content = str(content).encode("utf-8")

    def __setitem__(self, key, value):
        """The item for the requested key.

        Inputs: `key`, `value`. Output: None.
        """
        self.headers[key] = value

    def __getitem__(self, key):
        """Return the item for the requested key.

        Inputs: `key`. Output: `self.headers[key]`.
        """
        return self.headers[key]


class _JsonResponse(_BaseResponse):
    """Test double for JSON response behavior in this module."""

    def __init__(self, payload=None, status=200, **_kwargs):
        """Create `_JsonResponse` with `payload` and `status`.

        Inputs: `payload`, `status`, `**_kwargs`. Output: None.
        """
        self.payload = payload
        super().__init__(
            json.dumps(payload or {}).encode("utf-8"),
            status=status,
            content_type="application/json",
        )


class _HttpResponse(_BaseResponse):
    """Test double for HTTP response behavior in this module."""


class _HttpResponseRedirect(_HttpResponse):
    """Test double for HTTP response redirect behavior in this module."""

    def __init__(self, location):
        """Create `_HttpResponseRedirect` with `location`.

        Inputs: `location`. Output: None.
        """
        super().__init__("", status=302)
        self["Location"] = location


class _DjangoTemplates:
    """Test double for django templates behavior in this module."""

    def __init__(self, config):
        """Create `_DjangoTemplates` with `config`.

        Inputs: `config`. Output: None.
        """
        self.config = config


class _TemplateResponse(_HttpResponse):
    """Test double for template response behavior in this module."""

    def __init__(self, request, template, context=None, status=200, **_kwargs):
        """Create `_TemplateResponse` with `request`, `template`, `context`, and `status`.

        Inputs: `request`, `template`, `context`, `status`, `**_kwargs`. Output: None.
        """
        super().__init__("", status=status)
        self.request = request
        self.template_name = template
        self.context_data = context or {}


class _SimpleTemplateResponse(_HttpResponse):
    """Test double for simple template response behavior in this module."""

    def __init__(self, template, context=None, status=200, **_kwargs):
        """Create `_SimpleTemplateResponse` with `template`, `context`, and `status`.

        Inputs: `template`, `context`, `status`, `**_kwargs`. Output: None.
        """
        super().__init__("", status=status)
        self.template_name = template
        self.context_data = context or {}

    def render(self):
        """Render the render for `_SimpleTemplateResponse`.

        Inputs: none. Output: `self`.
        """
        return self


def _install_import_stubs():
    """Install the import stubs.

    Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
    """
    if "django.http" not in sys.modules:
        django_module = types.ModuleType("django")
        django_module.__path__ = []
        django_http = types.ModuleType("django.http")
        django_http.JsonResponse = _JsonResponse
        django_http.HttpResponse = _HttpResponse
        django_http.HttpResponseRedirect = _HttpResponseRedirect
        django_shortcuts = types.ModuleType("django.shortcuts")
        django_shortcuts.render = lambda *args, **kwargs: {
            "args": args,
            "kwargs": kwargs,
        }
        django_template = types.ModuleType("django.template")
        django_template.__path__ = []
        django_template_backends = types.ModuleType("django.template.backends")
        django_template_backends.__path__ = []
        django_template_backends_django = types.ModuleType(
            "django.template.backends.django"
        )
        django_template_backends_django.DjangoTemplates = _DjangoTemplates
        django_template_response = types.ModuleType("django.template.response")
        django_template_response.SimpleTemplateResponse = _SimpleTemplateResponse
        django_template_response.TemplateResponse = _TemplateResponse
        django_urls = types.ModuleType("django.urls")
        django_urls.reverse = lambda name, *args, **kwargs: f"/{name}/"
        django_views = types.ModuleType("django.views")
        django_views_decorators = types.ModuleType("django.views.decorators")
        django_views_csrf = types.ModuleType("django.views.decorators.csrf")
        django_views_csrf.csrf_exempt = lambda fn: fn
        django_views_csrf.ensure_csrf_cookie = lambda fn: fn
        sys.modules["django"] = django_module
        sys.modules["django.http"] = django_http
        sys.modules["django.shortcuts"] = django_shortcuts
        sys.modules["django.template"] = django_template
        sys.modules["django.template.backends"] = django_template_backends
        sys.modules["django.template.backends.django"] = django_template_backends_django
        sys.modules["django.template.response"] = django_template_response
        sys.modules["django.urls"] = django_urls
        sys.modules["django.views"] = django_views
        sys.modules["django.views.decorators"] = django_views_decorators
        sys.modules["django.views.decorators.csrf"] = django_views_csrf
    else:
        django_module = sys.modules.setdefault("django", types.ModuleType("django"))
        if not hasattr(django_module, "__path__"):
            django_module.__path__ = []

    if "omeroweb.decorators" not in sys.modules:
        omeroweb_module = types.ModuleType("omeroweb")
        omeroweb_decorators = types.ModuleType("omeroweb.decorators")
        omeroweb_decorators.login_required = lambda *args, **kwargs: lambda view: view
        sys.modules["omeroweb"] = omeroweb_module
        sys.modules["omeroweb.decorators"] = omeroweb_decorators


_install_import_stubs()

from omeroweb_admin_tools.services import storage_quotas
from omeroweb_admin_tools.views import index_view
from omeroweb_admin_tools.views import utils as admin_utils


class AdminToolsSecurityRegressionTests(TestCase):
    """Test cases for admin tools security regression tests."""

    def test_normalize_proxy_request_target_rejects_traversal(self):
        """Confirm normalize proxy request target rejects traversal is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in normalize proxy request target rejects traversal.
        """
        with self.assertRaises(ValueError):
            index_view._normalize_proxy_request_target("../api/admin")

    def test_rewrite_proxied_location_blocks_external_redirects(self):
        """Confirm rewrite proxied location blocks external redirects is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in rewrite proxied location blocks external redirects.
        """
        location = index_view._rewrite_proxied_location(
            "https://evil.example.org/steal",
            "https://grafana:3000",
            "/omeroweb_admin_tools/resource-monitoring/grafana-proxy",
        )

        self.assertEqual(
            "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/",
            location,
        )

    def test_grafana_proxy_home_fallback_response_sanitizes_segments(self):
        """Check that grafana proxy home fallback response sanitizes segments keeps sensitive data out of output.

        Inputs: repository fixtures. Output: fails on regressions in grafana proxy home fallback response sanitizes segments.
        """
        with mock.patch.dict(
            os.environ,
            {
                "ADMIN_TOOLS_GRAFANA_DASHBOARD_UID": "../../bad uid",
                "ADMIN_TOOLS_GRAFANA_DASHBOARD_SLUG": "server dashboard",
            },
            clear=False,
        ):
            response = index_view._grafana_proxy_home_fallback_response(
                "/omeroweb_admin_tools/resource-monitoring/grafana-proxy"
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual(
            "/omeroweb_admin_tools/resource-monitoring/grafana-proxy/d/bad-uid/server-dashboard",
            response["Location"],
        )

    def test_storage_quota_update_hides_payload_details(self):
        """Verify storage quota update hides payload details result shape.

        Inputs: repository fixtures. Output: fails on regressions in storage quota update hides payload details.
        """
        request = types.SimpleNamespace(
            method="POST",
            body=b'{"updates":"bad"}',
            POST={},
            META={"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": "17"},
        )

        with (
            mock.patch.object(index_view, "_require_root_user", return_value=None),
            mock.patch.object(admin_utils, "current_username", return_value="root"),
        ):
            response = index_view.storage_quota_update(request, conn=None)

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            {"error": "Invalid quota update payload."},
            json.loads(response.content.decode("utf-8")),
        )

    def test_write_state_temp_file_is_not_world_writable(self):
        """Verify write state temp file is not world writable.

        Inputs: repository fixtures. Output: fails on regressions in write state temp file is not world writable.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "quotas.json"
            seen_modes = []
            real_replace = os.replace

            def _capturing_replace(src, dst):
                """Record the capturing replace call on the test double for later assertions.

                Inputs: `src`, `dst`. Output: None.
                """
                seen_modes.append(stat.S_IMODE(Path(src).stat().st_mode))
                real_replace(src, dst)

            with mock.patch.object(
                storage_quotas.os, "replace", side_effect=_capturing_replace
            ):
                storage_quotas._write_state(state_path, {"quotas_gb": {}, "logs": []})

        self.assertEqual([0o600], seen_modes)


if __name__ == "__main__":
    unittest_main()
