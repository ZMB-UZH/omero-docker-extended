from __future__ import annotations

import shutil

from omeroweb_import.utils import file_helpers


def test_file_helpers_return_false_for_directory_creation_and_chmod_failures(
    tmp_path, monkeypatch
):
    path_type = type(tmp_path)
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()

    monkeypatch.setattr(
        path_type,
        "mkdir",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("mkdir failed")),
    )
    assert file_helpers.ensure_parent_dir(tmp_path / "nested" / "artifact.txt") is False
    assert file_helpers.ensure_dir(tmp_path / "managed") is False

    monkeypatch.setattr(
        path_type,
        "chmod",
        lambda self, mode: (_ for _ in ()).throw(OSError("chmod failed")),
    )
    assert file_helpers.ensure_dir_with_permissions(existing_dir, 0o700) is False


def test_file_helpers_cover_cache_safe_names_and_remove_failures(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    upload_root.mkdir()
    jobs_root.mkdir()

    file_helpers._UPLOAD_ROOT_CACHE = None
    file_helpers._JOBS_ROOT_CACHE = None
    monkeypatch.setattr(file_helpers, "resolve_upload_root", lambda: upload_root)
    monkeypatch.setattr(file_helpers, "resolve_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(
        type(tmp_path),
        "chmod",
        lambda self, mode: (_ for _ in ()).throw(OSError("chmod failed")),
    )
    file_helpers.initialize_directories()
    assert file_helpers.get_upload_root() == upload_root
    assert file_helpers.get_jobs_root() == jobs_root

    assert file_helpers.safe_relative_path("  ") == "unnamed"
    assert (
        file_helpers.safe_relative_path("/../unsafe:name?.txt") == "_/unsafe_name_.txt"
    )

    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside"
    inside.mkdir()
    (inside / "payload.txt").write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("remove failed")),
    )
    file_helpers.safe_remove_tree(inside, root)
    assert inside.exists()


def test_file_helpers_cover_cached_initialization_getters_and_new_dir_creation(
    tmp_path, monkeypatch
):
    cached_upload = tmp_path / "cached-upload"
    cached_jobs = tmp_path / "cached-jobs"

    monkeypatch.setattr(file_helpers, "_UPLOAD_ROOT_CACHE", cached_upload)
    monkeypatch.setattr(file_helpers, "_JOBS_ROOT_CACHE", cached_jobs)
    monkeypatch.setattr(
        file_helpers,
        "resolve_upload_root",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected resolve")),
    )
    monkeypatch.setattr(
        file_helpers,
        "resolve_jobs_root",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected resolve")),
    )
    file_helpers.initialize_directories()
    assert file_helpers._UPLOAD_ROOT_CACHE == cached_upload
    assert file_helpers._JOBS_ROOT_CACHE == cached_jobs

    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    monkeypatch.setattr(file_helpers, "_UPLOAD_ROOT_CACHE", None)
    monkeypatch.setattr(file_helpers, "_JOBS_ROOT_CACHE", jobs_root)
    monkeypatch.setattr(
        file_helpers,
        "initialize_directories",
        lambda: setattr(file_helpers, "_UPLOAD_ROOT_CACHE", upload_root),
    )
    assert file_helpers.get_upload_root() == upload_root

    monkeypatch.setattr(file_helpers, "_UPLOAD_ROOT_CACHE", upload_root)
    monkeypatch.setattr(file_helpers, "_JOBS_ROOT_CACHE", None)
    monkeypatch.setattr(
        file_helpers,
        "initialize_directories",
        lambda: setattr(file_helpers, "_JOBS_ROOT_CACHE", jobs_root),
    )
    assert file_helpers.get_jobs_root() == jobs_root

    managed_dir = tmp_path / "managed"
    assert file_helpers.ensure_dir_with_permissions(managed_dir, 0o750) is True
    assert managed_dir.is_dir()
    assert (managed_dir.stat().st_mode & 0o777) == 0o750
