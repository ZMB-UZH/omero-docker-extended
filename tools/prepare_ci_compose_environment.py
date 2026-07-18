#!/usr/bin/env python3
"""Prepare deployment environment contracts in an ephemeral Linux CI checkout."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.env_safety_guard import (
    ENV_TEMPLATE_PAIRS,
    parse_active_env_assignments,
    resolve_env_references,
)

DOT_ENV_TEMPLATE_PAIR = (".env_example", ".env")
COMPOSE_PROFILES_KEY = "COMPOSE_PROFILES"
INSTALLATION_PATH_KEY = "OMERO_INSTALLATION_PATH"
PRIVATE_FILE_MODE = 0o600
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CiComposeEnvironmentError(RuntimeError):
    """Raised when synthetic CI environment preparation cannot finish safely."""


def _contract_pairs(root: Path) -> tuple[tuple[Path, Path], ...]:
    """Return tracked examples paired with ignored runtime paths.

    Inputs: `root` repository path. Output: absolute source and target pairs.
    """
    relative_pairs = (DOT_ENV_TEMPLATE_PAIR, *ENV_TEMPLATE_PAIRS)
    return tuple((root / source, root / target) for source, target in relative_pairs)


def _copy_contract_exclusively(source: Path, target: Path) -> None:
    """Copy one environment contract through exclusive POSIX descriptors.

    Inputs: `source` regular file and absent `target`. Output: private target file.
    """
    try:
        source_descriptor = os.open(
            source,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise CiComposeEnvironmentError(
            f"Missing environment contract: {source}"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(source_descriptor).st_mode):
            raise CiComposeEnvironmentError(
                f"Environment contract is not a regular file: {source}"
            )
        with os.fdopen(source_descriptor, "rb") as source_file:
            source_descriptor = -1
            source_bytes = source_file.read()
    except OSError as exc:
        raise CiComposeEnvironmentError(
            f"Could not read environment contract: {source}"
        ) from exc
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            PRIVATE_FILE_MODE,
        )
    except FileExistsError as exc:
        raise CiComposeEnvironmentError(
            f"Refusing to overwrite existing deployment environment file: {target}"
        ) from exc
    try:
        with os.fdopen(file_descriptor, "wb") as target_file:
            target_file.write(source_bytes)
            target_file.flush()
            os.fsync(target_file.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _load_environment_values(pairs: Sequence[tuple[Path, Path]]) -> dict[str, str]:
    """Load active assignments using the deployment file precedence order.

    Inputs: prepared source-target `pairs`. Output: validated environment values.
    """
    values: dict[str, str] = {}
    for _source, target in pairs:
        try:
            for raw_line in target.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
                if not ENV_KEY_PATTERN.fullmatch(key):
                    raise CiComposeEnvironmentError(
                        f"Invalid environment key in {target}: {key}"
                    )
            values.update(parse_active_env_assignments(target))
        except (OSError, ValueError) as exc:
            raise CiComposeEnvironmentError(
                f"Invalid synthetic environment contract: {target}"
            ) from exc
    return values


def _resolve_environment_values(root: Path, values: dict[str, str]) -> dict[str, str]:
    """Resolve template references against the synthetic installation root.

    Inputs: repository `root` and raw `values`. Output: fully resolved values.
    """
    resolved_values = dict(values)
    resolved_values[INSTALLATION_PATH_KEY] = str(root.resolve())
    for key, value in tuple(resolved_values.items()):
        try:
            resolved_values[key] = resolve_env_references(value, resolved_values)
        except ValueError as exc:
            raise CiComposeEnvironmentError(
                f"Unsafe synthetic environment value for {key}: {exc}"
            ) from exc
    unresolved_names = sorted(
        key for key, value in resolved_values.items() if "${" in value
    )
    if unresolved_names:
        raise CiComposeEnvironmentError(
            "Unresolved synthetic environment reference(s): "
            + ", ".join(unresolved_names)
        )
    return resolved_values


def _discover_compose_profiles(
    root: Path,
    values: dict[str, str],
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    """Discover profiles from the rendered Compose project.

    Inputs: repository `root`, resolved `values`, and command runner. Output:
    sorted profile names.
    """
    try:
        completed = run_command(
            ["docker", "compose", "-f", "docker-compose.yml", "config", "--profiles"],
            cwd=root,
            env={**os.environ, **values},
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CiComposeEnvironmentError(
            "Could not discover Compose profiles from the synthetic environment."
        ) from exc
    profiles = tuple(
        sorted({line.strip() for line in completed.stdout.splitlines() if line.strip()})
    )
    if not profiles:
        raise CiComposeEnvironmentError(
            "No Compose profiles discovered for CI validation."
        )
    return profiles


def _append_github_environment(path: Path, values: dict[str, str]) -> None:
    """Append resolved values to the private GitHub environment channel.

    Inputs: regular-file `path` and resolved `values`. Output: appended entries.
    """
    entries: list[str] = []
    for key, value in sorted(values.items()):
        marker = f"OMERO_ENV_{key}_{uuid.uuid4().hex}"
        if marker in value:
            raise CiComposeEnvironmentError(
                f"Could not encode synthetic environment value for {key}."
            )
        entries.append(f"{key}<<{marker}\n{value}\n{marker}\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_APPEND
            | os.O_CREAT
            | os.O_CLOEXEC
            | os.O_NOFOLLOW
            | os.O_NONBLOCK,
            PRIVATE_FILE_MODE,
        )
    except OSError as exc:
        raise CiComposeEnvironmentError(
            f"Could not safely open the GitHub environment file: {path}"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise CiComposeEnvironmentError(
                f"GitHub environment path is not a regular file: {path}"
            )
        os.fchmod(file_descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(
            file_descriptor, "a", encoding="utf-8", newline="\n"
        ) as environment_file:
            file_descriptor = -1
            environment_file.write("".join(entries))
            environment_file.flush()
            os.fsync(environment_file.fileno())
    except OSError as exc:
        raise CiComposeEnvironmentError(
            f"Could not write the GitHub environment file: {path}"
        ) from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def prepare_ci_compose_environment(
    root: Path,
    github_environment_path: Path,
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    """Prepare the complete synthetic deployment environment.

    Inputs: repository `root`, GitHub environment path, and command runner.
    Output: resolved values after private runtime files and profiles are prepared.
    """
    root = root.resolve()
    pairs = _contract_pairs(root)
    created: list[Path] = []
    try:
        missing_sources = [
            str(source) for source, _target in pairs if not source.is_file()
        ]
        if missing_sources:
            raise CiComposeEnvironmentError(
                "Missing environment contract(s): " + ", ".join(missing_sources)
            )
        existing_targets = [str(target) for _source, target in pairs if target.exists()]
        if existing_targets:
            raise CiComposeEnvironmentError(
                "Refusing to overwrite existing deployment environment file(s): "
                + ", ".join(existing_targets)
            )
        for source, target in pairs:
            _copy_contract_exclusively(source, target)
            created.append(target)
        values = _resolve_environment_values(root, _load_environment_values(pairs))
        profiles = _discover_compose_profiles(root, values, run_command=run_command)
        values[COMPOSE_PROFILES_KEY] = ",".join(profiles)
        _append_github_environment(github_environment_path, values)
    except Exception:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return values


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface.

    Inputs: none. Output: configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Prepare synthetic Docker Compose environment files in Linux CI."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--github-env",
        type=Path,
        default=os.environ.get("GITHUB_ENV"),
        help="GitHub Actions environment file (defaults to GITHUB_ENV).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run synthetic environment preparation from the command line.

    Inputs: optional `argv` sequence. Output: zero after successful preparation.
    """
    args = _build_parser().parse_args(argv)
    if args.github_env is None:
        raise CiComposeEnvironmentError("GITHUB_ENV or --github-env is required.")
    values = prepare_ci_compose_environment(args.root, Path(args.github_env))
    print(
        f"Prepared {len(_contract_pairs(args.root.resolve()))} synthetic CI "
        f"environment files with {len(values)} resolved values."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
