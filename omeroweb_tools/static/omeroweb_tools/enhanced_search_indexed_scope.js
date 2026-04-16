(function () {
    'use strict';

    const DEFAULT_SERVER_BACKED_PARAMS = [
        'query_text',
        'indexed_scope',
        'acquisition_date_from',
        'acquisition_date_to',
        'page',
    ];

    const parseJsonScript = (documentRef, scriptId) => {
        const node = documentRef.getElementById(scriptId);
        if (!node) {
            return '';
        }
        try {
            return JSON.parse(node.textContent || '""');
        } catch (_error) {
            return '';
        }
    };

    const readBrowserStorage = (windowRef, key) => {
        if (!key) {
            return null;
        }
        try {
            return windowRef.localStorage.getItem(key);
        } catch (_error) {
            return null;
        }
    };

    const writeBrowserStorage = (windowRef, key, value) => {
        if (!key) {
            return;
        }
        try {
            windowRef.localStorage.setItem(key, value);
        } catch (_error) {
            // Browser storage may be disabled; the visible selection still works.
        }
    };

    const removeBrowserStorage = (windowRef, key) => {
        if (!key) {
            return;
        }
        try {
            windowRef.localStorage.removeItem(key);
        } catch (_error) {
            // Browser storage may be disabled.
        }
    };

    const indexedScopeValues = (selectEl) => new Set(
        Array.from(selectEl?.options || []).map((option) => option.value)
    );

    const hasServerBackedSearchQuery = (windowRef, serverBackedParams) => {
        const params = new URLSearchParams(windowRef.location.search);
        return serverBackedParams.some((name) => params.has(name));
    };

    const init = (options = {}) => {
        const windowRef = options.windowRef || window;
        const documentRef = options.documentRef || windowRef.document;
        const selectEl = documentRef.getElementById(options.selectId || 'indexed_scope');
        if (!selectEl) {
            return null;
        }
        const storageKey = options.storageKey || parseJsonScript(
            documentRef,
            options.storageKeyScriptId || 'tools-search-indexed-scope-storage-key'
        );
        const serverBackedParams = Array.isArray(options.serverBackedParams)
            ? options.serverBackedParams
            : DEFAULT_SERVER_BACKED_PARAMS;

        const persist = () => {
            const validValues = indexedScopeValues(selectEl);
            if (validValues.has(selectEl.value)) {
                writeBrowserStorage(windowRef, storageKey, selectEl.value);
            } else {
                removeBrowserStorage(windowRef, storageKey);
            }
        };

        const validValues = indexedScopeValues(selectEl);
        const storedScope = readBrowserStorage(windowRef, storageKey);
        if (storedScope !== null && !validValues.has(storedScope)) {
            removeBrowserStorage(windowRef, storageKey);
        }
        if (
            !hasServerBackedSearchQuery(windowRef, serverBackedParams)
            && validValues.has(storedScope)
        ) {
            selectEl.value = storedScope;
            if (typeof options.onStoredScopeApplied === 'function') {
                options.onStoredScopeApplied(selectEl.value);
            }
        }
        persist();
        selectEl.addEventListener('change', persist);
        return {
            persist,
            storageKey,
        };
    };

    window.OmeroEnhancedSearchIndexedScope = {
        init,
    };
}());
