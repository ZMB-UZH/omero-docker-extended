from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LINUX_SERVER_FILES = (
    "omeroweb_admin_tools/services/storage_quotas.py",
    "omeroweb_import/views/core_functions.py",
)


def test_linux_server_files_do_not_restore_windows_filesystem_fallbacks() -> None:
    """Verify server filesystem code remains on its supported POSIX path.

    Inputs: Linux production source fixtures. Output: fails on fallback drift.
    """
    forbidden_markers = (
        'os.name == "nt"',
        "Windows fallback",
        "_managed_fd_fallback_enabled",
        "_copy_zarr_tree_without_symlinks_portable",
        'getattr(os, "O_DIRECTORY"',
        'getattr(os, "O_NOFOLLOW"',
    )

    for relative_path in LINUX_SERVER_FILES:
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for marker in forbidden_markers:
            assert marker not in content, f"{relative_path} contains {marker!r}"
