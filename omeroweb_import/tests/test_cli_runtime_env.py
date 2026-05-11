"""Tests for OMERO CLI runtime environment handling."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from omeroweb_import.services.omero import connection_service, import_service
from omeroweb_import.services.import_management import workflow_service
from omeroweb_import.strings import errors
from omeroweb_import.views import core_functions


def test_run_omero_cli_sets_writable_home_and_cache(tmp_path: Path, monkeypatch):
    """Verify the run OMERO CLI sets writable home and cache execution contract.

    Inputs: `tmp_path` (Path) temporary path fixture, `monkeypatch` pytest monkeypatch
    fixture. Output: `CompletedProcess` result.
    """
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    captured = {}

    def fake_run(*args, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `CompletedProcess` result.
        """
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        )

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
    """Verify the run OMERO CLI merges existing ice config execution contract.

    Inputs: `tmp_path` (Path) temporary path fixture, `monkeypatch` pytest monkeypatch
    fixture. Output: `CompletedProcess` result.
    """
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    base_config = tmp_path / "base-ice.config"
    base_config.write_text("Ice.Default.Router=test-router\n", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setenv("ICE_CONFIG", str(base_config))

    captured = {}

    def fake_run(*args, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `CompletedProcess` result.
        """
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr(core_functions.subprocess, "run", fake_run)

    core_functions._run_omero_cli(["omero", "import", "file.tif"], timeout=123)

    merged_config = Path(captured["kwargs"]["env"]["ICE_CONFIG"])
    assert merged_config.read_text(encoding="utf-8") == (
        "Ice.Default.Router=test-router\nomero.keep_alive=30\n"
    )


def test_get_import_timeout_seconds_defaults_to_24_hours(monkeypatch):
    """Verify get import timeout seconds defaults to 24 hours.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get import timeout seconds defaults to 24 hours.
    """
    monkeypatch.delenv(core_functions.IMPORT_TIMEOUT_SECONDS_ENV, raising=False)

    assert core_functions._get_import_timeout_seconds() == 24 * 60 * 60


def test_get_local_import_scan_timeout_seconds_defaults_to_2_hours(monkeypatch):
    """Verify get local import scan timeout seconds defaults to 2 hours.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get local import scan timeout seconds defaults to 2 hours.
    """
    monkeypatch.delenv(
        core_functions.LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_ENV, raising=False
    )

    assert core_functions._get_local_import_scan_timeout_seconds() == 2 * 60 * 60


def test_import_file_adds_scan_depth_to_cli_command(monkeypatch):
    """Verify the import file adds scan depth to CLI command execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in import file adds scan depth to CLI command integration.
    """
    captured = {}
    sample_path = Path(tempfile.gettempdir()) / "sample.czi"

    def fake_run(cmd, timeout=None):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `cmd`, `timeout` timeout seconds. Output: `CompletedProcess` result.
        """
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="ok", stderr=""
        )

    monkeypatch.setattr(core_functions, "_run_omero_cli", fake_run)

    ok, _stdout, _stderr = core_functions._import_file(
        None,
        "session-key",
        "omeroserver",
        4064,
        sample_path,
        dataset_id=17,
    )

    assert ok is True
    depth_index = captured["cmd"].index("--depth")
    assert captured["cmd"][depth_index + 1] == str(
        core_functions.OMERO_IMPORT_SCAN_DEPTH
    )
    assert captured["cmd"][-3:] == ["-d", "17", str(sample_path)]


def test_compatibility_check_adds_scan_depth_to_cli_command(
    tmp_path: Path, monkeypatch
):
    """Verify the compatibility check adds scan depth to CLI command execution contract.

    Inputs: `tmp_path` (Path) temporary path fixture, `monkeypatch` pytest monkeypatch
    fixture. Output: `CompletedProcess` result.
    """
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    file_path = tmp_path / "nested" / "sample.czi"
    file_path.parent.mkdir()
    file_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    captured = {}

    def fake_run(cmd, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `CompletedProcess` result.
        """
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
    assert captured["cmd"][depth_index + 1] == str(
        core_functions.OMERO_IMPORT_SCAN_DEPTH
    )
    assert captured["cmd"][:4] == [core_functions.OMERO_CLI, "import", "-f", "--depth"]
    assert captured["cmd"][-1] == str(file_path)


def test_run_local_import_scan_uses_depth_10_and_writable_runtime_dirs(
    tmp_path: Path, monkeypatch
):
    """Verify run local import scan uses depth 10 and writable runtime dirs.

    Inputs: `tmp_path` (Path) temporary path fixture, `monkeypatch` pytest monkeypatch
    fixture. Output: `CompletedProcess` result.
    """
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    file_path = tmp_path / "nested" / "sample.zarr"
    file_path.parent.mkdir()
    file_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    captured = {}

    def fake_run(cmd, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `CompletedProcess` result.
        """
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core_functions.subprocess, "run", fake_run)

    result = core_functions._run_local_import_scan(file_path)

    assert result.returncode == 0
    assert captured["cmd"][:4] == [core_functions.OMERO_CLI, "import", "-f", "--depth"]
    depth_index = captured["cmd"].index("--depth")
    assert captured["cmd"][depth_index + 1] == str(
        core_functions.OMERO_IMPORT_SCAN_DEPTH
    )
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
    """Verify the service import file adds scan depth to CLI command execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in service import file adds scan depth to CLI command integration.
    """
    sample_path = Path(tempfile.gettempdir()) / "sample.czi"
    for module in (connection_service, import_service):
        captured = {}

        def fake_run(cmd, *args, _captured=captured, **kwargs):
            """Simulate run so the surrounding test controls that dependency.

            Inputs: `cmd`, `*args` positional arguments, `_captured`, `**kwargs` keyword
            arguments. Output: `CompletedProcess` result.
            """
            _captured["cmd"] = cmd
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="ok", stderr=""
            )

        monkeypatch.setattr(module, "_run_omero_cli", fake_run)

        ok, _stdout, _stderr = module._import_file(
            None,
            "session-key",
            "omeroserver",
            4064,
            sample_path,
            dataset_id=17,
        )

        assert ok is True
        depth_index = captured["cmd"].index("--depth")
        assert captured["cmd"][depth_index + 1] == str(
            core_functions.OMERO_IMPORT_SCAN_DEPTH
        )
        assert captured["cmd"][-3:] == ["-d", "17", str(sample_path)]


