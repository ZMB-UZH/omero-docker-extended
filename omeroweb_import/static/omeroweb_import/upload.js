(function restoreSpecialUploadSelection() {
    /** Return the per-user storage key for special upload selection. */
    function makeSpecialUploadSelectionStorageKey(rawUserId) {
        const userId = rawUserId ? Number(rawUserId) : null;
        const storageKeySuffix = userId ? `_u${userId}` : '';
        return `omeroweb_import_special_upload_selection_v1${storageKeySuffix}`;
    }

    /** Return whether a stored upload selection contains an active value. */
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
