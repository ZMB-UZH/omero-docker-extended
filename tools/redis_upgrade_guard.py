"""Refuse to stop an installation whose Redis data would not survive the upgrade."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*")
_INSPECT_FORMAT = (
    '{"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"directory":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},'
    '"mounts":{{json .Mounts}},"tmpfs":{{json .HostConfig.Tmpfs}}}'
)


class UpgradeError(RuntimeError):
    """A preflight refusal that is safe to display without Docker output."""


def _docker_output(executable: str, *arguments: str) -> str:
    """Read bounded Docker output without relaying daemon diagnostics.

    Inputs: absolute Docker path and read-only command arguments.
    Output: stdout as text or a sanitized inspection error.
    """
    try:
        return subprocess.run(
            [executable, *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise UpgradeError("Could not inspect Redis storage through Docker.") from None


def _redis_containers() -> list[dict[str, object]]:
    """Inspect only ownership and storage metadata for Compose Redis services.

    Inputs: local Docker context. Output: validated container metadata records.
    """
    path = os.pathsep.join(part for part in os.get_exec_path() if os.path.isabs(part))
    executable = shutil.which("docker", path=path)
    if executable is None:
        raise UpgradeError(
            "Docker is required to verify Redis storage before stopping services."
        )

    ids = _docker_output(
        executable,
        "container",
        "ls",
        "--all",
        "--no-trunc",
        "--filter",
        "label=com.docker.compose.service=redis",
        "--format",
        "{{.ID}}",
    ).splitlines()
    if not ids:
        return []
    if len(set(ids)) != len(ids) or not all(
        _CONTAINER_ID.fullmatch(cid) for cid in ids
    ):
        raise UpgradeError("Docker returned an invalid Redis container inventory.")
    response = _docker_output(
        executable, "container", "inspect", "--format", _INSPECT_FORMAT, *ids
    )
    try:
        records = [json.loads(line) for line in response.splitlines()]
    except ValueError:
        raise UpgradeError(
            "Docker returned unreadable Redis storage metadata."
        ) from None
    if len(records) != len(ids) or not all(isinstance(row, dict) for row in records):
        raise UpgradeError("Docker returned incomplete Redis storage metadata.")
    return records


def check_storage(project: str, installation: Path, previous: Path) -> None:
    """Refuse an upgrade when the existing Redis state would not be retained.

    Inputs: destination Compose project, destination root, and previous root.
    Output: no changes; raises when ownership or persistence is not proven.
    """
    if not _PROJECT.fullmatch(project):
        raise UpgradeError("Invalid destination Compose project name.")
    inherited_project = os.environ.get("COMPOSE_PROJECT_NAME")
    if inherited_project and inherited_project != project:
        raise UpgradeError(
            "Unset the conflicting COMPOSE_PROJECT_NAME before upgrading."
        )

    roots = {installation.resolve(), previous.resolve()}
    matching: list[dict[str, object]] = []
    for record in _redis_containers():
        directory = record.get("directory")
        owner = record.get("project")
        if (
            not isinstance(owner, str)
            or not isinstance(directory, str)
            or "\0" in directory
        ):
            raise UpgradeError("Docker returned incomplete Redis ownership metadata.")
        belongs_to_root = (
            Path(directory).is_absolute() and Path(directory).resolve() in roots
        )
        if owner == project and not belongs_to_root:
            raise UpgradeError(
                "Another installation uses the destination Compose project name."
            )
        if belongs_to_root:
            matching.append(record)
    if len(matching) > 1:
        raise UpgradeError(
            "Multiple Redis services match the installation; resolve their ownership first."
        )
    if not matching:
        return

    redis = matching[0]
    mounts = redis.get("mounts")
    tmpfs = redis.get("tmpfs")
    if not isinstance(mounts, list) or (
        tmpfs is not None and not isinstance(tmpfs, dict)
    ):
        raise UpgradeError("Docker returned incomplete Redis mount metadata.")
    data_mounts = [
        m for m in mounts if isinstance(m, dict) and m.get("Destination") == "/data"
    ]
    if (
        redis["project"] != project
        or (
            tmpfs is not None
            and any(path == "/data" or path.startswith("/data/") for path in tmpfs)
        )
        or any(
            isinstance(mount, dict)
            and isinstance(destination := mount.get("Destination"), str)
            and destination.startswith("/data/")
            for mount in mounts
        )
        or len(data_mounts) != 1
        or data_mounts[0].get("Type") != "volume"
        or data_mounts[0].get("Name") != f"{project}_redis-data"
        or data_mounts[0].get("RW") is not True
    ):
        raise UpgradeError(
            "Redis does not use the destination project's persistent data volume. "
            "Migrate its state before stopping or replacing it. "
            "See docs/operations/redis-persistence.md."
        )


def main(argv: list[str] | None = None) -> int:
    """Run the read-only check without disclosing deployment metadata.

    Inputs: CLI options for project and roots. Output: 0 if safe, 1 on refusal.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--installation", required=True, type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_storage(args.project, args.installation, args.previous)
    except (OSError, RuntimeError) as exc:
        message = (
            str(exc)
            if isinstance(exc, UpgradeError)
            else "Could not resolve Redis storage ownership."
        )
        print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Redis upgrade storage check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
