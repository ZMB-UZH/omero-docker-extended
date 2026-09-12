"""Real artifact, Git snapshot, and unmodified-report contracts for the shared scanner."""

from __future__ import annotations

import configparser
import csv
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

import pytest

from tools import devskim_gate as gate


def make_package(path: Path, members: dict[str, bytes] | None = None) -> Path:
    """Create a small real NuGet-style archive for boundary tests.

    Inputs: output path and optional archive members. Output: created ZIP path.
    """
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in (
            members or {"tools/net8.0/any/devskim.dll": b"fixture"}
        ).items():
            archive.writestr(name, value)
    return path


def package_settings(path: Path) -> dict[str, str]:
    """Derive a deterministic artifact fingerprint without secret-like test literals.

    Inputs: fixture package. Output: settings with a matching full content digest.
    """
    settings = gate.read_tooling(gate.REPO_ROOT / "tools" / "devskim_tooling.ini")
    settings["package_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return settings


def make_repo(path: Path) -> Path:
    """Initialize a real repository without creating commits or borrowing identities.

    Inputs: owned test directory. Output: Git repository with tracked and ignored files.
    """
    path.mkdir()
    git = gate.executable("git")
    subprocess.run([git, "init", "--quiet", str(path)], check=True)
    (path / ".gitignore").write_text("private.env\n.cache/\n", encoding="utf-8")
    (path / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    (path / "removed.py").write_text("VALUE = 0\n", encoding="utf-8")
    subprocess.run(
        [git, "add", ".gitignore", "tracked.py", "removed.py"], cwd=path, check=True
    )
    (path / "removed.py").unlink()
    (path / "new.py").write_text("VALUE = 2\n", encoding="utf-8")
    (path / "private.env").write_text(
        "PRIVATE_FIXTURE=not-for-scanning\n", encoding="utf-8"
    )
    return path


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", "latest"),
        ("version", "1.0;command"),
        ("framework", "../net8.0"),
        ("package_sha256", "incorrect"),
        ("runtime_image", "image:latest"),
        ("extra", "unexpected"),
    ],
)
def test_tooling_rejects_invalid_or_floating_pins(tmp_path, key, value):
    """Reject unreviewed configuration before downloads or subprocesses.

    Inputs: invalid tooling field. Output: explicit configuration failure.
    """
    config = configparser.ConfigParser(interpolation=None)
    config["devskim"] = gate.read_tooling(
        gate.REPO_ROOT / "tools" / "devskim_tooling.ini"
    )
    config["devskim"][key] = value
    path = tmp_path / "tooling.ini"
    with path.open("w", encoding="utf-8") as stream:
        config.write(stream)
    with pytest.raises(ValueError, match="immutable"):
        gate.read_tooling(path)


@pytest.mark.parametrize(
    "text",
    ["", "[other]\nvalue = value\n", "[DEFAULT]\nvalue = inherited\n[devskim]\n"],
)
def test_tooling_requires_explicit_section(tmp_path, text):
    """Reject missing configuration and inherited overrides.

    Inputs: malformed section layout. Output: closed manifest validation failure.
    """
    path = tmp_path / "tooling.ini"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="explicit"):
        gate.read_tooling(path)


def test_verified_cache_avoids_network_and_rejects_changed_content(
    tmp_path, monkeypatch
):
    """Reuse only exact cached bytes and never silently replace corrupt artifacts.

    Inputs: real ZIP cache, then altered bytes. Output: reuse followed by rejection.
    """
    package = make_package(tmp_path / "microsoft.cst.devskim.cli.1.0.90.nupkg")
    settings = package_settings(package)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Unexpected network request"),
    )
    assert gate.verified_package(settings, tmp_path) == package
    package.write_bytes(b"altered fixture")
    with pytest.raises(ValueError, match="checksum"):
        gate.verified_package(settings, tmp_path)
    assert package.read_bytes() == b"altered fixture"


def test_download_is_checked_before_cache_publication(tmp_path, monkeypatch):
    """Publish a download only after the expected checksum has been verified.

    Inputs: simulated curl writing a real NuGet archive. Output: validated cache artifact.
    """
    fixture = make_package(tmp_path / "fixture.nupkg")
    settings = package_settings(fixture)
    commands = []

    def download(command, **kwargs):
        """Supply deterministic download bytes through the real publication boundary.

        Inputs: curl command. Output: completed download process fixture.
        """
        commands.append(command)
        shutil.copyfile(fixture, command[command.index("--output") + 1])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(gate.subprocess, "run", download)
    monkeypatch.setattr(gate, "executable", lambda name: f"/usr/bin/{name}")
    cache = tmp_path / "cache"
    package = gate.verified_package(settings, cache)
    assert package.read_bytes() == fixture.read_bytes()
    assert commands[0][-1].startswith("https://api.nuget.org/v3-flatcontainer/")
    assert commands[0][commands[0].index("--proto") + 1] == "=https"
    assert "--max-filesize" in commands[0]
    assert set(cache.iterdir()) == {package}


