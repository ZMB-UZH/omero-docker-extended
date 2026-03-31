from __future__ import annotations

import os

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
