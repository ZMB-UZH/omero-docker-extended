from __future__ import annotations

from pathlib import Path

from omero_plugin_common import tmp_cleanup


def test_safe_remove_tree_removes_nested_directory_within_root(tmp_path: Path) -> None:
    root = tmp_path / "managed-root"
    target = root / "job123" / "nested"
    target.mkdir(parents=True)
    (target / "payload.bin").write_text("payload", encoding="utf-8")

    removed = tmp_cleanup.safe_remove_tree(root / "job123", root)

    assert removed is True
    assert not (root / "job123").exists()


def test_safe_remove_tree_refuses_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "managed-root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "payload.bin").write_text("payload", encoding="utf-8")

    removed = tmp_cleanup.safe_remove_tree(outside, root)

    assert removed is False
    assert outside.exists()


def test_safe_remove_tree_refuses_symlink_root_target(tmp_path: Path) -> None:
    root = tmp_path / "managed-root"
    root.mkdir()
    real_target = root / "real-target"
    real_target.mkdir()
    symlink_target = root / "symlink-target"
    symlink_target.symlink_to(real_target, target_is_directory=True)

    removed = tmp_cleanup.safe_remove_tree(symlink_target, root)

    assert removed is False
    assert symlink_target.exists()
    assert real_target.exists()


def test_safe_remove_tree_refuses_directory_with_symlinked_child(tmp_path: Path) -> None:
    root = tmp_path / "managed-root"
    target = root / "job123"
    safe_child = target / "safe"
    outside = tmp_path / "outside"
    root.mkdir()
    safe_child.mkdir(parents=True)
    outside.mkdir()
    (outside / "payload.bin").write_text("payload", encoding="utf-8")
    (target / "linked").symlink_to(outside, target_is_directory=True)

    removed = tmp_cleanup.safe_remove_tree(target, root)

    assert removed is False
    assert target.exists()
    assert outside.exists()


def test_safe_remove_job_data_targets_job_directory_under_upload_root(tmp_path: Path) -> None:
    upload_root = tmp_path / "upload-root"
    job_dir = upload_root / "job123"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.bin").write_text("payload", encoding="utf-8")

    removed = tmp_cleanup.safe_remove_job_data("job123", upload_root)

    assert removed is True
    assert not job_dir.exists()
