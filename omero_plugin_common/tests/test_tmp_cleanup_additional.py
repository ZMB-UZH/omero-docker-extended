from __future__ import annotations

import os
from pathlib import Path

from omero_plugin_common import tmp_cleanup


def test_tmp_cleanup_safe_remove_tree_returns_false_when_walk_or_delete_fails(
    tmp_path, monkeypatch
):
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
        type(payload),
        "unlink",
        lambda self: (_ for _ in ()).throw(OSError("unlink failed")),
    )
    assert tmp_cleanup.safe_remove_tree(target, root) is False


def test_tmp_cleanup_safe_remove_tree_returns_false_when_file_unlink_fails_in_delete_pass(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.mkdir()
    payload = target / "payload.txt"
    payload.write_text("payload", encoding="utf-8")

    real_unlink = Path.unlink

    def _fail_payload_unlink(self, *args, **kwargs):
        if self == payload:
            raise OSError("unlink failed")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _fail_payload_unlink)
    assert tmp_cleanup.safe_remove_tree(target, root) is False


def test_tmp_cleanup_marker_helpers_cover_fsync_and_root_validation(
    tmp_path, monkeypatch
):
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
        lambda path, checked_root: next(root_checks),
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

    real_rmdir = Path.rmdir

    def _fail_nested_rmdir(self):
        if self == nested:
            raise OSError("nested rmdir failed")
        return real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", _fail_nested_rmdir)
    assert tmp_cleanup.safe_remove_tree(target, root) is False

    monkeypatch.setattr(Path, "rmdir", real_rmdir)

    target.mkdir(exist_ok=True)
    (target / "payload.txt").write_text("payload", encoding="utf-8")

    def _fail_root_rmdir(self):
        if self == target:
            raise OSError("target rmdir failed")
        return real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", _fail_root_rmdir)
    assert tmp_cleanup.safe_remove_tree(target, root) is False

    monkeypatch.setattr(Path, "rmdir", real_rmdir)

    artifact = root / "artifact.txt"
    artifact.write_text("payload", encoding="utf-8")
    real_unlink = Path.unlink
    monkeypatch.setattr(
        tmp_cleanup.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
    )

    def _fail_tmp_unlink(self, *args, **kwargs):
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
