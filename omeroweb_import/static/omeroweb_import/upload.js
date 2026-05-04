(function restoreSpecialUploadSelection() {
    // Build Special Upload Selection Storage Key. Inputs: rawUserId. Output: return value.
    function makeSpecialUploadSelectionStorageKey(rawUserId) {
        const userId = rawUserId ? Number(rawUserId) : null;
        const storageKeySuffix = userId ? `_u${userId}` : '';
        return `omeroweb_import_special_upload_selection_v1${storageKeySuffix}`;
    }

    // Return whether Persisted Special Upload Selection. Inputs: rawValue. Output: return value.
    function hasPersistedSpecialUploadSelection(rawValue) {
        return Boolean(JSON.parse(rawValue || 'null')?.value);
    }

    try {
        const { userId: rawUserId } = document.documentElement.dataset;
        const storageKey = makeSpecialUploadSelectionStorageKey(rawUserId);
        const raw = window.localStorage?.getItem(storageKey);
        if (hasPersistedSpecialUploadSelection(raw)) {
            document.documentElement.classList.add('special-upload-active');
        }
    } catch {
        // Ignore storage access errors.
    }
}());
