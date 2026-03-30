from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from django.http import Http404

from omeroweb_admin_tools import apps
from omeroweb_admin_tools.views import help_view


def test_admin_tools_app_ready_invokes_logging_setup(monkeypatch):
    configured = []
    monkeypatch.setattr(
        apps, "configure_omero_gateway_logging", lambda: configured.append(True)
    )

    config = apps.AdminToolsPluginConfig(apps.AdminToolsPluginConfig.name, apps)
    config.ready()

    assert configured == [True]


def test_admin_help_page_serves_expected_file_and_404s_when_missing(
    tmp_path, monkeypatch
):
    docs_root = tmp_path / "docs" / "help"
    docs_root.mkdir(parents=True)
    help_file = docs_root / "omeroweb_admin_tools_help.md"
    help_file.write_text("# Help\n", encoding="utf-8")

    fake_module_path = tmp_path / "pkg" / "views" / "help_view.py"
    fake_module_path.parent.mkdir(parents=True)
    fake_module_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(help_view, "__file__", str(fake_module_path))

    unwrapped = inspect.unwrap(help_view.help_page)
    response = unwrapped(SimpleNamespace())
    assert response["Content-Type"] == "text/markdown"
    response.close()

    help_file.unlink()
    with pytest.raises(Http404):
        unwrapped(SimpleNamespace())
