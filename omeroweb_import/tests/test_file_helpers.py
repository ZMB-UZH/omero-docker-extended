from __future__ import annotations

from omeroweb_import.utils import file_helpers


def test_initialize_directories_populates_caches_and_permissions(tmp_path, monkeypatch):
    """Verify initialize directories populates caches and permissions.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    file_helpers._DIRECTORY_CACHE.upload_root = None
    file_helpers._DIRECTORY_CACHE.jobs_root = None

    monkeypatch.setattr(file_helpers, "resolve_upload_root", lambda: upload_root)
    monkeypatch.setattr(file_helpers, "resolve_jobs_root", lambda: jobs_root)

    file_helpers.initialize_directories()

    assert file_helpers.get_upload_root() == upload_root
    assert file_helpers.get_jobs_root() == jobs_root
    assert upload_root.is_dir()
    assert jobs_root.is_dir()


def test_file_helper_directory_and_name_safety_helpers(tmp_path):
    """Verify file helper directory and name safety helpers.

    Inputs: `tmp_path`. Output: None.
    """
    target = tmp_path / "nested" / "artifact.txt"

    assert file_helpers.ensure_parent_dir(target) is True
    assert target.parent.is_dir()

    managed_dir = tmp_path / "managed"
    assert file_helpers.ensure_dir(managed_dir) is True
    assert file_helpers.ensure_dir_with_permissions(managed_dir, 0o700) is True
    assert (managed_dir.stat().st_mode & 0o777) == 0o700
    assert (
        file_helpers.safe_relative_path(r"..\\dangerous/<name>.txt")
        == "_\\\\dangerous/_name_.txt"
    )


def test_file_helper_safe_remove_tree_requires_root_membership(tmp_path):
    """Verify file helper safe remove tree requires root membership.

    Inputs: `tmp_path`. Output: None.
    """
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside"
    inside.mkdir()
    (inside / "payload.txt").write_text("x", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()

    assert file_helpers.is_within_root(inside, root) is True
    assert file_helpers.is_within_root(outside, root) is False

    file_helpers.safe_remove_tree(inside, root)
    assert not inside.exists()

    file_helpers.safe_remove_tree(outside, root)
    assert outside.exists()