def test_cache_rejects_dangling_symlink_without_a_download(tmp_path, monkeypatch):
    """Do not overwrite even a dangling redirected cache entry.

    Inputs: missing symlink target in an owned cache. Output: rejection before curl.
    """
    settings = gate.read_tooling(gate.REPO_ROOT / "tools" / "devskim_tooling.ini")
    package = tmp_path / f"microsoft.cst.devskim.cli.{settings['version']}.nupkg"
    package.symlink_to(tmp_path / "missing-target")
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Unexpected download"),
    )
    with pytest.raises(ValueError, match="symlinks"):
        gate.verified_package(settings, tmp_path)
    assert package.is_symlink()


@pytest.mark.parametrize("failure", ["transfer", "checksum"])
def test_failed_download_never_publishes_or_leaves_partial_files(
    tmp_path, monkeypatch, failure
):
    """Keep incomplete and corrupted downloads outside the reusable artifact cache.

    Inputs: failed transfer or untrusted downloaded bytes. Output: empty cache and failure.
    """
    settings = gate.read_tooling(gate.REPO_ROOT / "tools" / "devskim_tooling.ini")

    def download(command, **kwargs):
        """Write a partial payload and optionally fail the transport.

        Inputs: curl invocation. Output: invalid download or transport exception.
        """
        Path(command[command.index("--output") + 1]).write_bytes(b"incomplete")
        if failure == "transfer":
            raise subprocess.CalledProcessError(18, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(gate.subprocess, "run", download)
    monkeypatch.setattr(gate, "executable", lambda name: f"/usr/bin/{name}")
    cache = tmp_path / "cache"
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        gate.verified_package(settings, cache)
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("case", ["checksum", "symlink", "size"])
def test_package_validation_precedes_archive_processing(tmp_path, monkeypatch, case):
    """Reject altered, oversized, and redirected package inputs.

    Inputs: invalid package variants. Output: no accepted archive payload.
    """
    package = make_package(tmp_path / "fixture.nupkg")
    expected = hashlib.sha256(package.read_bytes()).hexdigest()
    if case == "checksum":
        package.write_bytes(b"changed")
    elif case == "symlink":
        link = tmp_path / "link.nupkg"
        link.symlink_to(package)
        package = link
    else:
        monkeypatch.setattr(gate, "MAX_PACKAGE_BYTES", 1)
    with pytest.raises(ValueError):
        gate.verify_package_digest(package, expected)


def test_extraction_selects_only_the_reviewed_framework(tmp_path):
    """Preserve exact engine bytes without importing another framework's payload.

    Inputs: real multi-framework package. Output: exact selected runtime files.
    """
    package = make_package(
        tmp_path / "fixture.nupkg",
        {
            "tools/net8.0/any/devskim.dll": b"correct",
            "tools/net10.0/any/devskim.dll": b"different",
        },
    )
    engine = tmp_path / "engine"
    gate.extract_engine(package, "net8.0", engine)
    assert (engine / "devskim.dll").read_bytes() == b"correct"
    assert set(engine.iterdir()) == {engine / "devskim.dll"}


@pytest.mark.parametrize(
    "member", ["../escape", "/absolute", "sub/../../escape", "sub\\escape"]
)
def test_extraction_rejects_unsafe_paths(tmp_path, member):
    """Prevent archive member paths from crossing the private extraction boundary.

    Inputs: hostile member names. Output: closed failure without escaped files.
    """
    package = make_package(
        tmp_path / "fixture.nupkg", {f"tools/net8.0/any/{member}": b"invalid"}
    )
    with pytest.raises(ValueError, match="invalid runtime member"):
        gate.extract_engine(package, "net8.0", tmp_path / "engine")
    assert not (tmp_path / "escape").exists()


def test_extraction_rejects_links_and_expansion_limit(tmp_path, monkeypatch):
    """Reject special archive members and excessive decompressed payloads.

    Inputs: symlink ZIP metadata and bounded regular content. Output: both rejected.
    """
    package = tmp_path / "link.nupkg"
    member = zipfile.ZipInfo("tools/net8.0/any/devskim.dll")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(member, "outside")
    with pytest.raises(ValueError, match="invalid runtime member"):
        gate.extract_engine(package, "net8.0", tmp_path / "engine")
    make_package(package)
    monkeypatch.setattr(gate, "MAX_EXTRACTED_BYTES", 1)
    with pytest.raises(ValueError, match="invalid runtime member"):
        gate.extract_engine(package, "net8.0", tmp_path / "engine")


def test_snapshot_includes_new_files_and_omits_deleted_and_ignored_state(tmp_path):
    """Match the actual Git candidate instead of scanning live deployment files.

    Inputs: a real dirty Git repository. Output: exact intended candidate contents.
    """
    repo = make_repo(tmp_path / "repo")
    destination = tmp_path / "snapshot"
    gate.snapshot_candidate(repo, destination)
    assert {p.name for p in destination.iterdir()} == {
        ".gitignore",
        "tracked.py",
        "new.py",
    }
    assert (destination / "new.py").read_bytes() == (repo / "new.py").read_bytes()


def test_snapshot_rejects_external_links(tmp_path):
    """Do not pull unrelated host content into the scanner or its report.

    Inputs: candidate symlink escaping the repository. Output: explicit rejection.
    """
    repo = make_repo(tmp_path / "repo")
    outside = tmp_path / "outside.py"
    outside.write_text("PRIVATE_FIXTURE = 1\n", encoding="utf-8")
    (repo / "link.py").symlink_to(outside)
    with pytest.raises(ValueError, match="in-repository"):
        gate.snapshot_candidate(repo, tmp_path / "snapshot")


@pytest.mark.parametrize(
    "results,status",
    [
        ([], 0),
        ([{"ruleId": "fixture-rule", "message": {"text": "Retain this finding"}}], 1),
    ],
)
def test_entrypoint_uses_real_guard_without_modifying_report(
    tmp_path, monkeypatch, results, status
):
    """Preserve all findings and use the production SARIF result guard.

    Inputs: unmodified clean or finding-bearing report. Output: truthful gate status.
    """
    report = tmp_path / "results.sarif"
    report.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "fixture"}}, "results": results}],
            }
        ),
        encoding="utf-8",
    )
    original = report.read_bytes()
    monkeypatch.setattr(gate, "scan", lambda *args: report)
    assert gate.main(["--artifact-dir", str(tmp_path)]) == status
    assert report.read_bytes() == original


