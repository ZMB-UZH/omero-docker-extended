(function restoreSpecialUploadSelection() {
    try {
        const { userId: rawUserId } = document.documentElement.dataset;
        const userId = rawUserId ? Number(rawUserId) : null;
        const storageKeySuffix = userId ? `_u${userId}` : '';
        const storageKey = `omeroweb_import_special_upload_selection_v1${storageKeySuffix}`;
        const raw = window.localStorage?.getItem(storageKey);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed?.value) {
                document.documentElement.classList.add('special-upload-active');
            }
        }
    } catch {
        // Ignore storage access errors.
    }
}());
