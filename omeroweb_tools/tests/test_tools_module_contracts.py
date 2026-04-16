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
    assert "tools-search-field--date tools-search-field--start-date" in template_text
    assert "tools-search-field--date tools-search-field--end-date" in template_text
    assert 'placeholder="dd-mm-yyyy"' in template_text
    assert 'id="settings_menu_btn"' in template_text
    assert 'id="settings_menu"' in template_text
    assert 'id="user_settings_btn"' in template_text
    assert "User settings" in template_text
    assert "Admin settings" not in template_text
    assert 'autocomplete="off"' in template_text
    assert 'spellcheck="false"' in template_text
    assert "&larr; Back to tools" not in template_text
    assert "tools-search-field--actions" in template_text
    assert "tools-search-inline-action--primary" in template_text
    assert "Date format: dd-mm-yyyy" not in template_text
    assert 'class="tools-search-date-picker-button"' in template_text
    assert 'aria-label="Pick start date"' in template_text
    assert 'aria-label="Pick end date"' in template_text
    assert 'value="{{ query.acquisition_date_from_display }}"' in template_text
    assert 'value="{{ query.acquisition_date_to_display }}"' in template_text
    assert "query.acquisition_date_from|date" not in template_text
    assert "query.acquisition_date_to|date" not in template_text
    assert template_text.count("<span>Universal metadata index</span>") == 1
    assert 'data-collapsible-section="metadata-index"' in template_text
    assert 'data-collapsible-toggle="metadata-index"' in template_text
    assert 'data-collapsible-section="saved-queries"' in template_text
    assert 'data-collapsible-toggle="saved-queries"' in template_text
    assert "tools-search-card--precollapsed" in template_text
    assert (
        'aria-expanded="{% if metadata_index_collapsed %}false{% else %}true{% endif %}"'
        in template_text
    )
    assert (
        'aria-hidden="{% if metadata_index_collapsed %}true{% else %}false{% endif %}"'
        in template_text
    )
    assert 'class="tools-search-collapsible-body"' in template_text
    assert 'json_script:"tools-search-user-settings"' in template_text
    assert 'json_script:"tools-search-indexed-scope-storage-key"' in template_text
    assert "omeroweb_tools/enhanced_search_indexed_scope.js" in template_text
    assert (
        "const supportedCollapsibleSections = ['metadata-index', 'saved-queries'];"
        in template_text
    )
    assert "const persistCollapsedSections = async () => {" in template_text
    assert "const releasePrecollapsedCard = (card) => {" in template_text
    assert "const releasePrecollapsedCards = () => {" in template_text
    assert "const initializeCollapsibleSections = () => {" in template_text
    assert "window.setTimeout(releasePrecollapsedCards, 500);" in template_text
    assert (
        "releasePrecollapsedCard(button.closest('.tools-search-card--collapsible'));"
        in template_text
    )
    assert "initializeCollapsibleSections();" in template_text
    assert "const syncIndexSettingToggleAlignment = () => {" in template_text
    assert "document.querySelector('#sync-state-body td:nth-child(1)')" in template_text
    assert (
        "document.querySelector('.tools-search-status-table th:nth-child(1)')"
        in template_text
    )
    assert (
        "document.querySelector('#sync-state-body td:nth-child(2)')"
        not in template_text
    )
    assert "targetCell.getBoundingClientRect().left" in template_text
    assert "panel.style.setProperty(" in template_text
    assert "syncIndexSettingToggleAlignment();" in template_text
    assert (
        "window.addEventListener('resize', syncIndexSettingToggleAlignment);"
        in template_text
    )
    assert "<span>Universal metadata indexing</span>" in template_text
    assert (
        '<h2 class="tools-search-heading">Universal metadata indexing</h2>'
        not in template_text
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
    assert "const isSyncStateRunning = (state) => (" in template_text
    assert (
        "const setSyncButtonAvailability = (button, isRunning = null) => {"
        in template_text
    )
    assert "const refreshSyncState = async () => {" in template_text
    assert "data-sync-running=" in template_text
    assert 'data-default-label="Refresh index"' in template_text
    assert "button.dataset.syncRunning === 'true'" in template_text
    assert (
        "showLiveStatus('Refreshing universal metadata index…');" not in template_text
    )
    assert (
        "showLiveStatus('Universal metadata reindexing started.', 'success');"
        not in template_text
    )
    assert (
        "const hasSearchText = Boolean(String(queryTextInput?.value || '').trim());"
        in template_text
    )
    assert "|| !hasSearchText" in template_text
    assert "|| Boolean(searchSubmitButton?.disabled);" in template_text
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
    assert "const dateFormat = 'dd-mm-yy';" in template_text
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
    assert "window.OmeroEnhancedSearchIndexedScope?.init({" in template_text
    assert "onStoredScopeApplied: updateSearchSubmitState" in template_text
    assert (
        "const indexedScopeStorageKey = indexedScopeStorageKeyNode" not in template_text
    )
    assert "window.localStorage.getItem(key)" not in template_text
    assert (
        "const initializeIndexedScopeSelectionPersistence = () => {"
        not in template_text
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
    assert "updateSaveQueryButtonState();" in template_text
    assert "clearSearchValidationStatus" in template_text
    assert (
        "small.textContent = formatStatusTimestamp(item.updated_at);" in template_text
    )
    assert 'class="tools-search-saved-meta"' in template_text
    assert "<th>Scope</th>" not in template_text
    assert "tools-search-page-loader" in template_text
    assert "Loading search results" in template_text
    assert "Please wait while the search results are being queried." in template_text
    assert 'id="clear-search-btn"' in template_text
    assert 'id="tools-search-results-summary"' in template_text
    assert 'id="tools-search-results-body"' in template_text
    assert 'data-page-load-message="Resetting search' not in template_text
    assert "const handleClearSearchClick = (event) => {" in template_text
    assert "event.preventDefault();" in template_text
    assert "hidePageLoader();" in template_text
    assert (
        "window.history.replaceState({}, document.title, clearSearchButton.href);"
        in template_text
    )
    assert (
        "resultsBodyEl.innerHTML = '<p class=\"tools-search-empty\">Run a search to see indexed results.</p>';"
        in template_text
    )
    assert (
        "clearSearchButton?.addEventListener('click', handleClearSearchClick);"
        in template_text
    )
    assert "queryTextInput?.blur();" in template_text
    assert (
        '<p class="tools-page-note tools-page-note--section-summary"\n'
        '                   id="tools-search-results-summary">Showing {{ search_payload.results|length }} result(s){% if search_payload.total_count %} from {{ search_payload.total_count }} matching result(s){% endif %}.</p>'
        in template_text
    )
    assert "<th>Preview</th>" in template_text
    assert "<th>Channel(s)</th>" in template_text
    assert (
        '<col class="tools-search-results__col tools-search-results__col--preview">'
        in template_text
    )
    assert (
        '<col class="tools-search-results__col tools-search-results__col--image">'
        in template_text
    )
    assert (
        '<col class="tools-search-results__col tools-search-results__col--context">'
        in template_text
    )
    assert (
        '<col class="tools-search-results__col tools-search-results__col--acquisition">'
        in template_text
    )
    assert (
        '<col class="tools-search-results__col tools-search-results__col--channels">'
        in template_text
    )
    assert 'target="omero-web-image-view"' in template_text
    assert "Indexed by:" in template_text
    assert "Owner:" in template_text
    assert (
        "Owner: {{ row.owner_name|default:row.owner_id }}. Indexed by:" in template_text
    )
    assert "No matching images were found." in template_text
    assert "Run a search to see indexed results." in template_text
    assert "X:" in template_text
    assert "Y:" in template_text
    assert "Page {{ search_payload.page }}" not in template_text
    assert 'class="tools-search-results-body"' in template_text
    assert "tools-search-saved-list--empty" in template_text
    assert "container.classList.add('tools-search-saved-list--empty');" in template_text
    assert (
        "container.classList.remove('tools-search-saved-list--empty');" in template_text
    )
    assert "Optics / Detector" not in template_text


def test_enhanced_search_styles_use_compact_saved_query_grid_and_actions():
    styles_path = (
        Path(__file__).resolve().parents[1] / "static" / "omeroweb_tools" / "styles.css"
    )
    styles_text = styles_path.read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in styles_text
    assert (
        ".admin-tools-page .tools-search-card .tools-search-saved-action--load {"
        in styles_text
    )
    assert (
        ".admin-tools-page .tools-search-card .tools-search-saved-action--delete {"
        in styles_text
    )
    assert "padding: 6px 10px;" in styles_text
    assert "font-size: 13px;" in styles_text
    assert "gap: 1rem;" in styles_text
    assert "column-gap: 0.65rem;" in styles_text
    assert "gap: 0.65rem;" in styles_text
    assert (
        "grid-template-columns: minmax(430px, 2.35fr) max-content minmax(222px, 240px) minmax(214px, 228px) minmax(214px, 228px);"
        in styles_text
    )
    assert "min-width: var(--tools-search-primary-min-width, 0);" in styles_text
    assert "padding-right: 0;" in styles_text
    assert "padding: 0 0.8rem;" in styles_text
    assert "padding: 0.42rem 0.5rem;" in styles_text
    assert "padding: 0.36rem 0.52rem;" in styles_text
    assert "padding: 0.24rem 0;" in styles_text
    assert "flex: 0 0 auto;" in styles_text
    assert "color: #000000;" in styles_text
    assert "grid-template-columns: minmax(0, 1fr) auto;" in styles_text
    assert "width: min(100%, 63rem);" in styles_text
    assert ".tools-search-field--scope {\n    max-width: 15rem;" in styles_text
    assert (
        ".tools-search-field--scope {\n    max-width: 15rem;\n    margin-right: 0.35rem;"
        in styles_text
    )
    assert (
        ".tools-search-field--start-date {\n    margin-right: 0.35rem;" in styles_text
    )
    assert (
        ".tools-search-status-table th:nth-child(3),\n.tools-search-status-table td:nth-child(3) {\n    width: 7.25rem;"
        in styles_text
    )
    assert (
        ".admin-tools-page.admin-tools-page--wide {\n    min-width: 1400px;"
        in styles_text
    )
    assert ".tools-search-saved-meta {" in styles_text
    assert ".tools-search-status-table {" in styles_text
    assert ".tools-search-date-picker-proxy {" in styles_text
    assert ".tools-search-date-picker-button:active {" in styles_text
    assert (
        "transition: background 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease, transform 0.05s ease;"
        in styles_text
    )
    assert "gap: 0.2rem;" in styles_text
    assert "vertical-align: top;" in styles_text
    assert "width: 100%;" in styles_text
    assert "height: 2.5rem;" in styles_text
    assert ".tools-search-field--scope.is-select-active select {" in styles_text
    assert (
        ".tools-search-date-control.is-picker-open .tools-search-date-input:not(.tools-search-date-input--invalid),"
        in styles_text
    )
    assert ".tools-search-query-name-input {" in styles_text
    assert ".tools-search-query-name-input:focus," in styles_text
    assert ".tools-search-query-name-input:focus-visible {" in styles_text
    assert ".tools-search-status-message {" in styles_text
    assert ".tools-search-results td {" in styles_text
    assert ".tools-search-field input:focus," in styles_text
    assert ".tools-search-inline-form input:focus," in styles_text
    assert ".tools-search-section-toggle {" in styles_text
    assert ".tools-search-section-toggle__indicator {" in styles_text
    assert (
        ".tools-search-card--collapsed .tools-search-section-toggle__indicator {"
        in styles_text
    )
    assert "transform: rotate(90deg);" in styles_text
    assert ".tools-search-card--collapsed {\n    gap: 0;" in styles_text
    assert ".tools-search-card--collapsed .tools-search-heading {" in styles_text
    assert (
        ".tools-search-card--precollapsed .tools-search-section-toggle__indicator,"
        in styles_text
    )
    assert ".tools-search-collapsible-body {" in styles_text
    assert (
        "transition: max-height 0.2s ease, opacity 0.16s ease, margin-top 0.2s ease;"
        in styles_text
    )
    assert (
        ".tools-search-card--collapsed .tools-search-collapsible-body {" in styles_text
    )
    assert "margin-top: 0;" in styles_text
    assert "margin-left: var(--tools-search-settings-panel-offset, 0);" in styles_text
    assert "margin: 0;" in styles_text
    assert ".tools-search-results {\n    table-layout: fixed;" in styles_text
    assert "border-collapse: separate;" in styles_text
    assert "border-spacing: 0;" in styles_text
    assert ".tools-search-results thead th {" in styles_text
    assert "position: sticky;" in styles_text
    assert "top: 0;" in styles_text
    assert ".tools-search-results thead th::after {" in styles_text
    assert "background: #e5e7eb;" in styles_text
    assert ".tools-search-results__col--image {\n    width: 37%;" in styles_text
    assert ".tools-search-results__col--context {\n    width: 29%;" in styles_text
    assert ".tools-search-results__col--acquisition {\n    width: 19%;" in styles_text
    assert ".tools-search-results__col--channels {\n    width: 15%;" in styles_text
    assert "contain: strict;" in styles_text
    assert ".tools-search-preview {\n    position: relative;" in styles_text
    assert "border-radius: 0;" in styles_text
    assert ".tools-search-preview__image {" in styles_text
    assert "object-fit: contain;" in styles_text
    assert "object-fit: cover;" not in styles_text
    assert ".tools-search-preview__placeholder {" in styles_text
    assert ".tools-search-preview__icon {" in styles_text
    assert "scrollbar-gutter: stable;" in styles_text
    assert "font-size: 0.95rem;" in styles_text
    assert ".tools-search-settings-panel .tools-page-note {" in styles_text
    assert ".tools-search-empty {" in styles_text
    assert ".tools-search-card--results {" in styles_text
    assert ".tools-search-results-body {" in styles_text
    assert "overflow-y: auto;" in styles_text
    assert "overflow-y: scroll;" not in styles_text
    assert ".tools-search-results-body::-webkit-scrollbar {" in styles_text
    assert ".tools-search-results-body::-webkit-scrollbar-button {" in styles_text
    assert ".tools-search-saved-list--empty .tools-search-empty {" in styles_text
    assert "max-height: 750px;" in styles_text
    assert "white-space: normal;" in styles_text
    assert "overflow-wrap: anywhere;" in styles_text
    assert "width: 18.75rem;" in styles_text
    assert "#ui-datepicker-div.ui-widget-content {" in styles_text
    assert "#ui-datepicker-div table," in styles_text
    assert (
        "#ui-datepicker-div .ui-datepicker-header {\n    position: relative;\n    display: flex;"
        in styles_text
    )
    assert "min-height: 2.65rem;" in styles_text
    assert "padding: 0.35rem 2.4rem;" in styles_text
    assert "width: 6.75rem;" in styles_text
    assert "min-width: 6.75rem;" in styles_text
    assert "min-width: 7.1rem;" not in styles_text
    assert "min-width: 5.25rem;" not in styles_text
    assert (
        "#ui-datepicker-div .ui-datepicker-prev,\n#ui-datepicker-div .ui-datepicker-next {"
        in styles_text
    )
    assert "transform: translateY(-50%);" in styles_text
    assert (
        "#ui-datepicker-div .ui-datepicker-prev span,\n#ui-datepicker-div .ui-datepicker-next span {"
        in styles_text
    )
    assert (
        "#ui-datepicker-div .ui-datepicker-buttonpane button {\n    display: inline-flex;"
        in styles_text
    )
    assert "align-items: center;" in styles_text
    assert "justify-content: center;" in styles_text
    assert "min-height: 2.25rem;" in styles_text
    assert "line-height: 1;" in styles_text
    assert (
        "#ui-datepicker-div td.ui-state-disabled,\n#ui-datepicker-div td.ui-datepicker-unselectable {"
        in styles_text
    )
    assert (
        "#ui-datepicker-div td.ui-state-disabled .ui-state-default,\n#ui-datepicker-div td.ui-datepicker-unselectable .ui-state-default {"
        in styles_text
    )
    assert "color: #94a3b8;" in styles_text
    assert "cursor: not-allowed;" in styles_text
    assert (
        "#ui-datepicker-div .ui-datepicker-buttonpane button.ui-datepicker-current {\n    border-color: #d1d5db;"
        in styles_text
    )
    assert "opacity: 1;" in styles_text
    assert ".tools-search-card > .tools-search-heading--compact + * {" in styles_text
    assert (
        ".tools-search-index-heading + .tools-search-collapsible-body .tools-search-settings-panel {"
        in styles_text
    )
    assert "@media (max-width: 900px) {" in styles_text
    mobile_styles = styles_text.split("@media (max-width: 900px) {", 1)[1]
    assert ".tools-search-grid--primary,\n    .tools-search-grid {" not in mobile_styles
    assert (
        "    .tools-search-grid {\n        grid-template-columns: 1fr;"
        not in mobile_styles
    )
    assert ".tools-search-index-heading {" not in mobile_styles
    assert ".tools-search-saved-list {" not in mobile_styles
    assert (
        "    .tools-search-field--scope,\n    .tools-search-field--start-date {\n        margin-right: 0;"
        in mobile_styles
    )


def test_indexed_scope_browser_persistence_script_is_data_agnostic():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "omeroweb_tools"
        / "enhanced_search_indexed_scope.js"
    )
    script_text = script_path.read_text(encoding="utf-8")

    assert "window.OmeroEnhancedSearchIndexedScope" in script_text
    assert "windowRef.localStorage.getItem(key)" in script_text
    assert "windowRef.localStorage.setItem(key, value)" in script_text
    assert "windowRef.localStorage.removeItem(key)" in script_text
    assert "tools-search-indexed-scope-storage-key" in script_text
    assert "'indexed_scope'" in script_text
    assert "Delta" not in script_text
    assert "757" not in script_text
    assert "password" not in script_text.lower()


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
