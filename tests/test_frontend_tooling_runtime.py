"""Exercise actual tool-cache files, verified archives, and subprocess boundaries."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from tools import frontend_preview_tooling as tooling


def _executable(path, contents):
    """Inputs: private fixture path and script. Output: executable file for real subprocesses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o700)
    return path


@pytest.fixture
def manifest():
    """Inputs: repository pins. Output: a fresh manifest for isolated runtime fixtures."""
    return tooling.load_manifest()


def test_xdg_defaults_and_explicit_install_root(tmp_path, monkeypatch):
    """Inputs: private HOME/XDG overrides. Output: cache and runtime roots follow the contract."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "OMERO_AGENT_NODE_DIR"):
        monkeypatch.delenv(key, raising=False)
    assert (
        tooling.default_tool_dir()
        == tmp_path / ".cache" / "omero-agent-frontend-preview"
    )
    expected = "node-v1.2.3-linux-x64"
    assert (
        tooling.default_node_dir("1.2.3", "x64")
        == tmp_path / ".local" / "share" / "omero-agent-node" / expected
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert (
        tooling.default_tool_dir()
        == tmp_path / "cache" / "omero-agent-frontend-preview"
    )
    assert (
        tooling.default_node_dir("1.2.3", "x64")
        == tmp_path / "data" / "omero-agent-node" / expected
    )
    monkeypatch.setenv("OMERO_AGENT_NODE_DIR", "~/selected")
    assert tooling.default_node_dir("1.2.3", "x64") == tmp_path / "selected"


def test_tool_cache_installs_once_and_refreshes_changed_manifest(
    tmp_path, monkeypatch, manifest
):
    """Inputs: real node/npm protocol fixtures. Output: exact installs, cache reuse, version refresh."""
    binaries = tmp_path / "bin"
    _executable(
        binaries / "node", f"#!/bin/sh\nprintf 'v{manifest['node_version']}\\n'\n"
    )
    _executable(
        binaries / "npm",
        f"#!{sys.executable}\n"
        "import json, os\nfrom pathlib import Path\n"
        "assert os.environ['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] == '1'\n"
        "with Path('calls').open('a') as stream: stream.write('install\\n')\n"
        "Path('node_modules').mkdir(exist_ok=True)\n"
        "Path('package-lock.json').write_text('{}')\n",
    )
    monkeypatch.setenv("PATH", str(binaries))
    monkeypatch.delenv("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", raising=False)
    destination = tmp_path / "tool cache"
    assert tooling.ensure_tooling(destination, manifest) == destination
    package = json.loads((destination / "package.json").read_text())
    assert package["dependencies"] == manifest["dependencies"]
    assert package["private"] is True
    assert (destination / "calls").read_text() == "install\n"
    previous = (destination / "package.json").stat().st_mtime_ns
    tooling.ensure_tooling(destination, manifest)
    assert (destination / "calls").read_text() == "install\n"
    assert (destination / "package.json").stat().st_mtime_ns == previous
    newer = manifest | {
        "dependencies": manifest["dependencies"] | {"fixture-package": "1.0.0"}
    }
    tooling.ensure_tooling(destination, newer)
    assert (destination / "calls").read_text() == "install\ninstall\n"
    assert (
        json.loads((destination / "package.json").read_text())["dependencies"]
        == newer["dependencies"]
    )


def test_missing_and_failed_tool_runtime_does_not_create_cache(
    tmp_path, monkeypatch, manifest
):
    """Inputs: absent runtime, then failing executable. Output: no partially initialized cache."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    monkeypatch.setenv("PATH", str(binaries))
    destination = tmp_path / "cache"
    with pytest.raises(RuntimeError, match="not available"):
        tooling.ensure_tooling(destination, manifest)
    assert not destination.exists()
    _executable(binaries / "node", "#!/bin/sh\nexit 9\n")
    _executable(binaries / "npm", "#!/bin/sh\nexit 0\n")
    with pytest.raises(subprocess.CalledProcessError):
        tooling.ensure_tooling(destination, manifest)
    assert not destination.exists()


