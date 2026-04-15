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
    assert "Start date" in template_text
    assert "End date" in template_text
    assert 'placeholder="dd--mm--yyyy"' in template_text
    assert 'id="settings_menu_btn"' in template_text
    assert 'id="settings_menu"' in template_text
    assert 'id="user_settings_btn"' in template_text
    assert "User settings" in template_text
    assert "Admin settings" not in template_text
    assert "&larr; Back to tools" not in template_text
    assert "tools-search-field--actions" in template_text
    assert "tools-search-inline-action--primary" in template_text
    assert "Date format: dd--mm--yyyy" not in template_text
    assert 'class="tools-search-date-picker-button"' in template_text
    assert 'aria-label="Pick start date"' in template_text
    assert 'aria-label="Pick end date"' in template_text
    assert (
        template_text.count(
            '<h2 class="tools-search-heading">Acquisition metadata indexing</h2>'
        )
        == 1
    )
    assert (
        '<h2 class="tools-search-heading">Acquisition metadata index</h2>'
        not in template_text
    )
    assert ">Index status<" not in template_text
    assert 'id="acquisition-index-enabled-pill"' in template_text
    assert 'json_script:"acquisition-index-messages"' in template_text
    assert "acquisitionIndexMessages" in template_text
    assert "Save setting" not in template_text
    assert "Enable acquisition metadata indexing" not in template_text
    assert "Save current query" not in template_text
    assert 'id="save-query-btn"' in template_text
    assert 'class="tools-search-query-name-input"' in template_text
    assert 'maxlength="{{ saved_query_name_max_length }}"' in template_text
    assert "Updated {{ item.updated_at }}" not in template_text
    assert '<small>{{ item.updated_at|date:"j M Y, g:i a" }}</small>' in template_text
    assert "Saved search queries" in template_text
    assert "Loading saved search…" in template_text
    assert "current-query-payload" not in template_text
    assert "const buildCurrentQueryPayload = () => {" in template_text
    assert "const normalizeSavedQueryName = (value) =>" in template_text
    assert "const syncPrimaryLayoutMinWidth = () => {" in template_text
    assert "const updateSaveQueryButtonState = () => {" in template_text
    assert "function showSettingsMenu(show) {" in template_text
    assert "settingsMenuBtn.addEventListener('click'" in template_text
    assert "if (event.key === 'Escape')" in template_text
    assert (
        "savedQueryNameInput.addEventListener('input', updateSaveQueryButtonState);"
        in template_text
    )
    assert (
        "window.addEventListener('resize', syncPrimaryLayoutMinWidth);" in template_text
    )
    assert "const queryPayload = buildCurrentQueryPayload();" in template_text
    assert "window.alert('Enter a name for the saved query.');" not in template_text
    assert "Acquisition metadata indexing setting saved." not in template_text
    assert (
        "showLiveStatus('Saving acquisition metadata indexing setting…');"
        not in template_text
    )
    assert "open.textContent = 'Load';" in template_text
    assert "const previewLoadQueue = [];" in template_text
    assert "const maxConcurrentPreviewLoads = 4;" in template_text
    assert "jquery-ui-1.13.2/js/jquery-ui.js" in template_text
    assert "tools-search-date-control" in template_text
    assert "changeMonth: true" in template_text
    assert "changeYear: true" in template_text
    assert "showAnim: ''" in template_text
    assert "const earliestSelectableDate = new Date(2010, 0, 1);" in template_text
    assert "isBeforeEarliestSelectableDate" in template_text
    assert "yearRange: '2010:c'" in template_text
    assert "minDate: earliestSelectableDate" in template_text
    assert "maxDate: todayDate" in template_text
    assert "const todayDate = (() => {" in template_text
    assert "isFutureCalendarDate" in template_text
    assert "selectedDateByInput = new WeakMap()" in template_text
    assert "pendingDateInputSyncTimers = new WeakMap()" in template_text
    assert "datepickerProxyByInput = new WeakMap()" in template_text
    assert "dateInputByProxy = new WeakMap()" in template_text
    assert "setDateControlActive = (input, isActive) =>" in template_text
    assert (
        "indexedScopeSelect?.addEventListener('pointerdown', activateIndexedScope);"
        in template_text
    )
    assert "else if (String(dateText || '').trim())" not in template_text
    assert "installDatepickerPointerGuard" in template_text
    assert "activeDatepickerInput" in template_text
    assert "ui-datepicker-current" in template_text
    assert "tools-search-date-picker-button" in template_text
    assert "tools-search-date-picker-proxy" in template_text
    assert 'class="tools-search-status-message"' in template_text
    assert "updateSearchSubmitState" in template_text
    assert (
        "searchSubmitButton.disabled = blockedForRoot || hasInvalidDate || (!hasSearchText && !hasCompleteDate);"
        in template_text
    )
    assert "clearSearchValidationStatus" in template_text
    assert (
        "small.textContent = formatStatusTimestamp(item.updated_at);" in template_text
    )
    assert 'class="tools-search-saved-meta"' in template_text
    assert "<th>Scope</th>" not in template_text
    assert "tools-search-page-loader" in template_text
    assert "Loading search results" in template_text
    assert "Please wait while the search results are being queried." in template_text
    assert (
        '<p class="tools-page-note tools-page-note--section-summary">Showing {{ search_payload.results|length }} result(s){% if search_payload.total_count %} from {{ search_payload.total_count }} matching result(s){% endif %}.</p>'
        in template_text
    )
    assert "<th>Preview</th>" in template_text
    assert "<th>Channel(s)</th>" in template_text
    assert 'target="omero-web-image-view"' in template_text
    assert "Indexed by:" in template_text
    assert "Owner:" in template_text
    assert (
        "Owner: {{ row.owner_name|default:row.owner_id }} &middot; Indexed by:"
        in template_text
    )
    assert "No matching images were found." in template_text
    assert "Run a search to see indexed results." in template_text
    assert "X:" in template_text
    assert "Y:" in template_text
    assert "Optics / Detector" not in template_text


