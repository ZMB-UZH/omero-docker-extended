from __future__ import annotations

import ast
import inspect
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.http import Http404

from omeroweb_tools import apps, urls
from omeroweb_tools.views import help_view


def test_tools_app_ready_invokes_logging_setup(monkeypatch):
    configured = []
    monkeypatch.setattr(
        apps, "configure_omero_gateway_logging", lambda: configured.append(True)
    )

    config = apps.ToolsPluginConfig(apps.ToolsPluginConfig.name, apps)
    config.ready()

    assert configured == [True]


def test_tools_urls_expose_expected_routes():
    route_map = {pattern.name: str(pattern.pattern) for pattern in urls.urlpatterns}

    assert route_map["omeroweb_tools_index"] == ""
    assert route_map["omeroweb_tools_root_status"] == "root-status/"
    assert route_map["omeroweb_tools_enhanced_search"] == "enhanced-search/"
    assert route_map["omeroweb_tools_enhanced_search_sync"] == "enhanced-search/sync/"
    assert (
        route_map["omeroweb_tools_enhanced_search_settings"]
        == "enhanced-search/settings/"
    )
    assert route_map["omeroweb_tools_enhanced_search_apply_query"] == (
        "enhanced-search/saved-queries/<int:query_id>/"
    )
    assert route_map["omeroweb_tools_help"] == "help/"


def test_tools_help_page_serves_expected_file_and_404s_when_missing(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        docs_root = tmp_path / "docs" / "help"
        docs_root.mkdir(parents=True)
        help_file = docs_root / "omeroweb_tools_help.md"
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


def test_enhanced_search_template_removes_filter_heading_and_shows_loading_ui():
    template_path = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "omeroweb_tools"
        / "enhanced_search.html"
    )
    template_text = template_path.read_text(encoding="utf-8")

    assert "Search filters" not in template_text
    assert "Free text" not in template_text
    assert "Search box" in template_text
    assert "Indexed scope" in template_text
    assert "Acquired from" in template_text
    assert "Acquired to" in template_text
    assert 'placeholder="dd--mm--yyyy"' in template_text
    assert "tools-search-field--actions" in template_text
    assert "tools-search-inline-action--primary" in template_text
    assert "tools-search-page-loader" in template_text
    assert "Loading search results" in template_text
    assert "Please wait while the search results are being queried." in template_text
    assert "<th>Preview</th>" in template_text
    assert "<th>Channel(s)</th>" in template_text
    assert "Indexed by:" in template_text
    assert "Owner:" in template_text
    assert "No matching images were found." in template_text
    assert "Run a search to see indexed results." in template_text
    assert "X:" in template_text
    assert "Y:" in template_text
    assert "Optics / Detector" not in template_text


def test_tools_landing_template_has_single_enhanced_search_entry_without_descriptive_copy():
    template_path = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "omeroweb_tools"
        / "index.html"
    )
    template_text = template_path.read_text(encoding="utf-8")

    assert template_text.count("Enhanced search") == 1
    assert "tools-page-lead" not in template_text


def test_tools_task_wiring_avoids_service_task_import_cycle():
    task_path = Path(__file__).resolve().parents[1] / "tasks.py"
    task_names_path = Path(__file__).resolve().parents[1] / "task_names.py"
    service_path = (
        Path(__file__).resolve().parents[1] / "services" / "enhanced_search_service.py"
    )
    module = ast.parse(task_path.read_text(encoding="utf-8"))
    task_names_module = ast.parse(task_names_path.read_text(encoding="utf-8"))
    service_module = ast.parse(service_path.read_text(encoding="utf-8"))

    top_level_service_import = [
        node
        for node in module.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "services.enhanced_search_service"
    ]
    imported_names = {
        alias.name for node in top_level_service_import for alias in node.names
    }
    assert imported_names == {"run_scope_sync_task"}

    top_level_task_name_import = [
        node
        for node in module.body
        if isinstance(node, ast.ImportFrom) and node.module == "task_names"
    ]
    task_name_imported_names = {
        alias.name for node in top_level_task_name_import for alias in node.names
    }
    assert task_name_imported_names == {"ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME"}

    task_func = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_enhanced_search_scope_sync"
    )
    nested_service_import = [
        node
        for node in ast.walk(task_func)
        if isinstance(node, ast.ImportFrom)
        and node.module == "services.enhanced_search_service"
    ]
    assert nested_service_import == []

    service_task_imports = [
        node
        for node in service_module.body
        if isinstance(node, ast.ImportFrom) and node.module == "tasks"
    ]
    assert service_task_imports == []

    service_celery_app_imports = [
        node
        for node in service_module.body
        if isinstance(node, ast.ImportFrom) and node.module == "celery_app"
    ]
    assert service_celery_app_imports == []

    task_name_assignments = [
        node
        for node in task_names_module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "ENHANCED_SEARCH_SCOPE_SYNC_TASK_NAME"
            for target in node.targets
        )
    ]
    assert len(task_name_assignments) == 1