@pytest.mark.parametrize("failure", [None, "digest", "version"])
def test_pinned_node_install_verifies_bytes_and_version_before_publication(
    tmp_path, monkeypatch, manifest, failure
):
    """Inputs: real archive, expected digest and runtime. Output: verified install or no published tree."""
    version = manifest["node_version"]
    archive = tmp_path / "fixture.tar.xz"
    reported = "0.0.0" if failure == "version" else version
    contents = f"#!/bin/sh\nprintf 'v{reported}\\n'\n".encode()
    with tarfile.open(archive, "w:xz") as bundle:
        info = tarfile.TarInfo(f"node-v{version}-linux-x64/bin/node")
        info.mode = 0o700
        info.size = len(contents)
        bundle.addfile(info, io.BytesIO(contents))
    monkeypatch.setattr(tooling, "node_linux_arch", lambda: "x64")
    requested = []

    def download(wanted_version, filename, target):
        """Inputs: downloader request. Output: deterministic archive/checksum without network."""
        assert wanted_version == version
        requested.append(filename)
        if filename.endswith(".tar.xz"):
            shutil.copyfile(archive, target)
        else:
            digest = (
                "0" * 64
                if failure == "digest"
                else hashlib.sha256(archive.read_bytes()).hexdigest()
            )
            target.write_text(f"{digest}  node-v{version}-linux-x64.tar.xz\n")

    monkeypatch.setattr(tooling, "download_node_release_file", download)
    destination = tmp_path / "runtime" / "selected"
    if failure:
        with pytest.raises(RuntimeError):
            tooling.install_pinned_node(destination, version)
        assert not destination.exists()
    else:
        assert tooling.install_pinned_node(destination, version) == destination
        assert tooling.installed_node_version(destination) == f"v{version}"
        assert tooling.install_pinned_node(destination, version) == destination
    assert len(requested) == 2
    assert not list(destination.parent.glob("node-install-*"))


def test_existing_unknown_node_installation_is_never_overwritten(tmp_path, manifest):
    """Inputs: existing unmanaged contents. Output: explicit refusal and unchanged bytes."""
    sentinel = tmp_path / "keep"
    sentinel.write_bytes(b"existing installation")
    with pytest.raises(RuntimeError, match="already exists"):
        tooling.install_pinned_node(tmp_path, manifest["node_version"])
    assert sentinel.read_bytes() == b"existing installation"
    assert list(tmp_path.iterdir()) == [sentinel]
    _executable(tmp_path / "bin" / "node", "#!/bin/sh\nexit 7\n")
    assert tooling.installed_node_version(tmp_path) is None


@pytest.mark.parametrize("output_mode", ["shell", "json", "bin"])
def test_node_activation_output_preserves_shell_metacharacters(
    tmp_path, capsys, output_mode
):
    """Inputs: legal path containing shell syntax. Output: literal PATH, never command execution."""
    directory = tmp_path / "$(touch injected-marker)" / "quoted' space"
    args = argparse.Namespace(
        print_bin=output_mode == "bin", json=output_mode == "json"
    )
    tooling.print_node_install_status(directory, "1.2.3", args)
    output = capsys.readouterr().out.strip()
    if output_mode == "bin":
        assert output == str(directory / "bin")
        return
    if output_mode == "json":
        payload = json.loads(output)
        assert payload["node_dir"] == str(directory)
        output = payload["path_export"]
    result = subprocess.run(
        ["/bin/sh", "-c", output + '; printf "%s" "$PATH"'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.defpath},
        timeout=5,
    )
    assert not (tmp_path / "injected-marker").exists()
    assert result.stdout == str(directory / "bin") + ":" + os.defpath


def test_wrapped_command_keeps_arguments_separate_and_returns_child_status(tmp_path):
    """Inputs: spaces/options/shell syntax. Output: byte-exact argv, cwd, PATH and exit status."""
    binary = _executable(
        tmp_path / "node_modules" / ".bin" / "vitest",
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        "Path('observed.json').write_text(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(), 'path': os.environ['PATH']}))\n"
        "sys.exit(7)\n",
    )
    arguments = ["--run", "space value", "$(not-a-command)"]
    assert tooling.run_wrapped_command(tmp_path, "vitest", arguments) == 7
    result = json.loads((tmp_path / "observed.json").read_text())
    assert result["args"] == arguments
    assert result["cwd"] == str(tmp_path)
    assert result["path"].split(":")[0] == str(binary.parent)
    with pytest.raises(RuntimeError, match="was not installed"):
        tooling.wrapped_binary(tmp_path, "missing-wrapper")


