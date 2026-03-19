"""Tests for OMERO CLI runtime environment handling."""
from __future__ import annotations

import subprocess
from pathlib import Path

from omeroweb_import.services.omero import connection_service, import_service
from omeroweb_import.services.import_management import workflow_service
from omeroweb_import.strings import errors
from omeroweb_import.views import core_functions


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


def test_get_import_timeout_seconds_defaults_to_24_hours(monkeypatch):
    monkeypatch.delenv(core_functions.IMPORT_TIMEOUT_SECONDS_ENV, raising=False)

    assert core_functions._get_import_timeout_seconds() == 24 * 60 * 60


def test_get_local_import_scan_timeout_seconds_defaults_to_2_hours(monkeypatch):
    monkeypatch.delenv(core_functions.LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_ENV, raising=False)

    assert core_functions._get_local_import_scan_timeout_seconds() == 2 * 60 * 60


def test_import_file_adds_scan_depth_to_cli_command(monkeypatch):
    captured = {}

    def fake_run(cmd, timeout=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(core_functions, "_run_omero_cli", fake_run)

    path = Path("/tmp/sample.czi")
    ok, _stdout, _stderr = core_functions._import_file(
        None,
        "session-key",
        "omeroserver",
        4064,
        path,
        dataset_id=17,
    )

    assert ok is True
    depth_index = captured["cmd"].index("--depth")
    assert captured["cmd"][depth_index + 1] == str(core_functions.OMERO_IMPORT_SCAN_DEPTH)
    assert captured["cmd"][-3:] == ["-d", "17", str(path)]


def test_compatibility_check_adds_scan_depth_to_cli_command(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    file_path = tmp_path / "nested" / "sample.czi"
    file_path.parent.mkdir()
    file_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=f"{file_path}\n",
            stderr="",
        )

    monkeypatch.setattr(core_functions.subprocess, "run", fake_run)

    result = core_functions._check_import_compatibility(
        "session-key",
        "omeroserver",
        4064,
        file_path,
        None,
        "nested/sample.czi",
    )

    assert result["status"] == "compatible"
    depth_index = captured["cmd"].index("--depth")
    assert captured["cmd"][depth_index + 1] == str(core_functions.OMERO_IMPORT_SCAN_DEPTH)
    assert captured["cmd"][:4] == [core_functions.OMERO_CLI, "import", "-f", "--depth"]
    assert captured["cmd"][-1] == str(file_path)


def test_run_local_import_scan_uses_depth_10_and_writable_runtime_dirs(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    file_path = tmp_path / "nested" / "sample.zarr"
    file_path.parent.mkdir()
    file_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core_functions.subprocess, "run", fake_run)

    result = core_functions._run_local_import_scan(file_path)

    assert result.returncode == 0
    assert captured["cmd"][:4] == [core_functions.OMERO_CLI, "import", "-f", "--depth"]
    depth_index = captured["cmd"].index("--depth")
    assert captured["cmd"][depth_index + 1] == str(core_functions.OMERO_IMPORT_SCAN_DEPTH)
    assert captured["cmd"][-1] == str(file_path)
    assert captured["kwargs"]["timeout"] == 2 * 60 * 60

    env = captured["kwargs"]["env"]
    expected_home = upload_root / ".omero-cli-home"
    expected_cache = expected_home / ".cache"

    assert env["HOME"] == str(expected_home)
    assert env["XDG_CACHE_HOME"] == str(expected_cache)
    assert env["OMERODIR"]
    assert expected_home.is_dir()
    assert expected_cache.is_dir()


def test_service_import_file_adds_scan_depth_to_cli_command(monkeypatch):
    for module in (connection_service, import_service):
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(module, "_run_omero_cli", fake_run)

        ok, _stdout, _stderr = module._import_file(
            None,
            "session-key",
            "omeroserver",
            4064,
            Path("/tmp/sample.czi"),
            dataset_id=17,
        )

        assert ok is True
        depth_index = captured["cmd"].index("--depth")
        assert captured["cmd"][depth_index + 1] == "10"
        assert captured["cmd"][-3:] == ["-d", "17", "/tmp/sample.czi"]


def test_service_compatibility_check_adds_scan_depth_to_cli_command(tmp_path: Path, monkeypatch):
    file_path = tmp_path / "nested" / "sample.czi"
    file_path.parent.mkdir()
    file_path.write_text("dummy", encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=f"{file_path}\n",
            stderr="",
        )

    monkeypatch.setattr(workflow_service.subprocess, "run", fake_run)

    result = workflow_service._check_import_compatibility(
        "session-key",
        "omeroserver",
        4064,
        file_path,
        None,
        "nested/sample.czi",
    )

    assert result["status"] == "compatible"
    depth_index = captured["cmd"].index("--depth")
    assert captured["cmd"][depth_index + 1] == "10"
    assert captured["cmd"][:4] == [workflow_service.OMERO_CLI, "import", "-f", "--depth"]
    assert captured["cmd"][-1] == str(file_path)


def test_classify_import_failure_detects_session_expiry():
    stderr = """
    Proxy keep alive failed.
    java.lang.RuntimeException: Ice.ObjectNotExistException
    operation = "keepAllAlive"
    """

    assert core_functions._classify_import_failure("", stderr) == errors.import_session_expired()


def test_classify_import_failure_defaults_to_generic_error():
    assert core_functions._classify_import_failure("", "plain failure") == errors.import_failed()


def test_classify_import_failure_detects_parent_directory_write_denial():
    stderr = """
    Joined session for e.mitridis@omeroserver:4064. Idle timeout: 10 min. Current group: users_ldap
    Error on import: No annotate access for parent directory: 227
    omero.SecurityViolation: null
    """

    assert core_functions._classify_import_failure("", stderr) == (
        "Import failed because OMERO denied write access to the managed repository "
        "parent directory for group 'users_ldap' (directory id 227). This usually "
        "means the group-level repository folder already exists but is owned by a "
        "different user."
    )


def test_classify_import_failure_detects_parent_directory_write_denial_without_metadata():
    stderr = "No annotate access for parent directory: 227"

    assert core_functions._classify_import_failure("", stderr) == (
        "Import failed because OMERO denied write access to the managed repository "
        "parent directory (directory id 227). This usually means the group-level "
        "repository folder already exists but is owned by a different user."
    )


def test_classify_import_failure_does_not_treat_generic_object_not_exist_as_session_expiry():
    stderr = """
    java.lang.RuntimeException: Failure response on import!
    Caused by: Ice.ObjectNotExistException
    operation = "findAll"
    """

    assert core_functions._classify_import_failure("", stderr) == errors.import_failed()
