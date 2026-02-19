(() => {
    try {
        const { userId: rawUserId } = document.documentElement.dataset;
        const userId = rawUserId ? Number(rawUserId) : null;
        const storageKeySuffix = userId ? `_u${userId}` : '';
        const storageKey = `omeroweb_upload_special_upload_selection_v1${storageKeySuffix}`;
        const raw = window.localStorage?.getItem(storageKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (parsed?.value) {
            document.documentElement.classList.add('special-upload-active');
        }
    } catch (error) {
        // Ignore storage access errors.
    }
})();
