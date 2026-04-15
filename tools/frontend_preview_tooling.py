#!/usr/bin/env python3
"""Bootstrap and run the repo's host-side Vite/Vitest preview tooling."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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
    """Verify that host Node.js is present and recent enough for the pinned tools."""
    ensure_command_available("node")
    ensure_command_available("npm")
    node_version = subprocess.run(
        ["node", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    current = normalize_version(node_version)
    minimum = normalize_version(str(manifest["node_min_version"]))
    if current < minimum:
        raise RuntimeError(
            "Node.js is too old for the pinned frontend tooling. "
            f"Found {node_version}, need >= {manifest['node_min_version']}."
        )


def build_package_json(manifest: dict[str, object]) -> dict[str, object]:
    """Build the package.json payload written into the host tooling cache."""
    return {
        "name": manifest["name"],
        "private": True,
        "type": "module",
        "engines": {"node": f">={manifest['node_min_version']}"},
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
        install_env = os.environ.copy()
        install_env.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
            cwd=tool_dir,
            env=install_env,
            check=True,
        )
    return tool_dir


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
    payload = {
        "tool_dir": str(tool_dir),
        "repo_root": str(REPO_ROOT),
        "manifest_path": str(MANIFEST_PATH),
        "dependencies": manifest["dependencies"],
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Tool dir: {payload['tool_dir']}")
    print(f"Manifest: {payload['manifest_path']}")
    for dependency_name, version in payload["dependencies"].items():
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
