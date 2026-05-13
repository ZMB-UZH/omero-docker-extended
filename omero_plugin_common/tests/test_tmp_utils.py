from __future__ import annotations

import types

import pytest

from omero_plugin_common import tmp_utils


def test_get_plugin_tmp_dir_is_non_mutating_by_default(tmp_path, monkeypatch):
    """Verify get plugin tmp dir is non mutating by default.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in get plugin tmp dir is non mutating by default.
    """
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-import")

    path = tmp_utils.get_plugin_tmp_dir("jobs")

    assert path == tmp_path / "omeroweb-import" / "jobs"
    assert path.exists() is False


def test_get_plugin_tmp_dir_creates_tree_only_when_requested(tmp_path, monkeypatch):
    """Verify get plugin tmp dir creates tree only when requested.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in get plugin tmp dir creates tree only when requested.
    """
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-tools")

    path = tmp_utils.get_plugin_tmp_dir("jobs", create=True)

    assert path == tmp_path / "omeroweb-tools" / "jobs"
    assert path.is_dir()


def test_get_plugin_tmp_dir_rejects_unsafe_components(tmp_path, monkeypatch):
    """Confirm get plugin tmp dir rejects unsafe components is rejected at the boundary.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in get plugin tmp dir rejects unsafe components.
    """
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))
    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "../escape")

    with pytest.raises(ValueError, match="plugin temporary directory"):
        tmp_utils.get_plugin_tmp_dir("jobs")

    monkeypatch.setattr(tmp_utils, "_detect_caller_plugin", lambda: "omeroweb-tools")
    for unsafe_subdir in ("..", "bad\0name"):
        with pytest.raises(ValueError, match="temporary subdirectory"):
            tmp_utils.get_plugin_tmp_dir(unsafe_subdir)


def test_get_plugin_tmp_dir_accepts_explicit_safe_plugin_namespace(
    tmp_path, monkeypatch
):
    """Verify explicit plugin namespaces avoid runtime stack dependency.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on explicit namespace regressions.
    """
    monkeypatch.setenv(tmp_utils.TMP_PATH_ENV, str(tmp_path))

    path = tmp_utils.get_plugin_tmp_dir(
        "jobs",
        plugin="omero-imaris-connector",
    )

    assert path == tmp_path / "omero-imaris-connector" / "jobs"
    with pytest.raises(ValueError, match="plugin temporary directory"):
        tmp_utils.get_plugin_tmp_dir("jobs", plugin="../escape")


def test_detect_caller_plugin_recognizes_omero_plugin_packages(monkeypatch):
    """Verify plugin tmp namespaces include non-web OMERO plugin packages.

    Inputs: pytest provides `monkeypatch`. Output: fails on namespace regressions.
    """
    frames = [object(), object(), object()]
    modules = {
        frames[0]: types.SimpleNamespace(__name__="omero_plugin_common.tmp_utils"),
        frames[1]: types.SimpleNamespace(__name__="omero_imaris_connector.config"),
        frames[2]: types.SimpleNamespace(__name__="omeroweb_import.utils"),
    }

    monkeypatch.setattr(
        tmp_utils.inspect,
        "stack",
        lambda: [(frame,) for frame in frames],
    )
    monkeypatch.setattr(
        tmp_utils.inspect,
        "getmodule",
        lambda frame: modules[frame],
    )

    assert tmp_utils._detect_caller_plugin() == "omero-imaris-connector"