def test_service_compatibility_check_adds_scan_depth_to_cli_command(
    tmp_path: Path, monkeypatch
):
    """Verify the service compatibility check adds scan depth to CLI command execution contract.

    Inputs: `tmp_path` (Path) temporary path fixture, `monkeypatch` pytest monkeypatch
    fixture. Output: `CompletedProcess` result.
    """
    file_path = tmp_path / "nested" / "sample.czi"
    file_path.parent.mkdir()
    file_path.write_text("dummy", encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        """Simulate run so the surrounding test controls that dependency.

        Inputs: `cmd`, `**kwargs` keyword arguments. Output: `CompletedProcess` result.
        """
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
    assert captured["cmd"][depth_index + 1] == str(
        core_functions.OMERO_IMPORT_SCAN_DEPTH
    )
    assert captured["cmd"][:4] == [
        workflow_service.OMERO_CLI,
        "import",
        "-f",
        "--depth",
    ]
    assert captured["cmd"][-1] == str(file_path)


def test_classify_import_failure_detects_session_expiry():
    """Verify classify import failure detects session expiry.

    Inputs: import-job fakes. Output: fails on regressions in classify import failure detects session expiry.
    """
    stderr = """
    Proxy keep alive failed.
    java.lang.RuntimeException: Ice.ObjectNotExistException
    operation = "keepAllAlive"
    """

    assert (
        core_functions._classify_import_failure("", stderr)
        == errors.import_session_expired()
    )


def test_classify_import_failure_defaults_to_generic_error():
    """Confirm classify import failure defaults to generic error exposes the expected failure.

    Inputs: import-job fakes. Output: fails on regressions when classify import failure defaults to generic error stops reporting the expected error.
    """
    assert (
        core_functions._classify_import_failure("", "plain failure")
        == errors.import_failed()
    )


def test_classify_import_failure_detects_parent_directory_write_denial():
    """Verify classify import failure detects parent directory write denial.

    Inputs: import-job fakes. Output: fails on regressions in classify import failure detects parent directory write denial.
    """
    stderr = """
    Joined session for import.user@omeroserver:4064. Idle timeout: 10 min. Current group: users_ldap
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
    """Verify classify import failure detects parent directory write denial without metadata.

    Inputs: import-job fakes. Output: fails on regressions in classify import failure detects parent directory write denial without metadata.
    """
    stderr = "No annotate access for parent directory: 227"

    assert core_functions._classify_import_failure("", stderr) == (
        "Import failed because OMERO denied write access to the managed repository "
        "parent directory (directory id 227). This usually means the group-level "
        "repository folder already exists but is owned by a different user."
    )


def test_classify_import_failure_detects_path_permission_denial():
    """Verify the classify import failure detects path permission denial safety boundary.

    Inputs: import-job fakes. Output: fails on regressions when classify import failure detects path permission denial accepts unsafe input.
    """
    stderr = """
    Traceback (most recent call last):
      File "/opt/omero/web/venv-3.12/lib64/python3.12/site-packages/zarr/storage/_local.py", line 171, in _open
        if not self.root.exists():
    PermissionError: [Errno 13] Permission denied: '/OMERO/ManagedRepository/users/test/2026-04-10/17-28-10/sample.zarr'
    """

    assert core_functions._classify_import_failure("", stderr) == (
        errors.import_path_not_readable()
    )


def test_classify_import_failure_does_not_treat_generic_object_not_exist_as_session_expiry():
    """Verify classify import failure does not treat generic object not exist as session expiry.

    Inputs: import-job fakes. Output: fails on regressions in classify import failure does not treat generic object not exist as session expiry.
    """
    stderr = """
    java.lang.RuntimeException: Failure response on import!
    Caused by: Ice.ObjectNotExistException
    operation = "findAll"
    """

    assert core_functions._classify_import_failure("", stderr) == errors.import_failed()
