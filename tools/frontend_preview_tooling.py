#!/usr/bin/env python3
"""Bootstrap and run the repo's host-side Vite/Vitest preview tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("frontend_preview_tooling_manifest.json")


def load_manifest() -> dict[str, object]:
    """Load the pinned host-tooling manifest."""
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def normalize_version(version_text: str) -> tuple[int, ...]:
    """Turn a semver-like string into a comparable integer tuple."""
    cleaned = version_text.strip().lstrip("v").split("-", 1)[0]
    return tuple(int(part) for part in cleaned.split("."))


def default_tool_dir() -> Path:
    """Return the default cache-backed install location."""
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    cache_root = Path(xdg_cache_home) if xdg_cache_home else Path.home() / ".cache"
    return cache_root / "omero-agent-frontend-preview"


def default_node_dir(version: str, arch: str) -> Path:
    """Return the default host-side pinned Node.js install directory."""
    override_root = os.environ.get("OMERO_AGENT_NODE_DIR")
    if override_root:
        return Path(override_root).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    data_root = (
        Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    )
    return data_root / "omero-agent-node" / f"node-v{version}-linux-{arch}"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap the pinned host-side Vite/Vitest preview toolchain and run "
            "the wrapped frontend commands from a cache-backed directory."
        )
    )
    parser.add_argument(
        "--tool-dir",
        default=os.environ.get("OMERO_AGENT_FRONTEND_TOOLING_DIR"),
        help=(
            "Override the host-side install directory. Defaults to "
            "$OMERO_AGENT_FRONTEND_TOOLING_DIR or an XDG cache location."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Install or refresh the pinned frontend preview tooling.",
    )
    bootstrap_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable bootstrap information.",
    )

    install_node_parser = subparsers.add_parser(
        "install-node",
        help="Install the pinned Linux Node.js LTS binary after SHA-256 verification.",
    )
    install_node_parser.add_argument(
        "--node-dir",
        default=os.environ.get("OMERO_AGENT_NODE_DIR"),
        help=(
            "Override the pinned Node.js install directory. Defaults to "
            "$OMERO_AGENT_NODE_DIR or an XDG data location."
        ),
    )
    install_node_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable install information.",
    )
    install_node_parser.add_argument(
        "--print-bin",
        action="store_true",
        help="Print only the installed Node.js bin directory.",
    )

    for command_name, help_text in (
        ("vite", "Run the pinned Vite CLI."),
        ("vitest", "Run the pinned Vitest CLI."),
        ("playwright", "Run the pinned Playwright CLI."),
    ):
        command_parser = subparsers.add_parser(command_name, help=help_text)
        command_parser.add_argument(
            "args",
            nargs=argparse.REMAINDER,
            help="Arguments passed through to the wrapped frontend tool.",
        )

    return parser.parse_args()


def ensure_command_available(command: str) -> str:
    """Return the absolute path for a required host command."""
    command_path = shutil.which(command)
    if not command_path:
        raise RuntimeError(f"Required host command '{command}' is not available.")
    return command_path


def ensure_node_version(manifest: dict[str, object]) -> None:
    """Verify that host Node.js exactly matches the pinned LTS version."""
    node_bin = ensure_command_available("node")
    ensure_command_available("npm")
    node_version = subprocess.run(
        [node_bin, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    current = normalize_version(node_version)
    required_version = str(manifest["node_version"])
    required = normalize_version(required_version)
    if current != required:
        raise RuntimeError(
            "Node.js does not match the pinned frontend tooling runtime. "
            f"Found {node_version}, need v{required_version}. Run "
            "`python3 tools/frontend_preview_tooling.py install-node` and "
            "activate the printed PATH before retrying."
        )


def build_package_json(manifest: dict[str, object]) -> dict[str, object]:
    """Build the package.json payload written into the host tooling cache."""
    return {
        "name": manifest["name"],
        "private": True,
        "type": "module",
        "engines": {"node": str(manifest["node_version"])},
        "dependencies": manifest["dependencies"],
    }


def write_package_json(tool_dir: Path, manifest: dict[str, object]) -> bool:
    """Write the desired package.json and report whether it changed."""
    package_json_path = tool_dir / "package.json"
    desired = build_package_json(manifest)
    desired_text = json.dumps(desired, indent=2, sort_keys=True) + "\n"
    current_text = (
        package_json_path.read_text(encoding="utf-8")
        if package_json_path.exists()
        else None
    )
    if current_text == desired_text:
        return False
    package_json_path.write_text(desired_text, encoding="utf-8")
    return True


def ensure_tooling(tool_dir: Path, manifest: dict[str, object]) -> Path:
    """Install or refresh the host-side frontend tooling in the cache dir."""
    ensure_node_version(manifest)
    tool_dir.mkdir(parents=True, exist_ok=True)
    package_changed = write_package_json(tool_dir, manifest)
    package_lock = tool_dir / "package-lock.json"
    node_modules = tool_dir / "node_modules"
    if package_changed or not package_lock.exists() or not node_modules.exists():
        npm_bin = ensure_command_available("npm")
        install_env = os.environ.copy()
        install_env.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")
        subprocess.run(
            [npm_bin, "install", "--no-audit", "--no-fund", "--loglevel=error"],
            cwd=tool_dir,
            env=install_env,
            check=True,
        )
    return tool_dir


def node_linux_arch() -> str:
    """Return the official Node.js Linux binary arch for this host."""
    if sys.platform != "linux":
        raise RuntimeError(
            "The pinned Node.js installer supports Linux hosts only. Install "
            "the manifest-pinned Node.js version manually on this platform."
        )
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    raise RuntimeError(
        f"Unsupported Linux architecture for official Node.js binaries: {machine}."
    )


def download_file(url: str, destination: Path) -> None:
    """Download a URL to a local path."""
    with urllib.request.urlopen(url, timeout=60) as response:
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def sha256_hex(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_sha256(shasums_path: Path, filename: str) -> str:
    """Return the expected digest for a Node.js release artifact."""
    for line in shasums_path.read_text(encoding="utf-8").splitlines():
        digest, separator, artifact_name = line.partition("  ")
        if separator and artifact_name == filename:
            return digest
    raise RuntimeError(f"Could not find {filename} in Node.js SHASUMS256.txt.")


def verify_sha256(archive_path: Path, shasums_path: Path, filename: str) -> None:
    """Verify the downloaded Node.js archive against official SHA-256 data."""
    expected = expected_sha256(shasums_path, filename)
    actual = sha256_hex(archive_path)
    if actual != expected:
        raise RuntimeError(
            f"SHA-256 mismatch for {filename}: expected {expected}, got {actual}."
        )


def is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether path is inside parent without requiring newer pathlib APIs."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def safe_extract_tar_xz(archive_path: Path, destination: Path) -> None:
    """Extract a tar.xz archive without allowing path traversal."""
    destination_root = destination.resolve()
    with tarfile.open(archive_path, "r:xz") as archive:
        members = archive.getmembers()
        for member in members:
            member_path = (destination / member.name).resolve()
            if not is_relative_to(member_path, destination_root):
                raise RuntimeError(
                    f"Refusing to extract unsafe archive member: {member.name}"
                )
            if not (
                member.isfile() or member.isdir() or member.issym() or member.islnk()
            ):
                raise RuntimeError(
                    f"Refusing to extract unsupported archive member: {member.name}"
                )
            if member.issym() or member.islnk():
                link_target = Path(member.linkname)
                if link_target.is_absolute():
                    raise RuntimeError(
                        f"Refusing to extract absolute link target: {member.name}"
                    )
                link_root = member_path.parent if member.issym() else destination
                resolved_link = (link_root / link_target).resolve()
                if not is_relative_to(resolved_link, destination_root):
                    raise RuntimeError(
                        f"Refusing to extract unsafe link target: {member.name}"
                    )
        try:
            archive.extractall(destination, members, filter="data")
        except TypeError:
            archive.extractall(destination, members)


def installed_node_version(node_dir: Path) -> str | None:
    """Return the installed Node.js version string, if present and runnable."""
    node_bin = node_dir / "bin" / "node"
    if not node_bin.is_file():
        return None
    completed = subprocess.run(
        (str(node_bin), "--version"),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def install_pinned_node(node_dir: Path, version: str) -> Path:
    """Install the manifest-pinned Linux Node.js binary under node_dir."""
    arch = node_linux_arch()
    required_version = f"v{version}"
    current_version = installed_node_version(node_dir)
    if current_version == required_version:
        return node_dir
    if node_dir.exists():
        raise RuntimeError(
            f"{node_dir} already exists but does not contain Node.js "
            f"{required_version}. Move it aside before reinstalling."
        )

    filename = f"node-v{version}-linux-{arch}.tar.xz"
    release_url = f"https://nodejs.org/dist/v{version}"
    node_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="node-install-", dir=node_dir.parent
    ) as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / filename
        shasums_path = tmp_path / "SHASUMS256.txt"
        download_file(f"{release_url}/{filename}", archive_path)
        download_file(f"{release_url}/SHASUMS256.txt", shasums_path)
        verify_sha256(archive_path, shasums_path, filename)
        extract_root = tmp_path / "extract"
        extract_root.mkdir()
        safe_extract_tar_xz(archive_path, extract_root)
        extracted_node_dir = extract_root / f"node-v{version}-linux-{arch}"
        if installed_node_version(extracted_node_dir) != required_version:
            raise RuntimeError(f"Extracted Node.js archive did not provide {version}.")
        shutil.move(str(extracted_node_dir), node_dir)
    return node_dir


def print_node_install_status(
    node_dir: Path, version: str, args: argparse.Namespace
) -> None:
    """Emit instructions for activating the pinned Node.js installation."""
    bin_dir = node_dir / "bin"
    payload = {
        "node_version": version,
        "node_dir": str(node_dir),
        "bin_dir": str(bin_dir),
        "path_export": f'export PATH="{bin_dir}:$PATH"',
    }
    if args.print_bin:
        print(payload["bin_dir"])
        return
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(payload["path_export"])


def wrapped_binary(tool_dir: Path, command_name: str) -> Path:
    """Return the bin path for the wrapped frontend command."""
    suffix = ".cmd" if os.name == "nt" else ""
    binary = tool_dir / "node_modules" / ".bin" / f"{command_name}{suffix}"
    if not binary.exists():
        raise RuntimeError(
            f"Wrapped binary '{command_name}' was not installed under {tool_dir}."
        )
    return binary


def print_bootstrap_status(
    tool_dir: Path, manifest: dict[str, object], as_json: bool
) -> None:
    """Emit the resolved tooling status after bootstrap."""
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise RuntimeError("Frontend tooling manifest dependencies must be a mapping.")
    payload = {
        "tool_dir": str(tool_dir),
        "repo_root": str(REPO_ROOT),
        "manifest_path": str(MANIFEST_PATH),
        "node_version": str(manifest["node_version"]),
        "dependencies": dependencies,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Tool dir: {payload['tool_dir']}")
    print(f"Manifest: {payload['manifest_path']}")
    for dependency_name, version in dependencies.items():
        print(f"{dependency_name}: {version}")


def run_wrapped_command(
    tool_dir: Path, command_name: str, forwarded_args: list[str]
) -> int:
    """Run the wrapped frontend command from the cache-backed tooling dir."""
    binary = wrapped_binary(tool_dir, command_name)
    command = [str(binary), *forwarded_args]
    env = os.environ.copy()
    env["PATH"] = f"{binary.parent}:{env.get('PATH', '')}"
    completed = subprocess.run(command, cwd=tool_dir, env=env, check=False)
    return completed.returncode


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    manifest = load_manifest()
    if args.command == "install-node":
        version = str(manifest["node_version"])
        arch = node_linux_arch()
        node_dir = (
            Path(args.node_dir).expanduser()
            if args.node_dir
            else default_node_dir(version, arch)
        )
        installed_dir = install_pinned_node(node_dir.resolve(), version)
        print_node_install_status(installed_dir, version, args)
        return 0

    tool_dir = Path(args.tool_dir).expanduser() if args.tool_dir else default_tool_dir()
    tool_dir = ensure_tooling(tool_dir.resolve(), manifest)

    if args.command == "bootstrap":
        print_bootstrap_status(tool_dir, manifest, args.json)
        return 0

    forwarded_args = list(args.args)
    if forwarded_args and forwarded_args[0] == "--":
        forwarded_args = forwarded_args[1:]
    return run_wrapped_command(tool_dir, args.command, forwarded_args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
