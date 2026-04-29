from __future__ import annotations

import pytest

from omero_plugin_common import tmp_utils


def test_get_plugin_tmp_dir_is_non_mutating_by_default(tmp_path, monkeypatch):
    """Verify test get plugin tmp dir is non mutating by de behavior."""
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-import")

    path = tmp_utils.get_plugin_tmp_dir("jobs")

    assert path == tmp_path / "omeroweb-import" / "jobs"
    assert path.exists() is False


def test_get_plugin_tmp_dir_creates_tree_only_when_requested(tmp_path, monkeypatch):
    """Verify test get plugin tmp dir creates tree only whe behavior."""
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-tools")

    path = tmp_utils.get_plugin_tmp_dir("jobs", create=True)

    assert path == tmp_path / "omeroweb-tools" / "jobs"
    assert path.is_dir()


def test_get_plugin_tmp_dir_rejects_unsafe_components(tmp_path, monkeypatch):
    """Verify test get plugin tmp dir rejects unsafe compon behavior."""
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "../escape")

    with pytest.raises(ValueError, match="plugin temporary directory"):
        tmp_utils.get_plugin_tmp_dir("jobs")

    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-tools")
    for unsafe_subdir in ("..", "bad\0name"):
        with pytest.raises(ValueError, match="temporary subdirectory"):
            tmp_utils.get_plugin_tmp_dir(unsafe_subdir)
