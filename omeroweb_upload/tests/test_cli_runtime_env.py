"""Tests for OMERO CLI runtime environment handling."""
from __future__ import annotations

import subprocess
from pathlib import Path

from omeroweb_upload.views import core_functions


def test_run_omero_cli_sets_writable_home_and_cache(tmp_path: Path, monkeypatch):
    """CLI calls should run with HOME/XDG_CACHE_HOME under upload root."""
    upload_root = tmp_path / "upload-root"

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

    assert captured["kwargs"]["timeout"] == 123
    assert env["HOME"] == str(expected_home)
    assert env["XDG_CACHE_HOME"] == str(expected_cache)
    assert expected_home.is_dir()
    assert expected_cache.is_dir()