def test_enhanced_search_styles_use_compact_saved_query_grid_and_actions():
    styles_path = (
        Path(__file__).resolve().parents[1] / "static" / "omeroweb_tools" / "styles.css"
    )
    styles_text = styles_path.read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in styles_text
    assert ".tools-search-card .tools-search-saved-action--load {" in styles_text
    assert ".tools-search-card .tools-search-saved-action--delete {" in styles_text
    assert "padding: 6px 10px;" in styles_text
    assert "font-size: 13px;" in styles_text
    assert "gap: 1rem;" in styles_text
    assert "min-width: var(--tools-search-primary-min-width, 0);" in styles_text
    assert "padding-right: 0;" in styles_text
    assert "padding: 0.68rem 0.8rem;" in styles_text
    assert "padding: 0.48rem 0.52rem;" in styles_text
    assert "padding-top: 0.36rem;" in styles_text
    assert "padding: 0.18rem 0;" in styles_text
    assert "color: #000000;" in styles_text
    assert "grid-template-columns: minmax(0, 1fr) auto;" in styles_text
    assert "width: min(100%, 56rem);" in styles_text
    assert ".tools-search-saved-meta {" in styles_text
    assert ".tools-search-status-table {" in styles_text
    assert ".tools-search-date-picker-proxy {" in styles_text
    assert "gap: 0.25rem;" in styles_text
    assert "width: 100%;" in styles_text
    assert "height: 2.5rem;" in styles_text
    assert ".tools-search-field--scope.is-select-active select {" in styles_text
    assert (
        ".tools-search-date-control.is-picker-open .tools-search-date-input:not(.tools-search-date-input--invalid),"
        in styles_text
    )
    assert ".tools-search-query-name-input {" in styles_text
    assert ".tools-search-status-message {" in styles_text
    assert "font-size: 0.95rem;" in styles_text
    assert ".tools-search-settings-panel .tools-page-note {" in styles_text
    assert ".tools-search-empty {" in styles_text
    assert "white-space: normal;" in styles_text
    assert "overflow-wrap: anywhere;" in styles_text
    assert "#ui-datepicker-div.ui-widget-content {" in styles_text
    assert ".tools-search-card > .tools-search-heading--compact + * {" in styles_text
    assert ".tools-search-index-heading + .tools-search-settings-panel {" in styles_text
    assert "@media (max-width: 1200px) {" in styles_text
    assert "@media (max-width: 900px) {" in styles_text
    mobile_styles = styles_text.split("@media (max-width: 900px) {", 1)[1]
    assert ".tools-search-grid--primary,\n    .tools-search-grid {" not in mobile_styles
    assert (
        "    .tools-search-grid {\n        grid-template-columns: 1fr;"
        not in mobile_styles
    )


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