@pytest.mark.parametrize("artifact_name", ["artifacts", 'artifacts, with "quotes"'])
def test_scan_is_offline_readonly_and_keeps_raw_results(
    tmp_path, monkeypatch, artifact_name
):
    """Exercise real package extraction and source copying around the container boundary.

    Inputs: isolated repository and simulated scanner process. Output: raw report and constrained invocation.
    """
    repo = make_repo(tmp_path / "repo")
    (repo / "tools").mkdir()
    shutil.copyfile(
        gate.REPO_ROOT / "tools" / "devskim_tooling.ini",
        repo / "tools" / "devskim_tooling.ini",
    )
    package = make_package(tmp_path / "fixture.nupkg")
    artifact_dir = tmp_path / artifact_name
    artifact_dir.mkdir()
    monkeypatch.setattr(gate, "verified_package", lambda *args: package)
    monkeypatch.setattr(gate, "executable", lambda name: f"/usr/bin/{name}")
    real_run = subprocess.run
    commands = []
    raw_report = b'{"version":"2.1.0","runs":[{"results":[{"ruleId":"fixture"}]}]}\n'

    def run(command, **kwargs):
        """Simulate only Docker while retaining actual Git behavior.

        Inputs: process invocation. Output: real Git result or deterministic scanner result.
        """
        if command[0] != "/usr/bin/docker":
            return real_run(command, **kwargs)
        commands.append(command)
        mount = next(value for value in command if value.endswith("target=/output"))
        fields = next(csv.reader([mount]))
        output = Path(
            next(
                field.removeprefix("source=")
                for field in fields
                if field.startswith("source=")
            )
        )
        (output / "devskim-results.sarif").write_bytes(raw_report)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(gate.subprocess, "run", run)
    report = gate.scan(repo, artifact_dir)
    assert report.read_bytes() == raw_report
    command = commands[0]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "HOME=/run/devskim" in command
    assert "TMPDIR=/run/devskim" in command
    assert command[command.index("--ignore-rule-ids") + 1] == "DS162092"
    assert command[command.index("--ignore-globs") + 1] == gate.IGNORE_GLOBS
    assert any(value.endswith("target=/source,readonly") for value in command)
    assert any(value.endswith("target=/engine,readonly") for value in command)
    assert not list(artifact_dir.glob("scan-*"))
