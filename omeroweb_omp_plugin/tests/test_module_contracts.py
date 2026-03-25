from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from omeroweb_omp_plugin import apps


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_omp_app_ready_configures_gateway_logging(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(apps, "configure_omero_gateway_logging", lambda: calls.append("configured"))

    apps.OMPPluginConfig("omeroweb_omp_plugin", apps).ready()

    assert calls == ["configured"]


def test_omp_urls_publish_expected_named_routes_with_stubbed_views(monkeypatch) -> None:
    package_module = types.ModuleType("omeroweb_omp_plugin")
    package_module.__path__ = [str(REPO_ROOT / "omeroweb_omp_plugin")]
    views_module = types.ModuleType("omeroweb_omp_plugin.views")
    views_module.__path__ = [str(REPO_ROOT / "omeroweb_omp_plugin" / "views")]
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin", package_module)
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.views", views_module)

    index_view = types.ModuleType("omeroweb_omp_plugin.views.index_view")
    index_view.index = lambda *args, **kwargs: "index"
    index_view.list_projects = lambda *args, **kwargs: "projects"
    index_view.root_status = lambda *args, **kwargs: "root-status"
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.views.index_view", index_view)

    job_view = types.ModuleType("omeroweb_omp_plugin.views.job_view")
    for name in (
        "start_job",
        "job_progress",
        "start_acq_job",
        "start_delete_all_job",
        "start_delete_plugin_job",
    ):
        setattr(job_view, name, lambda *args, _name=name, **kwargs: _name)
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.views.job_view", job_view)

    delete_all_view = types.ModuleType("omeroweb_omp_plugin.views.delete_all_view")
    delete_all_view.delete_all_keyvaluepairs = lambda *args, **kwargs: "delete-all"
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.views.delete_all_view", delete_all_view)

    delete_plugin_view = types.ModuleType("omeroweb_omp_plugin.views.delete_plugin_view")
    delete_plugin_view.delete_plugin_keyvaluepairs = lambda *args, **kwargs: "delete-plugin"
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_omp_plugin.views.delete_plugin_view",
        delete_plugin_view,
    )

    variable_set_view = types.ModuleType("omeroweb_omp_plugin.views.variable_set_view")
    for name in ("list_sets", "save_set", "load_set", "delete_set"):
        setattr(variable_set_view, name, lambda *args, _name=name, **kwargs: _name)
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_omp_plugin.views.variable_set_view",
        variable_set_view,
    )

    help_view = types.ModuleType("omeroweb_omp_plugin.views.help_view")
    help_view.help_page = lambda *args, **kwargs: "help"
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.views.help_view", help_view)

    ai_credentials_view = types.ModuleType("omeroweb_omp_plugin.views.ai_credentials_view")
    for name in ("list_credentials", "save_credentials", "test_credentials", "list_models"):
        setattr(ai_credentials_view, name, lambda *args, _name=name, **kwargs: _name)
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_omp_plugin.views.ai_credentials_view",
        ai_credentials_view,
    )

    user_data_view = types.ModuleType("omeroweb_omp_plugin.views.user_data_view")
    for name in ("delete_api_keys", "delete_variable_sets", "delete_all_data"):
        setattr(user_data_view, name, lambda *args, _name=name, **kwargs: _name)
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.views.user_data_view", user_data_view)

    user_settings_view = types.ModuleType("omeroweb_omp_plugin.views.user_settings_view")
    user_settings_view.save_settings = lambda *args, **kwargs: "save-settings"
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_omp_plugin.views.user_settings_view",
        user_settings_view,
    )

    spec = importlib.util.spec_from_file_location(
        "omeroweb_omp_plugin.urls",
        REPO_ROOT / "omeroweb_omp_plugin" / "urls.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "omeroweb_omp_plugin.urls", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    route_map = {pattern.name: str(pattern.pattern) for pattern in module.urlpatterns}
    assert route_map["omeroweb_omp_plugin_index"] == ""
    assert route_map["omeroweb_omp_plugin_projects"] == "projects/"
    assert route_map["omeroweb_omp_plugin_root_status"] == "root-status/"
    assert route_map["omeroweb_omp_plugin_start_job"] == "start_job/"
    assert route_map["omeroweb_omp_plugin_job_progress"] == "progress/<str:job_id>/"
    assert route_map["omeroweb_omp_plugin_start_acq_job"] == "start_acq_job/"
    assert route_map["omeroweb_omp_plugin_start_delete_all_job"] == "start_delete_all_job/"
    assert route_map["omeroweb_omp_plugin_start_delete_plugin_job"] == "start_delete_plugin_job/"
    assert route_map["omeroweb_omp_plugin_delete_all"] == "delete_all/"
    assert route_map["omeroweb_omp_plugin_delete_plugin"] == "delete_plugin/"
    assert route_map["omeroweb_omp_plugin_list_sets"] == "varsets/"
    assert route_map["omeroweb_omp_plugin_save_set"] == "varsets/save/"
    assert route_map["omeroweb_omp_plugin_load_set"] == "varsets/load/"
    assert route_map["omeroweb_omp_plugin_delete_set"] == "varsets/delete/"
    assert route_map["omeroweb_omp_plugin_list_ai_credentials"] == "ai-credentials/"
    assert route_map["omeroweb_omp_plugin_test_ai_credentials"] == "ai-credentials/test/"
    assert route_map["omeroweb_omp_plugin_save_ai_credentials"] == "ai-credentials/save/"
    assert route_map["omeroweb_omp_plugin_list_models"] == "ai-credentials/models/"
    assert route_map["omeroweb_omp_plugin_save_user_settings"] == "user-settings/save/"
    assert route_map["omeroweb_omp_plugin_delete_api_keys"] == "user-data/delete-api-keys/"
    assert route_map["omeroweb_omp_plugin_delete_variable_sets"] == "user-data/delete-variable-sets/"
    assert route_map["omeroweb_omp_plugin_delete_user_data"] == "user-data/delete-all/"
    assert route_map["omeroweb_omp_plugin_help"] == "help/"
