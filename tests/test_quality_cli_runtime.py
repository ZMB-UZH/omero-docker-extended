"""Native quality-tool entrypoints must preserve inventories and failing exits."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tools import mypy_check, vulture_check, run_agent_skill_smoke
from tools import prepare_ci_compose_environment as ci_environment


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["api_servers", "logo_context"])
@pytest.mark.parametrize("mode", ["no_argument", "wrong_source", "missing_import"])
def test_build_patch_cli_rejects_changed_upstream_without_writing(tmp_path, name, mode):
    """Inputs: incompatible upstream source or invalid CLI. Output: actionable failure with identical original bytes."""
    script = ROOT / "docker" / f"patch_omeroweb_{name}.py"
    constants = runpy.run_path(str(script))
    source = tmp_path / "upstream.py"
    before = (
        constants["OLD_API_SERVERS_BLOCK"]
        if name == "api_servers" and mode == "missing_import"
        else "# preserve this unrecognized upstream\n"
    )
    source.write_text(before)
    arguments = [] if mode == "no_argument" else [str(source)]
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    expected = (
        "usage:"
        if mode == "no_argument"
        else "import block not found"
        if name == "api_servers" and mode == "missing_import"
        else "block not found"
    )
    assert expected in result.stderr
    assert source.read_text() == before


@pytest.mark.parametrize(
    "relative,arguments,expected",
    [
        (
            "docker/patch_omeroweb_webgateway.py",
            ["fixture.py"],
            "Unrecognized OMERO.web",
        ),
        ("tools/prepare_quota_directories.py", [".", "-1"], "valid nonnegative GID"),
        ("tools/lint_docs_structure.py", ["--repo-root", "."], "ERROR:"),
        ("startup/dropbox_user_dir_sync.py", ["--help"], "usage:"),
        ("tools/regression_guard.py", ["selfcheck"], ""),
    ],
)
def test_native_cli_reports_invalid_input_without_modifying_existing_files(
    tmp_path, relative, arguments, expected
):
    """Inputs: actual CLI and controlled invalid source/configuration. Output: explicit status and unchanged user fixture."""
    source = tmp_path / "fixture.py"
    source.write_text("# original\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / relative), *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    success = arguments in (["--help"], ["selfcheck"])
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert expected in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == [source]
    assert source.read_text() == "# original\n"


def test_runtime_scanner_cli_refuses_empty_inventory(tmp_path):
    """Inputs: empty image file. Output: no scanner process or misleading coverage receipt."""
    inventory = tmp_path / "images.txt"
    inventory.write_text("")
    output = tmp_path / "analysis"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/scan_prebuilt_runtime_images.py"),
            "--required-images-file",
            str(inventory),
            "--output-dir",
            str(output),
        ],
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert (
        result.returncode != 0 and "nonempty runtime image inventory" in result.stderr
    )
    assert not output.exists()


@pytest.fixture
def quality_repository(tmp_path):
    """Inputs: private directory. Output: isolated real Git inventory and tool configuration."""
    git = shutil.which("git")
    assert git, "Native inventory tests require Git"
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "mypy.ini").write_text("[mypy]\nstrict = True\n")
    (tmp_path / ".gitignore").write_text("ignored.py\n.mypy_cache/\n")
    for relative in (
        "source.py",
        "new_source.py",
        "ignored.py",
        "tests/test_case.py",
        "plugin/tests/test_case.py",
        "third_party/dependency.py",
        "docs/conf.py",
        ".private/hook.py",
        "conftest.py",
        "test_root.py",
        "root_test.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value: int = 1\nprint(value)\n")
    subprocess.run([git, "add", "source.py"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize("module", [mypy_check, vulture_check])
@pytest.mark.parametrize("path", ["", ".", "/", "..", "././", "file", "file.py", ".py"])
def test_target_filter_handles_empty_paths_before_indexing_parts(module, path):
    """Inputs: real pathlib edge cases. Output: only a named Python source is admitted."""
    predicate = getattr(module, "is_mypy_target", None) or module.is_vulture_target
    assert predicate(PurePosixPath(path)) == (path == "file.py")


@pytest.mark.parametrize("module", [mypy_check, vulture_check])
def test_quality_inventory_fails_without_git_or_production_files(
    module, tmp_path, monkeypatch
):
    """Inputs: missing executable or test-only inventory. Output: explicit failure, never an empty pass."""
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="not available in PATH"):
        module.resolve_required_executable("git")
    monkeypatch.setattr(module, "_run_git", lambda *_args: "tests/test_only.py\0")
    listing = getattr(module, "list_mypy_targets", None) or module.list_vulture_targets
    with pytest.raises(RuntimeError, match="No production Python files"):
        listing(tmp_path)


@pytest.mark.parametrize("name", ["mypy", "vulture"])
def test_quality_cli_lists_tracked_and_new_files_without_running_tool(
    quality_repository, name
):
    """Inputs: real Git index plus untracked sources. Output: complete, sorted first-party inventory."""
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / f"{name}_check.py"),
            "--repo-root",
            str(quality_repository),
            "--print-files",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["new_source.py", "source.py"]
    assert not result.stderr


@pytest.mark.parametrize("name", ["mypy", "vulture"])
@pytest.mark.parametrize("invalid", [False, True])
def test_quality_cli_returns_native_tool_result(quality_repository, name, invalid):
    """Inputs: real valid and invalid sources. Output: actual type/dead-code finding controls exit."""
    source = quality_repository / "source.py"
    if invalid:
        source.write_text(
            'value: int = "invalid assignment"\nprint(value)\n'
            if name == "mypy"
            else 'def used() -> int:\n    return 1\n    print("unreachable")\nprint(used())\n'
        )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / f"{name}_check.py"),
            "--repo-root",
            str(quality_repository),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert (result.returncode != 0) == invalid, result.stdout + result.stderr
    if invalid:
        assert (
            "Incompatible types" if name == "mypy" else "unreachable code"
        ) in result.stdout


def test_smoke_command_preserves_native_failure(tmp_path, monkeypatch):
    """Inputs: a real failing child process. Output: exact status, correct working directory."""
    monkeypatch.setattr(run_agent_skill_smoke, "REPO_ROOT", tmp_path)
    child = (
        "from pathlib import Path; import sys; "
        "Path('receipt').write_text('ran'); sys.exit(13)"
    )
    assert (
        run_agent_skill_smoke._run_command(
            [
                sys.executable,
                "-c",
                child,
            ]
        )
        == 13
    )
    assert (tmp_path / "receipt").read_text() == "ran"


@pytest.mark.parametrize("failed", [False, True])
def test_smoke_fallback_only_compiles_after_success(tmp_path, monkeypatch, failed):
    """Inputs: nested smoke status. Output: later syntax checks never conceal the initial failure."""
    monkeypatch.setattr(run_agent_skill_smoke, "REPO_ROOT", tmp_path)
    files = (
        "omeroweb_import/tests/test_cli_runtime_env.py",
        "omeroweb_import/tests/test_security_hardening.py",
        "omeroweb_tools/tests/test_tools_module_contracts.py",
        "omeroweb_omp_plugin/tests/test_log_sanitization.py",
    )
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("answer = 42\n")
    runner = Mock(return_value=7 if failed else 0)
    monkeypatch.setattr(run_agent_skill_smoke, "_run_command", runner)
    assert run_agent_skill_smoke.main(["plugin-suite-fallback"]) == (1 if failed else 0)
    runner.assert_called_once()
    assert "--noconftest" in runner.call_args.args[0]
    assert len(list(tmp_path.rglob("*.pyc"))) == (0 if failed else 4)


def test_unknown_smoke_profile_has_actionable_failure():
    """Inputs: unsupported public profile. Output: status 2, not an unexecuted success."""
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_agent_skill_smoke.py"),
            "unknown-profile",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "Unknown smoke profile: unknown-profile" in result.stderr


def test_ci_resolver_checks_its_dependency_postcondition(tmp_path, monkeypatch):
    """Inputs: a faulty resolver returning expansion syntax. Output: no unresolved value reaches Compose."""
    monkeypatch.setattr(
        ci_environment, "resolve_env_references", lambda *_args: "${UNRESOLVED}"
    )
    with pytest.raises(
        ci_environment.CiComposeEnvironmentError, match="Unresolved synthetic"
    ):
        ci_environment._resolve_environment_values(tmp_path, {"VALUE": "input"})


@pytest.mark.parametrize("size", [0, 1024 * 1024 + 37])
def test_archive_writer_cli_preserves_exact_stream_and_count(tmp_path, size):
    """Inputs: empty and multi-chunk binary streams. Output: deterministic gzip plus exact raw size."""
    payload = (bytes(range(256)) * (size // 256 + 1))[:size]
    first = None
    for index in range(2):
        archive, count = tmp_path / f"archive-{index}.gz", tmp_path / f"count-{index}"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/write_prebuilt_runtime_archive.py"),
                "--archive",
                str(archive),
                "--raw-bytes-file",
                str(count),
            ],
            input=payload,
            check=False,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert gzip.decompress(archive.read_bytes()) == payload
        assert count.read_text() == f"{size}\n"
        assert not list(tmp_path.glob(".*.tmp"))
        if first is None:
            first = archive.read_bytes()
        else:
            assert archive.read_bytes() == first


def test_processor_patch_cli_is_idempotent_and_preserves_surrounding_source(tmp_path):
    """Inputs: actual patch command twice. Output: one allowlist extension and stable second output."""
    source = tmp_path / "processor.py"
    initial = (
        'before = True\nallowed = (\n            "OMERO_TMPDIR",\n)\nafter = True\n'
    )
    source.write_text(initial)
    for status in ("patched", "already patched"):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "docker/patch_omero_processor_env.py"),
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().endswith(f"allowlist {status}.")
    patched = source.read_text()
    assert patched == initial.replace(
        '            "OMERO_TMPDIR",\n',
        '            "OMERO_TMPDIR",\n            "OMERO_IMS_EXPORT_DIR",\n'
        '            "CONFIG_omero_managed_dir",\n',
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"runs": [None]},
        {"runs": [{"results": {}}]},
        {"runs": [{"results": [None]}]},
    ],
)
def test_sarif_cli_rejects_structurally_invalid_reports(tmp_path, payload):
    """Inputs: syntactically valid but malformed scanner output. Output: fail closed with reason."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload))
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/sarif_result_guard.py"), str(report)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "ERROR: SARIF result guard" in result.stderr


def test_sarif_cli_caps_diagnostics_without_dropping_findings(tmp_path):
    """Inputs: 23 scanner findings. Output: every finding blocks upload, with bounded diagnostics."""
    report = tmp_path / "findings.json"
    report.write_text(
        json.dumps(
            {"runs": [{"results": [{"ruleId": f"rule-{n}"} for n in range(23)]}]}
        )
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/sarif_result_guard.py"), str(report)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "23 result(s)" in result.stderr and "... and 3 more" in result.stderr
    assert result.stderr.count(" at <unknown-path>:?") == 20