@pytest.mark.parametrize("as_json", [False, True])
def test_bootstrap_status_matches_installed_manifest(
    tmp_path, manifest, capsys, as_json
):
    """Inputs: manifest and chosen cache. Output: useful machine-readable or human-readable status."""
    tooling.print_bootstrap_status(tmp_path, manifest, as_json)
    output = capsys.readouterr().out
    if as_json:
        payload = json.loads(output)
        assert payload["dependencies"] == manifest["dependencies"]
        assert payload["tool_dir"] == str(tmp_path)
    else:
        assert str(tmp_path) in output
        for name, version in manifest["dependencies"].items():
            assert f"{name}: {version}" in output
    with pytest.raises(RuntimeError, match="dependencies must be a mapping"):
        tooling.print_bootstrap_status(
            tmp_path, manifest | {"dependencies": []}, as_json
        )


@pytest.mark.parametrize(
    ("system", "architecture", "expected"),
    [
        ("linux", "x86_64", "x64"),
        ("linux", "AMD64", "x64"),
        ("linux", "aarch64", "arm64"),
        ("linux", "ARM64", "arm64"),
        ("linux", "unsupported", None),
        ("darwin", "arm64", None),
    ],
)
def test_node_archive_selection_matches_supported_host(
    monkeypatch, system, architecture, expected
):
    """Inputs: platform identification. Output: correct archive architecture or explicit refusal."""
    monkeypatch.setattr(tooling.sys, "platform", system)
    monkeypatch.setattr(tooling.platform, "machine", lambda: architecture)
    if expected:
        assert tooling.node_linux_arch() == expected
    else:
        with pytest.raises(RuntimeError, match="Linux"):
            tooling.node_linux_arch()


@pytest.mark.parametrize(
    "scenario",
    ["valid", "absolute", "outside", "missing", "duplicate", "duplicate_link", "fifo"],
)
def test_real_archive_links_and_overwrite_boundaries(tmp_path, scenario):
    """Inputs: real archives with link/collision hazards. Output: contained extraction or refusal."""
    archive = tmp_path / "input.tar.xz"
    output = tmp_path / "output"
    output.mkdir()
    sentinel = tmp_path / "outside"
    sentinel.write_bytes(b"operator data")
    with tarfile.open(archive, "w:xz") as bundle:
        directory = tarfile.TarInfo("bin")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o750
        bundle.addfile(directory)
        target = tarfile.TarInfo("bin/node")
        target.size = 4
        target.mode = 0o700
        bundle.addfile(target, io.BytesIO(b"node"))
        if scenario == "duplicate":
            bundle.addfile(target, io.BytesIO(b"evil"))
        link = tarfile.TarInfo("bin/link")
        link.type = tarfile.LNKTYPE
        link.linkname = "bin/node"
        if scenario == "absolute":
            link.linkname = str(sentinel)
        elif scenario == "outside":
            link.type = tarfile.SYMTYPE
            link.linkname = "../../outside"
        elif scenario == "missing":
            link.linkname = "bin/absent"
        elif scenario == "fifo":
            link.type = tarfile.FIFOTYPE
        bundle.addfile(link)
        if scenario == "duplicate_link":
            bundle.addfile(link)
    if scenario == "valid":
        tooling.safe_extract_tar_xz(archive, output)
        assert (output / "bin/link").read_bytes() == b"node"
        assert (output / "bin/link").stat().st_ino == (
            output / "bin/node"
        ).stat().st_ino
        assert (output / "bin").stat().st_mode & 0o777 == 0o750
        assert (output / "bin/node").stat().st_mode & 0o777 == 0o700
    else:
        with pytest.raises(RuntimeError, match="Refusing"):
            tooling.safe_extract_tar_xz(archive, output)
    assert sentinel.read_bytes() == b"operator data"


