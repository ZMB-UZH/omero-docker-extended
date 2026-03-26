from __future__ import annotations

from omero_plugin_common import tmp_cleanup


def test_safe_remove_tree_and_job_data_stay_within_root(tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    job_dir = upload_root / "job-1" / "nested"
    job_dir.mkdir(parents=True)
    (job_dir / "file.txt").write_text("payload", encoding="utf-8")

    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    outside_target = outside_root / "data"
    outside_target.mkdir()

    assert tmp_cleanup.safe_remove_job_data("job-1", upload_root) is True
    assert not (upload_root / "job-1").exists()
    assert tmp_cleanup.safe_remove_tree(outside_target, upload_root) is False


def test_safe_remove_tree_rejects_symlinked_paths(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    real_dir = root / "real"
    real_dir.mkdir()
    link_path = root / "linked"
    link_path.symlink_to(real_dir, target_is_directory=True)

    assert tmp_cleanup.safe_remove_tree(link_path, root) is False
    assert real_dir.exists()


def test_safe_mark_path_for_deferred_cleanup_writes_markers_for_files_and_dirs(
    tmp_path,
):
    root = tmp_path / "root"
    root.mkdir()
    dir_path = root / "dir"
    dir_path.mkdir()
    file_path = root / "dir" / "artifact.txt"
    file_path.write_text("x", encoding="utf-8")

    assert tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        dir_path, root, ttl_seconds=60, now=1000
    )
    assert tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        file_path, root, ttl_seconds=60, now=1000
    )

    assert (dir_path / tmp_cleanup.RETENTION_DIR_MARKER_NAME).read_text(
        encoding="utf-8"
    ).strip() == "1060"
    assert (
        file_path.parent
        / f".{file_path.name}{tmp_cleanup.RETENTION_FILE_MARKER_SUFFIX}"
    ).read_text(encoding="utf-8").strip() == "1060"
    assert not tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        root / "missing", root, ttl_seconds=0
    )
