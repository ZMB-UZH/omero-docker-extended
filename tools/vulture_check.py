"""Run Vulture against tracked production Python files only."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath


DEFAULT_MIN_CONFIDENCE = 100
TRACKED_PYTHON_PATHSPEC = "*.py"
EXCLUDED_TOP_LEVEL_DIRS: frozenset[str] = frozenset({"docs", "tests", "third_party"})


def resolve_required_executable(name: str) -> str:
    """Resolve an executable name to an absolute path."""

    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"Required executable `{name}` is not available in PATH.")
    return resolved


def is_vulture_target(relative_path: PurePosixPath) -> bool:
    """Return True when a tracked Python file belongs to the production scope."""

    if relative_path.suffix != ".py":
        return False

    parts = relative_path.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_TOP_LEVEL_DIRS:
        return False
    if "tests" in parts:
        return False
    if any(part.startswith(".") for part in parts[:-1]):
        return False

    filename = relative_path.name
    if filename == "conftest.py":
        return False
    if filename.startswith("test_") or filename.endswith("_test.py"):
        return False
    return True


def _run_git(repo_root: Path, *args: str) -> str:
    safe_repo_root = str(repo_root.resolve())
    completed = subprocess.run(
        [
            resolve_required_executable("git"),
            "-c",
            f"safe.directory={safe_repo_root}",
            *args,
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def list_vulture_targets(repo_root: Path) -> list[str]:
    """List tracked Python files that belong to the Vulture production scope."""

    tracked_files = _run_git(repo_root, "ls-files", "--", TRACKED_PYTHON_PATHSPEC)
    targets = [
        relative_path
        for relative_path in tracked_files.splitlines()
        if is_vulture_target(PurePosixPath(relative_path))
    ]
    if not targets:
        raise RuntimeError(
            "No tracked production Python files matched the Vulture scope."
        )
    return targets


def build_vulture_command(paths: list[str], *, min_confidence: int) -> list[str]:
    """Build the Vulture command for the given tracked paths."""

    return [
        sys.executable,
        "-m",
        "vulture",
        "--min-confidence",
        str(min_confidence),
        *paths,
    ]


def run_vulture(repo_root: Path, paths: list[str], *, min_confidence: int) -> int:
    """Run Vulture from the repository root."""

    command = build_vulture_command(paths, min_confidence=min_confidence)
    completed = subprocess.run(command, cwd=repo_root, check=False)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Vulture against tracked production Python files only."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root containing the tracked Python files.",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=DEFAULT_MIN_CONFIDENCE,
        help=f"Vulture minimum confidence threshold. Defaults to {DEFAULT_MIN_CONFIDENCE}.",
    )
    parser.add_argument(
        "--print-files",
        action="store_true",
        help="Print the tracked production Python files that Vulture will scan.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    targets = list_vulture_targets(repo_root)
    if args.print_files:
        sys.stdout.write("\n".join(targets) + "\n")
        return 0
    return run_vulture(repo_root, targets, min_confidence=args.min_confidence)


if __name__ == "__main__":
    raise SystemExit(main())
