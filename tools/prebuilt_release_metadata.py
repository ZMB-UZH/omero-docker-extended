#!/usr/bin/env python3
"""Resolve release metadata for the prebuilt carrier workflow."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[a-z-][0-9a-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[a-z-][0-9a-z-]*))*))?$"
)
DOCKER_HUB_REPOSITORY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*/[a-z0-9]+(?:[._-][a-z0-9]+)*$"
)
BETA_PATTERN = re.compile(r"^beta\.([1-9][0-9]*)$")


@dataclass(frozen=True)
class SemVer:
    """Parsed Docker-compatible SemVer release value."""

    major: int
    minor: int
    patch: int
    prerelease: str | None


def parse_release_version(value: str) -> SemVer:
    """Parse a Docker-compatible release version.

    Inputs: `value`. Output: `SemVer`; raises `ValueError` for invalid tags.
    """
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            "Release version must be Docker-compatible SemVer without a v "
            "prefix or +build metadata, for example 0.1.0-beta.1."
        )
    return SemVer(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=match.group(4),
    )


def is_valid_release_version(value: str) -> bool:
    """Return whether a release value is safe for the release workflow.

    Inputs: `value`. Output: `bool`.
    """
    try:
        validate_release_version(value)
    except ValueError:
        return False
    return True


def validate_release_version(value: str) -> str:
    """Validate a release version string.

    Inputs: `value`. Output: normalized `str`; raises `ValueError` on failure.
    """
    if value == "latest" or value.endswith(":latest"):
        raise ValueError("Release version must not be latest.")
    parse_release_version(value)
    return value


def validate_docker_repository(value: str) -> str:
    """Validate a Docker Hub namespace and repository.

    Inputs: `value`. Output: repository `str`; raises `ValueError` on failure.
    """
    if DOCKER_HUB_REPOSITORY_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "Docker repository must be a lower-case Docker Hub namespace/repository."
        )
    return value


def semver_sort_key(version: SemVer) -> tuple[int, int, int, int, int, str]:
    """Return ordering data for supported release values.

    Inputs: `version`. Output: tuple usable as a deterministic sort key.
    """
    if version.prerelease is None:
        return (version.major, version.minor, version.patch, 2, 0, "")

    beta_match = BETA_PATTERN.fullmatch(version.prerelease)
    if beta_match is not None:
        return (
            version.major,
            version.minor,
            version.patch,
            1,
            int(beta_match.group(1)),
            "",
        )

    return (version.major, version.minor, version.patch, 0, 0, version.prerelease)


def next_beta_release_version(existing_tags: Sequence[str]) -> str:
    """Choose the next beta release tag from remote tags.

    Inputs: `existing_tags`. Output: Docker-compatible SemVer prerelease tag.
    """
    versions: list[SemVer] = []
    for tag in existing_tags:
        try:
            versions.append(parse_release_version(tag))
        except ValueError:
            continue

    if not versions:
        return "0.1.0-beta.1"

    latest = max(versions, key=semver_sort_key)
    if latest.prerelease is not None:
        beta_match = BETA_PATTERN.fullmatch(latest.prerelease)
        if beta_match is not None:
            return (
                f"{latest.major}.{latest.minor}.{latest.patch}-"
                f"beta.{int(beta_match.group(1)) + 1}"
            )

    return f"{latest.major}.{latest.minor}.{latest.patch + 1}-beta.1"


def list_remote_tags(repo_root: Path) -> list[str]:
    """List release tags from the `origin` remote.

    Inputs: `repo_root`. Output: sorted tag names from the remote repository.
    """
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is required to list remote release tags.")
    result = subprocess.run(
        [git, "ls-remote", "--tags", "origin"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tags = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        tag_ref = line.rsplit("/", 1)[-1].removesuffix("^{}")
        tags.add(tag_ref)
    return sorted(tags)


def resolve_release_metadata(
    *,
    requested_version: str,
    requested_docker_repository: str,
    default_docker_repository: str,
    existing_tags: Sequence[str],
) -> tuple[str, str, str]:
    """Resolve release metadata for GitHub and Docker.

    Inputs: requested values, defaults, and existing tags. Output: release, repo,
    and carrier image reference.
    """
    release_version = (
        validate_release_version(requested_version.strip())
        if requested_version.strip()
        else next_beta_release_version(existing_tags)
    )
    docker_repository = validate_docker_repository(
        requested_docker_repository.strip() or default_docker_repository
    )
    return release_version, docker_repository, f"{docker_repository}:{release_version}"


def write_github_env(path: Path, values: dict[str, str]) -> None:
    """Write resolved metadata to a GitHub Actions env file.

    Inputs: `path`, `values`. Output: appends key-value lines to the file.
    """
    with path.open("a", encoding="utf-8") as env_file:
        for key, value in values.items():
            env_file.write(f"{key}={value}\n")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse release metadata command-line options.

    Inputs: `argv`. Output: parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(
        description="Resolve prebuilt carrier release metadata."
    )
    parser.add_argument("--validate-release-version", default=None)
    parser.add_argument("--requested-version", default="")
    parser.add_argument("--requested-docker-repository", default="")
    parser.add_argument("--default-docker-repository", default="")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--github-env", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run release metadata resolution.

    Inputs: optional `argv`. Output: process exit code.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.validate_release_version is not None:
            validate_release_version(args.validate_release_version)
            return 0
        if not args.default_docker_repository:
            raise ValueError("--default-docker-repository is required.")
        release_version, docker_repository, carrier_image = resolve_release_metadata(
            requested_version=args.requested_version,
            requested_docker_repository=args.requested_docker_repository,
            default_docker_repository=args.default_docker_repository,
            existing_tags=list_remote_tags(args.repo_root),
        )
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    values = {
        "RELEASE_VERSION": release_version,
        "DOCKER_REPOSITORY": docker_repository,
        "CARRIER_IMAGE": carrier_image,
    }

    github_env = args.github_env or (
        Path(os.environ["GITHUB_ENV"]) if "GITHUB_ENV" in os.environ else None
    )
    if github_env is not None:
        write_github_env(github_env, values)

    print(f"Release version: {release_version}")
    print(f"Carrier image: {carrier_image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
