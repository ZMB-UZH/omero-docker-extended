#!/usr/bin/env python3
"""Run one pinned DevSkim engine against the complete Git candidate, without uploads."""

from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE_GLOBS = (
    "**/.git/**,**/pgdata/**,**/omero_data/**,**/omero_temp/**,**/third_party/**"
)
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024


def executable(name: str) -> str:
    """Resolve a required command before use.

    Inputs: executable name. Output: absolute executable path or an explicit failure.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise ValueError(f"DevSkim requires {name}.")
    return resolved


def read_tooling(path: Path) -> dict[str, str]:
    """Read the reviewed CLI, package fingerprint, and container runtime pins.

    Inputs: tooling manifest path. Output: validated immutable tooling settings.
    """
    config = configparser.ConfigParser(interpolation=None)
    with path.open(encoding="utf-8") as stream:
        config.read_file(stream)
    if config.sections() != ["devskim"] or config.defaults():
        raise ValueError(
            "DevSkim tooling requires exactly one explicit configuration section."
        )
    settings = dict(config["devskim"])
    patterns = {
        "version": r"[0-9]+\.[0-9]+\.[0-9]+",
        "package_sha256": r"[0-9a-f]{64}",
        "runtime_image": r"mcr\.microsoft\.com/dotnet/sdk:[0-9.]+-bookworm-slim@sha256:[0-9a-f]{64}",
        "framework": r"net[0-9]+\.0",
    }
    if set(settings) != set(patterns) or any(
        re.fullmatch(pattern, settings[key]) is None
        for key, pattern in patterns.items()
    ):
        raise ValueError("DevSkim tooling requires complete, immutable release pins.")
    return settings


def verified_package(settings: dict[str, str], cache: Path) -> Path:
    """Fetch the official NuGet artifact and reject incomplete or altered cache data.

    Inputs: validated tooling settings and owned cache. Output: hash-verified package.
    """
    cache.mkdir(parents=True, exist_ok=True)
    version = settings["version"]
    filename = f"microsoft.cst.devskim.cli.{version}.nupkg"
    package = cache / filename
    if package.is_symlink():
        raise ValueError("DevSkim package cache must not contain symlinks.")
    if not package.exists():
        url = (
            "https://api.nuget.org/v3-flatcontainer/microsoft.cst.devskim.cli/"
            f"{version}/{filename}"
        )
        with tempfile.TemporaryDirectory(prefix="download-", dir=cache) as temporary:
            candidate = Path(temporary) / filename
            subprocess.run(
                [
                    executable("curl"),
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--proto",
                    "=https",
                    "--connect-timeout",
                    "20",
                    "--max-time",
                    "180",
                    "--max-filesize",
                    str(MAX_PACKAGE_BYTES),
                    "--output",
                    str(candidate),
                    url,
                ],
                check=True,
            )
            verify_package_digest(candidate, settings["package_sha256"])
            candidate.replace(package)
    verify_package_digest(package, settings["package_sha256"])
    return package


def verify_package_digest(path: Path, expected: str) -> None:
    """Verify package size and full content before any archive processing.

    Inputs: candidate package and public SHA-256. Output: None, or a closed failure.
    """
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > MAX_PACKAGE_BYTES
    ):
        raise ValueError("DevSkim package must be a bounded regular file.")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(
            "DevSkim package checksum does not match the reviewed release."
        )


def extract_engine(package: Path, framework: str, destination: Path) -> None:
    """Extract the selected official runtime payload inside a new private directory.

    Inputs: verified NuGet package, framework and destination. Output: CLI runtime files.
    """
    prefix = f"tools/{framework}/any/"
    size = 0
    seen: set[str] = set()
    with zipfile.ZipFile(package) as archive:
        for member in archive.infolist():
            if not member.filename.startswith(prefix) or member.is_dir():
                continue
            name = member.filename.removeprefix(prefix)
            relative = PurePosixPath(name)
            size += member.file_size
            if (
                not name
                or name in seen
                or "\\" in name
                or relative.is_absolute()
                or ".." in relative.parts
                or stat.S_ISLNK(member.external_attr >> 16)
                or size > MAX_EXTRACTED_BYTES
            ):
                raise ValueError("DevSkim package contains an invalid runtime member.")
            seen.add(name)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    if not (destination / "devskim.dll").is_file():
        raise ValueError("DevSkim package does not contain the selected CLI runtime.")


def snapshot_candidate(repo_root: Path, destination: Path) -> None:
    """Copy Git-selected candidate files without deployment state or ignored caches.

    Inputs: repository root and new snapshot directory. Output: complete candidate copy.
    """
    git = executable("git")
    result = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    deleted = subprocess.run(
        [git, "ls-files", "--deleted", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    removed = set(deleted.stdout.split(b"\0"))
    files = sorted(set(result.stdout.split(b"\0")) - removed - {b""})
    if not files:
        raise ValueError("DevSkim requires a non-empty Git candidate.")
    for raw_path in files:
        relative = PurePosixPath(os.fsdecode(raw_path))
        source = repo_root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or source.is_symlink()
            or not source.resolve().is_relative_to(repo_root.resolve())
            or not source.is_file()
        ):
            raise ValueError("DevSkim candidate must contain only in-repository files.")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    print(f"DevSkim candidate: {len(files)} Git-selected files.", flush=True)


def bind_mount(source: Path, target: str, *, readonly: bool = True) -> str:
    """Encode bind mounts using Docker's CSV grammar, including unusual path names.

    Inputs: host source, container target and access mode. Output: one mount argument.
    """
    fields = ["type=bind", f"source={source}", f"target={target}"]
    if readonly:
        fields.append("readonly")
    stream = io.StringIO()
    csv.writer(stream, lineterminator="").writerow(fields)
    return stream.getvalue()


def scan(repo_root: Path, artifact_dir: Path) -> Path:
    """Run the reviewed scanner without network access or write access to source.

    Inputs: repository and artifact roots. Output: unmodified SARIF report path.
    """
    settings = read_tooling(repo_root / "tools" / "devskim_tooling.ini")
    package = verified_package(settings, artifact_dir / "packages")
    docker = executable("docker")
    report = artifact_dir / "devskim-results.sarif"
    with tempfile.TemporaryDirectory(prefix="scan-", dir=artifact_dir) as temporary:
        root = Path(temporary)
        engine, source, output = (
            root / name for name in ("engine", "source", "output")
        )
        for directory in (engine, source, output):
            directory.mkdir()
        extract_engine(package, settings["framework"], engine)
        snapshot_candidate(repo_root, source)
        subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/run/devskim:rw,nosuid,nodev,mode=1777",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--env",
                "HOME=/run/devskim",
                "--env",
                "TMPDIR=/run/devskim",
                "--env",
                "DOTNET_CLI_TELEMETRY_OPTOUT=1",
                "--mount",
                bind_mount(engine, "/engine"),
                "--mount",
                bind_mount(source, "/source"),
                "--mount",
                bind_mount(output, "/output", readonly=False),
                settings["runtime_image"],
                "dotnet",
                "/engine/devskim.dll",
                "analyze",
                "--source-code",
                "/source",
                "--output-file",
                "/output/devskim-results.sarif",
                "--ignore-globs",
                IGNORE_GLOBS,
                "--ignore-rule-ids",
                "DS162092",
            ],
            check=True,
        )
        candidate_report = output / report.name
        if candidate_report.is_symlink() or not candidate_report.is_file():
            raise ValueError("DevSkim must produce a regular SARIF report file.")
        candidate_report.replace(report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Run the shared local/hosted DevSkim gate and retain every diagnostic.

    Inputs: CLI arguments. Output: exit status from the existing SARIF result guard.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = scan(REPO_ROOT, args.artifact_dir.resolve())
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "sarif_result_guard.py"),
                str(report),
            ],
            check=False,
        )
        return result.returncode
    except (
        OSError,
        ValueError,
        configparser.Error,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"DevSkim gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
