"""Regression coverage for runtime-package analysis, independent of the carrier."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools import scan_prebuilt_runtime_images as scanner


@pytest.mark.parametrize("exit_code", [0, 7])
def test_real_scanner_process_keeps_public_and_private_output_separate(
    tmp_path, exit_code
):
    """Exercise the subprocess boundary with real byte streams and exit statuses.

    Inputs: temporary child process. Output: verifies captured output and private logs.
    """
    source = "\n".join(
        (
            "import sys",
            "print('command output', flush=True)",
            "print('command diagnostic', file=sys.stderr, flush=True)",
            f"sys.exit({exit_code})",
        )
    )
    log = tmp_path / "scan.log"
    arguments = ["-c", source]
    if exit_code:
        with pytest.raises(RuntimeError, match="inspect the private scan log"):
            scanner._run(sys.executable, arguments, env=dict(os.environ), log=log)
        expected = b"command diagnostic\ncommand output\n"
    else:
        result = scanner._run(sys.executable, arguments, env=dict(os.environ), log=log)
        assert result == "command output\n"
        expected = b"command diagnostic\n"
    assert log.read_bytes() == expected


@pytest.mark.parametrize("timeout", [False, True])
@pytest.mark.parametrize("output", [None, b"private scanner detail\n"])
def test_scanner_failures_preserve_output_only_in_private_log(
    monkeypatch, tmp_path, timeout, output
):
    """Keep scanner diagnostics without disclosing them in public failure text.

    Inputs: failed or timed-out command output. Output: verifies private diagnostics.
    """

    def fail(arguments, **kwargs):
        """Inputs: scanner invocation. Output: writes stderr and raises its failure."""
        kwargs["stderr"].write(b"private stderr\n")
        if timeout:
            raise subprocess.TimeoutExpired(arguments, 1800, output=output)
        raise subprocess.CalledProcessError(1, arguments, output=output)

    monkeypatch.setattr(scanner.subprocess, "run", fail)
    log = tmp_path / "scan.log"
    with pytest.raises(RuntimeError, match="inspect the private scan log") as error:
        scanner._run("/usr/bin/docker", ["scout", "sbom"], env={}, log=log)
    assert log.read_bytes() == b"private stderr\n" + (output or b"")
    assert "private scanner detail" not in str(error.value)
    assert "private stderr" not in str(error.value)


def _sbom():
    """Inputs: none. Output: a minimal native Scout software-package fixture."""
    return {
        "descriptor": {"name": "docker-scout", "version": "1.24.0"},
        "artifacts": [
            {
                "name": "example",
                "version": "1.0",
                "type": "pypi",
                "purl": "pkg:pypi/example@1.0",
            }
        ],
    }


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {**_sbom(), "descriptor": None},
        {**_sbom(), "descriptor": {"name": "another-tool"}},
        {**_sbom(), "artifacts": []},
        {**_sbom(), "artifacts": [None]},
        {**_sbom(), "artifacts": [{"name": "file"}]},
        {**_sbom(), "artifacts": [{"name": "file", "purl": "file://image"}]},
        {**_sbom(), "artifacts": [{"name": "file", "purl": 42}]},
    ],
)
def test_empty_or_nonsoftware_inventory_fails(document):
    """Inputs: invalid native documents. Output: rejects missing package coverage."""
    with pytest.raises(ValueError):
        scanner.package_count(document)


def test_native_scout_inventory_is_accepted_without_lossy_conversion():
    """Inputs: native package inventory. Output: counts each unmodified artifact."""
    document = _sbom()
    document["artifacts"].append({"name": "source", "type": "file"})
    assert scanner.package_count(document) == 2


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {"version": "2.1.0", "runs": []},
        {"version": "2.1.0", "runs": [{}]},
        {"version": "2.1.0", "runs": [{"results": [None]}]},
        {
            "version": "2.1.0",
            "runs": [{"results": [], "invocations": [{"executionSuccessful": False}]}],
        },
    ],
)
def test_incomplete_analysis_is_not_a_clean_report(document):
    """Inputs: incomplete SARIF documents. Output: asserts coverage validation fails."""
    with pytest.raises(ValueError):
        scanner.vulnerability_count(document)


def test_every_required_image_is_accounted_for_and_identical_images_scan_once(
    monkeypatch, tmp_path
):
    """The immutable image ID, not the carrier or an arbitrary tag, is analyzed.

    Inputs: three references to two image fixtures. Output: asserts complete coverage.
    """
    first = "sha256:" + "a" * 64
    second = "sha256:" + "b" * 64
    ids = {"example/web:1": first, "example/worker:1": first, "example/db:2": second}
    calls = []
    scratch_paths = []

    def run(_docker, arguments, *, env, log):
        """Inputs: Docker command. Output: fixture identity or generated analysis file."""
        calls.append(arguments)
        if arguments[:2] == ["image", "inspect"]:
            return ids[arguments[-1]]
        assert env["DOCKER_SCOUT_CACHE_FORMAT"] == "tar"
        scratch = Path(env["TMPDIR"])
        assert scratch.parent == tmp_path.resolve()
        assert env["DOCKER_SCOUT_CACHE_DIR"] == str(scratch)
        assert scratch.is_dir() and scratch.stat().st_mode & 0o777 == 0o700
        scratch_paths.append(scratch)
        output = Path(arguments[arguments.index("--output") + 1])
        if arguments[1] == "sbom":
            assert arguments[arguments.index("--format") + 1] == "json"
            assert output.name.endswith(".scout.json")
            assert arguments[-1] in {f"local://{first}", f"local://{second}"}
            document = _sbom()
        else:
            assert arguments[-1].startswith("sbom://")
            document = {
                "version": "2.1.0",
                "runs": [{"results": [{"ruleId": "TEST-FINDING"}]}],
            }
        output.write_text(json.dumps(document))
        return ""

    monkeypatch.setattr(scanner.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(scanner, "_run", run)
    summary = scanner.scan_images(list(ids), tmp_path)
    assert summary["inventory"] == ids
    assert len(summary["images"]) == 2
    assert sum(call[:2] == ["scout", "sbom"] for call in calls) == 2
    assert all(
        row["packages"] == 1 and row["vulnerabilities"] == 1
        for row in summary["images"].values()
    )
    assert json.loads((tmp_path / "coverage.json").read_text()) == summary
    assert scratch_paths and all(not path.exists() for path in scratch_paths)


def test_failed_image_analysis_cleans_only_its_output_local_scratch(
    monkeypatch, tmp_path
):
    """Large image scratch belongs on the selected output filesystem, not global tmp.

    Inputs: a failed scanner and unrelated output content. Output: private scratch removed.
    """
    unrelated = tmp_path / "operator-artifact"
    unrelated.write_text("retain", encoding="utf-8")
    scratch_paths = []

    def fail(_docker, arguments, *, env, log):
        """Return a stable image identity, then fail after creating scratch content.

        Inputs: Docker invocation. Output: image ID or an explicit scanner failure.
        """
        if arguments[:2] == ["image", "inspect"]:
            return "sha256:" + "a" * 64
        scratch = Path(env["TMPDIR"])
        assert scratch.parent == tmp_path.resolve()
        (scratch / "partial-layer").write_text("incomplete", encoding="utf-8")
        scratch_paths.append(scratch)
        raise RuntimeError("Scanner failed")

    monkeypatch.setattr(scanner.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(scanner, "_run", fail)
    with pytest.raises(RuntimeError, match="Scanner failed"):
        scanner.scan_images(["example/web:1"], tmp_path)
    assert scratch_paths and all(not path.exists() for path in scratch_paths)
    assert unrelated.read_text(encoding="utf-8") == "retain"


def test_invalid_inventory_and_missing_docker_fail(monkeypatch, tmp_path):
    """Inputs: invalid image lists and absent CLI. Output: asserts explicit failure."""
    for images in ([], [""], ["-option"], ["two images"]):
        with pytest.raises(ValueError):
            scanner.scan_images(images, tmp_path)
    monkeypatch.setattr(scanner.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError):
        scanner.scan_images(["example/web:1"], tmp_path)
