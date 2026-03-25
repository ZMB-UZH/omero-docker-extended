from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from django.test import RequestFactory

from omeroweb_import import apps
from omeroweb_import import urls
from omeroweb_import.services import compat
from omeroweb_import.utils import omero_helpers
from omeroweb_import.views import help_view, utils as view_utils
from omero_plugin_common import omero_helpers as common_omero_helpers


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_app_ready_configures_gateway_logging(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(apps, "configure_omero_gateway_logging", lambda: calls.append("configured"))

    apps.ImportPluginConfig("omeroweb_import", apps).ready()

    assert calls == ["configured"]


def test_import_urls_publish_expected_named_routes() -> None:
    route_map = {pattern.name: str(pattern.pattern) for pattern in urls.urlpatterns}

    assert route_map["omeroweb_import_index"] == ""
    assert route_map["omeroweb_import_start"] == "start/"
    assert route_map["omeroweb_import_files"] == "upload/<str:job_id>/"
    assert route_map["omeroweb_import_import_step"] == "import/<str:job_id>/"
    assert route_map["omeroweb_import_confirm"] == "confirm/<str:job_id>/"
    assert route_map["omeroweb_import_prune"] == "prune/<str:job_id>/"
    assert route_map["omeroweb_import_status"] == "status/<str:job_id>/"
    assert route_map["omeroweb_import_projects"] == "projects/"
    assert route_map["omeroweb_import_root_status"] == "root-status/"
    assert route_map["omeroweb_import_save_user_settings"] == "user-settings/save/"
    assert route_map["omeroweb_import_save_special_method_settings"] == "special-method-settings/save/"
    assert route_map["omeroweb_import_load_special_method_settings"] == "special-method-settings/load/"
    assert route_map["omeroweb_import_help"] == "help/"


def test_import_compat_wrappers_inject_jobs_root_and_keep_reexports(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(compat, "get_jobs_root", lambda: "/tmp/import-jobs")
    monkeypatch.setattr(
        compat,
        "_get_job_path_internal",
        lambda job_id, jobs_root: captured.setdefault("path", (job_id, jobs_root)),
    )
    monkeypatch.setattr(
        compat,
        "_load_job_internal",
        lambda job_id, jobs_root: captured.setdefault("load", (job_id, jobs_root)),
    )
    monkeypatch.setattr(
        compat,
        "_save_job_internal",
        lambda job_dict, jobs_root, retries, timeout: captured.setdefault(
            "save",
            (job_dict, jobs_root, retries, timeout),
        ),
    )
    monkeypatch.setattr(
        compat,
        "_robust_update_job_internal",
        lambda job_id, update_fn, jobs_root, retries, timeout: captured.setdefault(
            "update",
            (job_id, update_fn("value"), jobs_root, retries, timeout),
        ),
    )

    assert compat._job_path("job-1") == ("job-1", "/tmp/import-jobs")
    assert compat._load_job("job-2") == ("job-2", "/tmp/import-jobs")
    assert compat._save_job({"job_id": "job-3"}, retries=5, timeout=2.5) == (
        {"job_id": "job-3"},
        "/tmp/import-jobs",
        5,
        2.5,
    )
    assert compat._robust_update_job("job-4", lambda value: f"updated-{value}", retries=6, timeout=3.5) == (
        "job-4",
        "updated-value",
        "/tmp/import-jobs",
        6,
        3.5,
    )

    assert "_iter_accessible_projects" in compat.__all__
    assert "_build_sem_edx_associations_from_entries" in compat.__all__
    assert compat._iter_accessible_projects is not None
    assert compat._normalize_sem_edx_associations is not None


def test_import_omero_helpers_reexport_common_symbols() -> None:
    assert omero_helpers.get_text is common_omero_helpers.get_text
    assert omero_helpers.get_id is common_omero_helpers.get_id
    assert omero_helpers.get_owner_id is common_omero_helpers.get_owner_id
    assert omero_helpers.is_owned_by_user is common_omero_helpers.is_owned_by_user
    assert omero_helpers._current_user_id is common_omero_helpers._current_user_id
    assert omero_helpers._get_owner_username is common_omero_helpers._get_owner_username
    assert omero_helpers._has_read_write_permissions is common_omero_helpers._has_read_write_permissions
    assert omero_helpers.__all__ == [
        "get_text",
        "get_id",
        "get_owner_id",
        "is_owned_by_user",
        "_current_user_id",
        "_get_owner_username",
        "_has_read_write_permissions",
    ]


def test_help_page_serves_markdown_and_raises_404_when_missing(monkeypatch, tmp_path: Path) -> None:
    request = RequestFactory().get("/omeroweb_import/help/")
    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")

    synthetic_module_path = tmp_path / "pkg" / "views" / "help_view.py"
    synthetic_module_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(help_view, "__file__", str(synthetic_module_path))

    help_doc = tmp_path / "docs" / "help" / "omeroweb_import_help.md"
    help_doc.parent.mkdir(parents=True, exist_ok=True)
    help_doc.write_text("# Import Help\n", encoding="utf-8")

    response = help_view.help_page(request, conn=None)
    assert response.status_code == 200
    assert b"Import Help" in b"".join(response.streaming_content)
    response.close()

    help_doc.unlink()
    with pytest.raises(help_view.Http404):
        help_view.help_page(request, conn=None)


def test_import_urls_module_can_be_loaded_in_isolation_with_stubbed_views(monkeypatch) -> None:
    package_module = types.ModuleType("omeroweb_import")
    package_module.__path__ = [str(REPO_ROOT / "omeroweb_import")]
    views_module = types.ModuleType("omeroweb_import.views")
    views_module.__path__ = [str(REPO_ROOT / "omeroweb_import" / "views")]
    monkeypatch.setitem(sys.modules, "omeroweb_import", package_module)
    monkeypatch.setitem(sys.modules, "omeroweb_import.views", views_module)

    index_view = types.ModuleType("omeroweb_import.views.index_view")
    for name in (
        "confirm_import",
        "import_step",
        "index",
        "job_status",
        "list_projects",
        "prune_upload",
        "root_status",
        "start_upload",
        "upload_files",
    ):
        setattr(index_view, name, lambda *args, _name=name, **kwargs: _name)
    monkeypatch.setitem(sys.modules, "omeroweb_import.views.index_view", index_view)

    special_method_settings_view = types.ModuleType("omeroweb_import.views.special_method_settings_view")
    special_method_settings_view.load_settings = lambda *args, **kwargs: "load"
    special_method_settings_view.save_settings = lambda *args, **kwargs: "save"
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.views.special_method_settings_view",
        special_method_settings_view,
    )

    user_settings_view = types.ModuleType("omeroweb_import.views.user_settings_view")
    user_settings_view.save_settings = lambda *args, **kwargs: "save-user"
    monkeypatch.setitem(sys.modules, "omeroweb_import.views.user_settings_view", user_settings_view)

    help_page_view = types.ModuleType("omeroweb_import.views.help_view")
    help_page_view.help_page = lambda *args, **kwargs: "help"
    monkeypatch.setitem(sys.modules, "omeroweb_import.views.help_view", help_page_view)

    spec = importlib.util.spec_from_file_location(
        "omeroweb_import.urls",
        REPO_ROOT / "omeroweb_import" / "urls.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "omeroweb_import.urls", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    route_map = {pattern.name: str(pattern.pattern) for pattern in module.urlpatterns}
    assert route_map["omeroweb_import_help"] == "help/"
