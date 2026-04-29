'use strict';

(function () {
    const DEFAULT_SERVER_BACKED_PARAMS = [
        'query_text',
        'indexed_scope',
        'acquisition_date_from',
        'acquisition_date_to',
        'page',
    ];

    /** Return parsed JSON script text for the given element id. */
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

    /** Return a localStorage value when browser storage is available. */
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

    /** Persist a value to browser storage when storage is available. */
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

    /** Remove a browser storage value when storage is available. */
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

    /** Return the valid indexed-scope option values. */
    const indexedScopeValues = (selectEl) => new Set(
        Array.from(selectEl?.options || []).map((option) => option.value)
    );

    /** Return whether the URL already carries server-backed search state. */
    const hasServerBackedSearchQuery = (windowRef, serverBackedParams) => {
        const params = new URLSearchParams(windowRef.location.search);
        return serverBackedParams.some((name) => params.has(name));
    };

    /** Return the configured indexed-scope select element. */
    const selectElementForOptions = (documentRef, options) => (
        documentRef.getElementById(options.selectId || 'indexed_scope')
    );

    /** Return the browser storage key configured for indexed scope. */
    const storageKeyForOptions = (documentRef, options) => (
        options.storageKey || parseJsonScript(
            documentRef,
            options.storageKeyScriptId || 'tools-search-indexed-scope-storage-key'
        )
    );

    /** Return the query parameters that should block stored scope replay. */
    const serverBackedParamsForOptions = (options) => {
        if (Array.isArray(options.serverBackedParams)) {
            return options.serverBackedParams;
        }
        return DEFAULT_SERVER_BACKED_PARAMS;
    };

    /** Persist the selected scope only when it is still valid. */
    const persistScope = (windowRef, storageKey, selectEl) => {
        const validValues = indexedScopeValues(selectEl);
        if (validValues.has(selectEl.value)) {
            writeBrowserStorage(windowRef, storageKey, selectEl.value);
            return;
        }
        removeBrowserStorage(windowRef, storageKey);
    };

    /** Remove stored scope values that are no longer valid options. */
    const discardInvalidStoredScope = (
        windowRef,
        storageKey,
        validValues,
        storedScope
    ) => {
        if (storedScope === null || validValues.has(storedScope)) {
            return false;
        }
        removeBrowserStorage(windowRef, storageKey);
        return true;
    };

    /** Return whether stored scope can be applied to the current search. */
    const shouldApplyStoredScope = (
        windowRef,
        serverBackedParams,
        validValues,
        storedScope
    ) => (
        !hasServerBackedSearchQuery(windowRef, serverBackedParams)
        && validValues.has(storedScope)
    );

    /** Notify callers after a stored scope value is restored. */
    const notifyStoredScopeApplied = (callback, value) => {
        if (typeof callback === 'function') {
            callback(value);
        }
    };

    /** Restore a stored indexed-scope value when current URL state allows it. */
    const restoreStoredScope = ({
        windowRef,
        storageKey,
        selectEl,
        serverBackedParams,
        onStoredScopeApplied,
    }) => {
        const validValues = indexedScopeValues(selectEl);
        const storedScope = readBrowserStorage(windowRef, storageKey);
        if (discardInvalidStoredScope(
            windowRef,
            storageKey,
            validValues,
            storedScope
        )) {
            return;
        }
        if (!shouldApplyStoredScope(
            windowRef,
            serverBackedParams,
            validValues,
            storedScope
        )) {
            return;
        }
        selectEl.value = storedScope;
        notifyStoredScopeApplied(onStoredScopeApplied, selectEl.value);
    };

    /** Initialize indexed-scope persistence for the search form. */
    const init = (options = {}) => {
        const windowRef = options.windowRef || window;
        const documentRef = options.documentRef || windowRef.document;
        const selectEl = selectElementForOptions(documentRef, options);
        if (!selectEl) {
            return null;
        }
        const storageKey = storageKeyForOptions(documentRef, options);
        const serverBackedParams = serverBackedParamsForOptions(options);

        /** Persist the current select element value. */
        const persist = () => persistScope(windowRef, storageKey, selectEl);
        restoreStoredScope({
            windowRef,
            storageKey,
            selectEl,
            serverBackedParams,
            onStoredScopeApplied: options.onStoredScopeApplied,
        });
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
