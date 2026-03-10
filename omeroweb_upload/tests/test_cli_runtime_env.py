"""Tests for OMERO CLI runtime environment handling."""
from __future__ import annotations

import subprocess
from pathlib import Path

from omeroweb_upload.strings import errors
from omeroweb_upload.views import core_functions


def test_run_omero_cli_sets_writable_home_and_cache(tmp_path: Path, monkeypatch):
    """CLI calls should run with HOME/XDG_CACHE_HOME under upload root."""
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(core_functions.subprocess, "run", fake_run)

    result = core_functions._run_omero_cli(["omero", "import", "file.tif"], timeout=123)

    assert result.returncode == 0

    env = captured["kwargs"]["env"]
    expected_home = upload_root / ".omero-cli-home"
    expected_cache = expected_home / ".cache"
    expected_ice_config = expected_home / "omero-cli-ice.config"

    assert captured["kwargs"]["timeout"] == 123
    assert env["HOME"] == str(expected_home)
    assert env["XDG_CACHE_HOME"] == str(expected_cache)
    assert env["ICE_CONFIG"] == str(expected_ice_config)
    assert expected_home.is_dir()
    assert expected_cache.is_dir()
    assert expected_ice_config.read_text(encoding="utf-8") == "omero.keep_alive=30\n"


def test_run_omero_cli_merges_existing_ice_config(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    base_config = tmp_path / "base-ice.config"
    base_config.write_text("Ice.Default.Router=test-router\n", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setenv("ICE_CONFIG", str(base_config))

    captured = {}

    def fake_run(*args, **kwargs):
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(core_functions.subprocess, "run", fake_run)

    core_functions._run_omero_cli(["omero", "import", "file.tif"], timeout=123)

    merged_config = Path(captured["kwargs"]["env"]["ICE_CONFIG"])
    assert merged_config.read_text(encoding="utf-8") == (
        "Ice.Default.Router=test-router\n"
        "omero.keep_alive=30\n"
    )


def test_classify_import_failure_detects_session_expiry():
    stderr = """
    Proxy keep alive failed.
    java.lang.RuntimeException: Ice.ObjectNotExistException
    operation = "keepAllAlive"
    """

    assert core_functions._classify_import_failure("", stderr) == errors.import_session_expired()


def test_classify_import_failure_defaults_to_generic_error():
    assert core_functions._classify_import_failure("", "plain failure") == errors.import_failed()
