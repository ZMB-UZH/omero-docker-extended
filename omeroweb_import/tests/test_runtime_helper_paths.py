from __future__ import annotations

from pathlib import Path

import pytest

from omeroweb_import.views import core_functions


def test_directory_initialization_uses_parent_checks_and_caches_paths(
    tmp_path, monkeypatch
):
    """Verify directory initialization uses parent checks and caches paths.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in directory initialization uses parent checks and caches paths.
    """
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    ensure_parent_calls = []
    ensure_dir_calls = []

    monkeypatch.setattr(core_functions, "_resolve_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_resolve_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        core_functions,
        "_ensure_parent_dir",
        lambda path: ensure_parent_calls.append(path) or True,
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_dir_with_permissions",
        lambda path, mode: ensure_dir_calls.append((path, mode)) or True,
    )
    core_functions._DIRECTORY_CACHE.upload_root = None
    core_functions._DIRECTORY_CACHE.jobs_root = None
    core_functions._DIRECTORY_CACHE.initialized = False

    assert core_functions._get_upload_root() == upload_root
    assert core_functions._get_jobs_root() == jobs_root
    assert ensure_parent_calls == [upload_root, jobs_root]
    assert ensure_dir_calls == [(upload_root, 0o700), (jobs_root, 0o700)]
    assert core_functions._DIRECTORY_CACHE.initialized is True

    ensure_parent_calls.clear()
    ensure_dir_calls.clear()
    assert core_functions._get_upload_root() == upload_root
    assert core_functions._get_jobs_root() == jobs_root
    core_functions._initialize_directories()
    assert ensure_parent_calls == []
    assert ensure_dir_calls == []


def test_upload_root_accessor_reports_failed_initialization(monkeypatch) -> None:
    """Verify upload root accessor reports failed initialization.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in upload root accessor reports failed initialization.
    """
    original_upload_root = core_functions._DIRECTORY_CACHE.upload_root
    original_initialized = core_functions._DIRECTORY_CACHE.initialized
    try:
        core_functions._DIRECTORY_CACHE.upload_root = None
        core_functions._DIRECTORY_CACHE.initialized = False
        monkeypatch.setattr(core_functions, "_initialize_directories", lambda: None)

        with pytest.raises(RuntimeError, match="Upload root was not initialized"):
            core_functions._get_upload_root()
    finally:
        core_functions._DIRECTORY_CACHE.upload_root = original_upload_root
        core_functions._DIRECTORY_CACHE.initialized = original_initialized


def test_directory_helpers_cover_failure_and_permission_fix_paths(
    tmp_path, monkeypatch
):
    """Verify the directory helpers cover failure and permission fix paths safety boundary.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `original_chmod` result.
    """
    target = tmp_path / "nested" / "child"
    target.parent.mkdir(parents=True)
    assert core_functions._ensure_parent_dir(target) is True

    core_functions._DIRECTORY_CACHE.upload_root = None
    core_functions._DIRECTORY_CACHE.jobs_root = None
    core_functions._DIRECTORY_CACHE.initialized = False
    monkeypatch.setattr(
        core_functions, "_resolve_upload_root", lambda: tmp_path / "uploads"
    )
    monkeypatch.setattr(core_functions, "_resolve_jobs_root", lambda: tmp_path / "jobs")
    with monkeypatch.context() as init_patch:
        init_patch.setattr(core_functions, "_ensure_parent_dir", lambda path: False)
        assert core_functions._initialize_directories() is None
        assert core_functions._DIRECTORY_CACHE.initialized is False
        with pytest.raises(RuntimeError, match="Jobs root was not initialized"):
            core_functions._get_jobs_root()

    core_functions._DIRECTORY_CACHE.upload_root = None
    core_functions._DIRECTORY_CACHE.jobs_root = None
    core_functions._DIRECTORY_CACHE.initialized = False
    with monkeypatch.context() as init_patch:
        init_patch.setattr(core_functions, "_ensure_parent_dir", lambda path: True)
        init_patch.setattr(
            core_functions,
            "_ensure_dir_with_permissions",
            lambda path, mode: path.name != "jobs",
        )
        assert core_functions._initialize_directories() is None
        assert core_functions._DIRECTORY_CACHE.initialized is False

    created = tmp_path / "created"
    assert core_functions._ensure_dir_with_permissions(created, 0o700) is True
    assert created.exists()

    chmod_calls = []
    existing = tmp_path / "existing"
    existing.mkdir(mode=0o755)
    original_chmod = Path.chmod

    def chmod(self, path_mode):
        """Return the chmod.

        Inputs: `path_mode`. Output: `original_chmod` result.
        """
        if self == existing:
            chmod_calls.append(path_mode)
            return None
        return original_chmod(self, path_mode)

    monkeypatch.setattr(Path, "chmod", chmod)
    assert core_functions._ensure_dir_with_permissions(existing, 0o700) is True
    assert chmod_calls == [0o700]

    inaccessible = tmp_path / "inaccessible"
    inaccessible.mkdir()
    original_access = core_functions.os.access

    def access(path, mode):
        """Return the access.

        Inputs: `path` path, `mode`. Output: `original_access` result.
        """
        if Path(path) == inaccessible:
            return False
        return original_access(path, mode)

    monkeypatch.setattr(core_functions.os, "access", access)
    assert core_functions._ensure_dir_with_permissions(inaccessible, 0o700) is False
    assert core_functions._ensure_dir(inaccessible) is False


def test_runtime_env_helpers_normalize_boolean_and_integer_values(monkeypatch):
    """Check runtime env helpers normalize boolean and integer values parsing against the documented contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in runtime env helpers normalize boolean and integer values.
    """
    monkeypatch.setenv("IMPORT_BATCH", " 7 ")
    monkeypatch.setenv("FEATURE_FLAG", " yes ")
    monkeypatch.setenv("BROKEN_BATCH", "bad-value")
    monkeypatch.setenv("ZERO_BATCH", "0")

    assert core_functions._get_env_int("IMPORT_BATCH", 5, 1, 10) == 7
    assert core_functions._get_env_int("BROKEN_BATCH", 5, 1, 10) == 5
    assert core_functions._get_env_int("ZERO_BATCH", 5, 1, 10) == 1
    assert core_functions._get_env_bool("FEATURE_FLAG") is True
    assert core_functions._get_env_bool("MISSING_FEATURE", default=True) is True