def test_missing_checksum_and_missing_archive_stream_fail_closed(tmp_path, monkeypatch):
    """Inputs: incomplete upstream artifacts. Output: no unverified file is published."""
    sums = tmp_path / "checksums"
    sums.write_text("0" * 64 + "  unrelated.tar.xz\n")
    with pytest.raises(RuntimeError, match="Could not find"):
        tooling.expected_sha256(sums, "wanted.tar.xz")
    archive = tmp_path / "input.tar.xz"
    with tarfile.open(archive, "w:xz") as bundle:
        member = tarfile.TarInfo("node")
        member.size = 4
        bundle.addfile(member, io.BytesIO(b"node"))
    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *_args: None)
    target = tmp_path / "output" / "node"
    with tarfile.open(archive, "r:xz") as bundle:
        with pytest.raises(RuntimeError, match="Could not extract"):
            tooling.extract_file_member(bundle, bundle.getmembers()[0], target)
    assert not target.exists()


@pytest.mark.parametrize("failure", ["exit", "timeout", "exec"])
def test_release_download_errors_are_actionable(tmp_path, monkeypatch, failure):
    """Inputs: downloader failure modes. Output: explicit download error preserving its cause."""
    version = tooling.load_manifest()["node_version"]
    filename = f"node-v{version}-linux-x64.tar.xz"
    binary = _executable(
        tmp_path / "curl", "#!/bin/sh\nprintf 'unavailable' >&2\nexit 22\n"
    )
    monkeypatch.setattr(tooling, "ensure_command_available", lambda _name: str(binary))
    if failure != "exit":

        def fail_run(*_args, **_kwargs):
            """Inputs: downloader invocation. Output: OS or subprocess timeout failure."""
            if failure == "timeout":
                raise subprocess.TimeoutExpired(str(binary), 60)
            raise OSError("cannot execute downloader")

        monkeypatch.setattr(tooling.subprocess, "run", fail_run)
    target = tmp_path / "download"
    with pytest.raises(RuntimeError, match="Node.js release download failed") as caught:
        tooling.download_node_release_file(version, filename, target)
    assert filename in str(caught.value)
    assert not target.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_real_cli_install_bootstrap_and_forwarding(
    tmp_path, monkeypatch, manifest, explicit
):
    """Inputs: actual CLI processes and private executable fixtures. Output: correct cache and exit status."""
    version = manifest["node_version"]
    node_dir = tmp_path / "node runtime"
    _executable(node_dir / "bin/node", f"#!/bin/sh\nprintf 'v{version}\\n'\n")
    _executable(
        node_dir / "bin/npm",
        f"#!{sys.executable}\nfrom pathlib import Path\n"
        "Path('node_modules').mkdir(exist_ok=True)\n"
        "Path('package-lock.json').write_text('{}')\n",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(node_dir / "bin"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("OMERO_AGENT_NODE_DIR", str(node_dir))
    tool_dir = tmp_path / "explicit tools" if explicit else tooling.default_tool_dir()
    runner = [sys.executable, str(Path(tooling.__file__).resolve())]
    install = [*runner, "install-node", "--print-bin"]
    if explicit:
        install += ["--node-dir", str(node_dir)]
    result = subprocess.run(
        install, capture_output=True, text=True, check=True, timeout=10
    )
    assert result.stdout.strip() == str(node_dir / "bin")
    arguments = ["--tool-dir", str(tool_dir)] if explicit else []
    result = subprocess.run(
        [*runner, *arguments, "bootstrap", "--json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout)["dependencies"] == manifest["dependencies"]
    _executable(
        tool_dir / "node_modules/.bin/vitest",
        f"#!{sys.executable}\nimport json, sys\n"
        "print(json.dumps(sys.argv[1:]))\nsys.exit(7)\n",
    )
    result = subprocess.run(
        [*runner, *arguments, "vitest", "--", "--run", "space value"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 7
    assert json.loads(result.stdout) == ["--run", "space value"]
    _executable(node_dir / "bin/node", "#!/bin/sh\nprintf 'v0.0.0\\n'\n")
    result = subprocess.run(
        [*runner, *arguments, "bootstrap"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert f"Found v0.0.0, need v{version}." in result.stderr
    assert not result.stdout
