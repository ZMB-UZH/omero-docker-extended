from __future__ import annotations

from omero_plugin_common import tmp_cleanup


def test_safe_remove_tree_and_job_data_stay_within_root(tmp_path):
    """Verify safe remove tree and job data stay within root.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in safe remove tree and job data stay within root.
    """
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
    """Confirm safe remove tree rejects symlinked paths is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in safe remove tree rejects symlinked paths.
    """
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
    """Check safe mark path for deferred cleanup writes markers for files and dirs cleanup behavior.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when safe mark path for deferred cleanup writes markers for files and dirs accepts unsafe input.
    """
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


def test_tmp_cleanup_helpers_reject_invalid_roots_and_symlinked_children(tmp_path):
    """Confirm tmp cleanup helpers reject invalid roots and symlinked children is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when tmp cleanup helpers reject invalid roots and symlinked children stops reporting the expected error.
    """
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    nested = root / "nested"
    nested.mkdir()
    (nested / "payload.txt").write_text("payload", encoding="utf-8")
    (nested / "escape-link").symlink_to(outside, target_is_directory=True)

    assert tmp_cleanup.is_within_root(nested / "payload.txt", root) is True
    assert tmp_cleanup.is_within_root(outside / "payload.txt", root) is False
    assert tmp_cleanup.safe_remove_tree(nested, root) is False
    assert nested.exists()


def test_tmp_cleanup_resolution_failures_from_symlink_loops_are_safe(tmp_path):
    """Check tmp cleanup resolution failures from symlink loops are safe cleanup behavior.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when tmp cleanup resolution failures from symlink loops are safe accepts unsafe input.
    """
    root = tmp_path / "root"
    root.mkdir()
    loop = root / "loop"
    loop.symlink_to(loop)

    assert tmp_cleanup.is_within_root(loop, root) is False
    assert tmp_cleanup.safe_remove_tree(loop, root) is False
    assert loop.is_symlink()


def test_tmp_cleanup_refuses_root_deletion_and_unsafe_job_ids(tmp_path):
    """Check tmp cleanup refuses root deletion and unsafe job IDs cleanup behavior.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in tmp cleanup refuses root deletion and unsafe job IDs.
    """
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload.txt").write_text("payload", encoding="utf-8")

    assert tmp_cleanup.safe_remove_tree(root, root) is False
    assert root.exists()
    assert tmp_cleanup.safe_remove_job_data("../escape", root) is False
    assert tmp_cleanup.safe_remove_job_data("bad/name", root) is False


def test_tmp_cleanup_missing_paths_must_stay_within_root(tmp_path):
    """Check tmp cleanup missing paths must stay within root cleanup behavior.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in tmp cleanup missing paths must stay within root.
    """
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    assert tmp_cleanup.safe_remove_tree(root / "missing", root) is True
    assert tmp_cleanup.safe_remove_tree(outside / "missing", root) is False
    assert (
        tmp_cleanup.safe_mark_path_for_deferred_cleanup(
            root / "missing",
            root,
            ttl_seconds=60,
        )
        is True
    )
    assert (
        tmp_cleanup.safe_mark_path_for_deferred_cleanup(
            outside / "missing",
            root,
            ttl_seconds=60,
        )
        is False
    )


def test_safe_mark_path_for_deferred_cleanup_rejects_invalid_inputs_and_cleans_temp_file(
    tmp_path, monkeypatch
):
    """Confirm safe mark path for deferred cleanup rejects invalid inputs and cleans temp file is rejected at the boundary.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None after assertions pass. Raises: OSError for the exercised failure path.
    """
    root = tmp_path / "root"
    root.mkdir()
    target = root / "artifact.txt"
    target.write_text("payload", encoding="utf-8")
    symlink = root / "artifact-link"
    symlink.symlink_to(target)

    assert not tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        target, root, ttl_seconds="bad"
    )
    assert not tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        target, root, ttl_seconds=0
    )
    assert not tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        symlink, root, ttl_seconds=60
    )
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("outside", encoding="utf-8")
    assert not tmp_cleanup.safe_mark_path_for_deferred_cleanup(
        outside_path,
        root,
        ttl_seconds=60,
    )

    created_tmp = {}
    real_replace = tmp_cleanup.os.replace

    def _failing_replace(src, dst):
        """Record the failing replace call on the test double for later assertions.

        Inputs: `src`, `dst`. Output: None. Raises: OSError for the exercised failure path.
        """
        created_tmp["path"] = src
        raise OSError("replace failed")

    monkeypatch.setattr(tmp_cleanup.os, "replace", _failing_replace)
    assert (
        tmp_cleanup.safe_mark_path_for_deferred_cleanup(
            target, root, ttl_seconds=60, now=1000
        )
        is False
    )
    assert "path" in created_tmp
    assert not created_tmp["path"].exists()
    monkeypatch.setattr(tmp_cleanup.os, "replace", real_replace)
