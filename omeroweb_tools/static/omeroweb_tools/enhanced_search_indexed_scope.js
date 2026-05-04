'use strict';

(function () {
    const DEFAULT_SERVER_BACKED_PARAMS = [
        'query_text',
        'indexed_scope',
        'acquisition_date_from',
        'acquisition_date_to',
        'page',
    ];

    // Parse JSON Script. Inputs: documentRef, scriptId. Output: return value.
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

    // Read Browser Storage. Inputs: windowRef, key. Output: return value.
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

    // Write Browser Storage. Inputs: windowRef, key, value. Output: return value.
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

    // Remove Browser Storage. Inputs: windowRef, key. Output: return value.
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

    // Return indexed Scope Values. Inputs: selectEl. Output: return value.
    const indexedScopeValues = (selectEl) => new Set(
        Array.from(selectEl?.options || []).map((option) => option.value)
    );

    // Return whether Server Backed Search Query. Inputs: windowRef, serverBackedParams. Output: return value.
    const hasServerBackedSearchQuery = (windowRef, serverBackedParams) => {
        const params = new URLSearchParams(windowRef.location.search);
        return serverBackedParams.some((name) => params.has(name));
    };

    // Select Element For Options. Inputs: documentRef, options. Output: return value.
    const selectElementForOptions = (documentRef, options) => (
        documentRef.getElementById(options.selectId || 'indexed_scope')
    );

    // Return storage Key For Options. Inputs: documentRef, options. Output: return value.
    const storageKeyForOptions = (documentRef, options) => (
        options.storageKey || parseJsonScript(
            documentRef,
            options.storageKeyScriptId || 'tools-search-indexed-scope-storage-key'
        )
    );

    // Return server Backed Params For Options. Inputs: options. Output: return value.
    const serverBackedParamsForOptions = (options) => {
        if (Array.isArray(options.serverBackedParams)) {
            return options.serverBackedParams;
        }
        return DEFAULT_SERVER_BACKED_PARAMS;
    };

    // Return persist Scope. Inputs: windowRef, storageKey, selectEl. Output: return value.
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

    // Return notify Stored Scope Applied. Inputs: callback, value. Output: return value.
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

    // Initialize the feature. Inputs: options. Output: return value.
    const init = (options = {}) => {
        const windowRef = options.windowRef || window;
        const documentRef = options.documentRef || windowRef.document;
        const selectEl = selectElementForOptions(documentRef, options);
        if (!selectEl) {
            return null;
        }
        const storageKey = storageKeyForOptions(documentRef, options);
        const serverBackedParams = serverBackedParamsForOptions(options);

        // Persist current state. Inputs: none. Output: return value.
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
