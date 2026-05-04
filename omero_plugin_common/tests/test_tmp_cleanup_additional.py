from __future__ import annotations

from iter_test_helpers import next_or_fail

import os
from pathlib import Path

from omero_plugin_common import tmp_cleanup


def test_tmp_cleanup_safe_remove_tree_returns_false_when_walk_or_delete_fails(
    tmp_path, monkeypatch
):
    """Verify temporary cleanup safe remove tree returns false when walk or delete fails.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.mkdir()
    nested = target / "nested"
    nested.mkdir()
    payload = nested / "payload.txt"
    payload.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        tmp_cleanup.os,
        "walk",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("walk failed")),
    )
    assert tmp_cleanup.safe_remove_tree(target, root) is False

    monkeypatch.setattr(tmp_cleanup.os, "walk", os.walk)
    monkeypatch.setattr(
        tmp_cleanup.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("rmtree failed")),
    )
    assert tmp_cleanup.safe_remove_tree(target, root) is False


def test_tmp_cleanup_safe_remove_tree_returns_false_when_file_unlink_fails_in_delete_pass(
    tmp_path,
    monkeypatch,
):
    """Verify temporary cleanup safe remove tree returns false when file unlink fails in delete pass.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.mkdir()
    payload = target / "payload.txt"
    payload.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        tmp_cleanup.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("rmtree failed")),
    )
    assert tmp_cleanup.safe_remove_tree(target, root) is False


def test_tmp_cleanup_marker_helpers_cover_fsync_and_root_validation(
    tmp_path, monkeypatch
):
    """Verify temporary cleanup marker helpers cover fsync and root validation.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    root = tmp_path / "root"
    root.mkdir()
    artifact = root / "artifact.txt"
    artifact.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        tmp_cleanup.os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("open failed")),
    )
    tmp_cleanup._fsync_directory(root)

    root_checks = iter((True, False))
    monkeypatch.setattr(
        tmp_cleanup,
        "is_within_root",
        lambda path, checked_root: next_or_fail(root_checks),
    )
    assert (
        tmp_cleanup.safe_mark_path_for_deferred_cleanup(
            artifact,
            root,
            ttl_seconds=60,
            now=1000,
        )
        is False
    )


def test_tmp_cleanup_covers_symlink_directory_cleanup_and_marker_cleanup_failures(
    tmp_path,
    monkeypatch,
):
    """Verify temporary cleanup covers symlink directory cleanup and marker cleanup failures.

    Inputs: `tmp_path`, `monkeypatch`. Output: `real_unlink` result. Raises on invalid
    or unavailable state.

    or unavailable state.
    """
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.mkdir()
    nested = target / "nested"
    nested.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("payload", encoding="utf-8")
    (nested / "linked.txt").symlink_to(outside)

    assert tmp_cleanup.safe_remove_tree(target, root) is False

    (nested / "linked.txt").unlink()
    payload = nested / "payload.txt"
    payload.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        tmp_cleanup.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("rmtree failed")),
    )
    assert tmp_cleanup.safe_remove_tree(target, root) is False

    artifact = root / "artifact.txt"
    artifact.write_text("payload", encoding="utf-8")
    real_unlink = Path.unlink
    monkeypatch.setattr(
        tmp_cleanup.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
    )

    def _fail_tmp_unlink(self, *args, **kwargs):
        """Fail tmp unlink.

        Inputs: `*args`, `**kwargs`. Output: `real_unlink` result. Raises on invalid or
        unavailable state.

        unavailable state.
        """
        if self.suffix == ".tmp":
            raise OSError("cleanup failed")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _fail_tmp_unlink)
    assert (
        tmp_cleanup.safe_mark_path_for_deferred_cleanup(
            artifact,
            root,
            ttl_seconds=60,
            now=1000,
        )
        is False
    )
