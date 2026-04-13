from __future__ import annotations

from omero_plugin_common import tmp_utils


def test_get_plugin_tmp_dir_is_non_mutating_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-import")

    path = tmp_utils.get_plugin_tmp_dir("jobs")

    assert path == tmp_path / "omeroweb-import" / "jobs"
    assert path.exists() is False


def test_get_plugin_tmp_dir_creates_tree_only_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-tools")

    path = tmp_utils.get_plugin_tmp_dir("jobs", create=True)

    assert path == tmp_path / "omeroweb-tools" / "jobs"
    assert path.is_dir()
