"""Exercise Ice source-build failures without downloading or compiling in unit tests."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from tools import install_java_dependencies as installer


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docker/install-ice-python.sh"


def test_source_build_is_inventoried_without_relabeling_the_upstream_version():
    """Inputs: script, SBOM and workflow. Output: every admitted artifact retains its identity."""
    tree = installer.read_xml(
        (ROOT / "docker/ice-python.cdx.xml").read_text(), "Ice source inventory"
    )
    ns = {"c": installer.CYCLONEDX_NAMESPACE[1:-1]}
    components = tree.findall("c:components/c:component", ns)
    assert len(components) == 1
    component = components[0]
    assert component.findtext("c:name", namespaces=ns) == "zeroc-ice"
    assert component.findtext("c:version", namespaces=ns) == "3.6.5"
    assert component.findtext("c:purl", namespaces=ns) == "pkg:pypi/zeroc-ice@3.6.5"
    script = SCRIPT.read_text()
    references = component.findall("c:externalReferences/c:reference", ns)
    assert len(references) == 3
    for reference in references:
        assert reference.findtext("c:url", namespaces=ns) in script
        assert reference.findtext("c:hashes/c:hash", namespaces=ns) in script
    workflow = (ROOT / ".github/workflows/security-code-scanning.yml").read_text()
    assert "--lockfile=docker/ice-python.cdx.xml" in workflow
    for name in ("server", "web", "celery-worker"):
        dockerfile = (ROOT / f"docker/omero-{name}.Dockerfile").read_text()
        assert (
            "COPY docker/install-ice-python.sh /tmp/install-ice-python.sh" in dockerfile
        )
        assert "/bin/bash /tmp/install-ice-python.sh" in dockerfile


@pytest.fixture
def commands(tmp_path):
    """Inputs: isolated filesystem. Output: instrumented native-command boundary."""
    directory = tmp_path / "bin"
    directory.mkdir()
    archive = tmp_path / "source.tar.gz"
    for malicious in (False, True):
        destination = archive if not malicious else tmp_path / "escape.tar.gz"
        with tarfile.open(destination, "w:gz") as output:
            content = b"# fixture source\n"
            member = tarfile.TarInfo(
                "../outside.txt" if malicious else "zeroc-ice-3.6.5/setup.py"
            )
            member.size = len(content)
            output.addfile(member, io.BytesIO(content))
    dispatcher = directory / "dispatch"
    dispatcher.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, pathlib, shutil, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
failure = os.environ.get("FAILURE", "")
with open(os.environ["CALLS"], "a") as record:
    record.write(json.dumps([name, args]) + "\n")
if name == "curl":
    assert args[args.index("--proto") + 1] == "=https"
    assert args[args.index("--proto-redir") + 1] == "=https"
    minimum = next(arg.removeprefix("--tlsv") for arg in args if arg.startswith("--tlsv"))
    assert tuple(map(int, minimum.split("."))) == (1, 2)
    assert "--tls-max" not in args
    assert "--fail" in args and "--location" in args
    if failure == "download": sys.exit(61)
    target = pathlib.Path(args[args.index("--output") + 1])
    if target.name == "source.tar.gz":
        source = "escape.tar.gz" if failure == "extract" else "source.tar.gz"
        shutil.copyfile(pathlib.Path(os.environ["FIXTURES"]) / source, target)
    else: target.write_text("fixture patch\n")
elif name == "sha256sum":
    data = sys.stdin.read()
    assert len(data.split()[0]) == 64
    if failure == "checksum": sys.exit(62)
elif name == "patch":
    assert "--fuzz=0" in args and "--forward" in args and "-p0" in args
    assert sys.stdin.read() == "fixture patch\n"
    if failure == "patch": sys.exit(63)
elif name == "python":
    if args[0] == "-":
        sys.exit(subprocess.run([os.environ["NATIVE_PYTHON"], *args], input=sys.stdin.buffer.read()).returncode)
    if args[0] == "-c":
        if "sys.version_info" in args[1]:
            if failure == "interpreter": sys.exit(64)
        else: print("/fixture/IcePy.so")
    elif args[:3] == ["-m", "pip", "wheel"]:
        if failure == "build": sys.exit(65)
        assert "--no-deps" in args and "--no-build-isolation" in args
        directory = pathlib.Path(args[args.index("--wheel-dir") + 1])
        directory.mkdir()
        if failure != "wheel-count": (directory / "zeroc_ice-3.6.5-fixture.whl").write_bytes(b"fixture")
        if failure == "ambiguous-wheels": (directory / "zeroc_ice-3.6.5-other.whl").write_bytes(b"other")
    elif args[:3] == ["-m", "pip", "install"]:
        assert "--no-deps" in args and "--force-reinstall" in args
        if failure == "install": sys.exit(66)
    else: raise AssertionError(args)
elif name == "ldd":
    assert args == ["/fixture/IcePy.so"]
    if failure == "missing-tls":
        print("libssl.so.3 => not found")
        print("libcrypto.so.3 => /lib/libcrypto.so.3")
    else:
        print("libssl.so.3 => /lib/libssl.so.3")
        print("libcrypto.so.3 => /lib/libcrypto.so.3")
        if failure == "legacy-tls": print("libssl-obsolete.so.1.1 => /lib/obsolete.so")
else: raise AssertionError(name)
""",
        encoding="utf-8",
    )
    dispatcher.chmod(0o700)
    for name in ("curl", "sha256sum", "patch", "python", "ldd"):
        (directory / name).symlink_to(dispatcher)
    return directory


@pytest.mark.parametrize(
    "failure",
    [
        "",
        "interpreter",
        "download",
        "checksum",
        "extract",
        "patch",
        "build",
        "wheel-count",
        "ambiguous-wheels",
        "install",
        "legacy-tls",
        "missing-tls",
    ],
)
def test_build_fails_closed_and_cleans_only_its_private_work(
    tmp_path, commands, failure
):
    """Inputs: each dependency boundary failure. Output: no successful or partially admitted build."""
    calls = tmp_path / "calls.jsonl"
    sentinel = tmp_path / "preserve.txt"
    sentinel.write_text("unrelated data")
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), str(commands / "python")],
        env={
            **os.environ,
            "PATH": str(commands) + os.pathsep + os.defpath,
            "FAILURE": failure,
            "CALLS": str(calls),
            "TMPDIR": str(tmp_path),
            "FIXTURES": str(tmp_path),
            "NATIVE_PYTHON": sys.executable,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert (result.returncode == 0) == (failure == ""), result.stdout + result.stderr
    assert sentinel.read_text() == "unrelated data"
    assert not list(tmp_path.glob("omero-ice-build.*"))
    assert not (tmp_path / "outside.txt").exists()
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    if not failure:
        assert sum(name == "curl" for name, _ in recorded) == 3
        assert sum(name == "sha256sum" for name, _ in recorded) == 3
        assert sum(name == "patch" for name, _ in recorded) == 2
        assert "system OpenSSL 3" in result.stdout
    if failure in {"interpreter", "download", "checksum", "extract", "patch"}:
        assert not any(args[:3] == ["-m", "pip", "wheel"] for _, args in recorded)


@pytest.mark.parametrize(
    "arguments", [[], ["/nonexistent/python"], ["first", "second"]]
)
def test_invalid_invocations_stop_before_creating_build_state(tmp_path, arguments):
    """Inputs: absent or malformed interpreter. Output: usage failure without side effects."""
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), *arguments],
        env={**os.environ, "TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 2 and "Usage:" in result.stderr
    assert not list(tmp_path.iterdir())
