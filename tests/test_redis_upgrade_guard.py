"""Verify that installer shutdown cannot discard existing Redis state."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import redis_upgrade_guard as guard


def storage(root: Path, **changes: object) -> dict[str, object]:
    """Build a realistic Redis metadata record for storage checks.

    Inputs: Compose working directory and field overrides. Output: Docker facts.
    """
    return {
        "project": "microscopy",
        "directory": str(root),
        "tmpfs": None,
        "mounts": [
            {
                "Destination": "/data",
                "Type": "volume",
                "Name": "microscopy_redis-data",
                "RW": True,
            }
        ],
        **changes,
    }


@pytest.fixture(autouse=True)
def clear_project_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the tests from a Compose project exported by the test runner.

    Inputs: environment patch fixture. Output: project override unset for each test.
    """
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)


@pytest.mark.parametrize("state", ("fresh", "persistent", "relocated", "unrelated"))
def test_storage_without_data_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """Accept fresh and persistent installations without modifying storage.

    Inputs: owned or unrelated Redis records. Output: permitted preflight.
    """
    root = tmp_path / "new"
    previous = tmp_path / "previous"
    rows = {
        "fresh": [],
        "persistent": [storage(root)],
        "relocated": [storage(previous)],
        "unrelated": [
            storage(tmp_path / "elsewhere", project="independent", mounts=[])
        ],
    }[state]
    monkeypatch.setattr(guard, "_redis_containers", lambda: rows)
    guard.check_storage("microscopy", root, previous)


@pytest.mark.parametrize(
    "changes",
    [
        {"mounts": [], "tmpfs": {"/data": "size=64m"}},
        {"mounts": [{"Destination": "/data", "Type": "tmpfs", "RW": True}]},
        {"mounts": [{"Destination": "/data", "Type": "bind", "RW": True}]},
        {
            "mounts": [
                {
                    "Destination": "/data",
                    "Type": "volume",
                    "Name": "old_redis-data",
                    "RW": True,
                }
            ]
        },
        {
            "mounts": [
                {
                    "Destination": "/data",
                    "Type": "volume",
                    "Name": "microscopy_redis-data",
                    "RW": False,
                }
            ]
        },
        {"tmpfs": {"/data/appendonlydir": "size=64m"}},
        {"project": "legacy"},
    ],
)
def test_refuse_legacy_or_unusable_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, object]
) -> None:
    """Require verified writable storage that the upgraded project will reuse.

    Inputs: unsupported metadata variations. Output: migration-required refusal.
    """
    old = tmp_path / "old"
    monkeypatch.setattr(guard, "_redis_containers", lambda: [storage(old, **changes)])
    with pytest.raises(guard.UpgradeError, match="Migrate its state"):
        guard.check_storage("microscopy", tmp_path / "new", old)


def test_refuse_nested_mount_even_with_persistent_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a nested mount that could hide part of Redis persistence.

    Inputs: named data volume with a nested tmpfs. Output: upgrade refusal.
    """
    row = storage(tmp_path)
    mounts = row["mounts"]
    assert isinstance(mounts, list)
    mounts.append({"Destination": "/data/appendonlydir", "Type": "tmpfs"})
    monkeypatch.setattr(guard, "_redis_containers", lambda: [row])
    with pytest.raises(guard.UpgradeError, match="Migrate its state"):
        guard.check_storage("microscopy", tmp_path, tmp_path)


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        ([{"project": "microscopy", "directory": None}], "ownership metadata"),
        (
            [{"project": "microscopy", "directory": "/different/deployment"}],
            "Another installation",
        ),
    ],
)
def test_refuse_unverified_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    error: str,
) -> None:
    """Keep the upgrade from acting on missing or conflicting ownership.

    Inputs: malformed or unrelated ownership record. Output: matching refusal.
    """
    monkeypatch.setattr(guard, "_redis_containers", lambda: rows)
    with pytest.raises(guard.UpgradeError, match=error):
        guard.check_storage("microscopy", tmp_path, tmp_path)


def test_reject_parallel_matching_deployments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse to choose between matching old and destination Redis services.

    Inputs: two matching Compose roots. Output: ambiguous ownership error.
    """
    old = tmp_path / "old"
    monkeypatch.setattr(
        guard,
        "_redis_containers",
        lambda: [storage(tmp_path), storage(old, project="old")],
    )
    with pytest.raises(guard.UpgradeError, match="Multiple Redis"):
        guard.check_storage("microscopy", tmp_path, old)


def test_reject_malformed_mount_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a Redis service without a usable mount inventory.

    Inputs: null mount list for the matched service. Output: explicit refusal.
    """
    monkeypatch.setattr(
        guard, "_redis_containers", lambda: [storage(tmp_path, mounts=None)]
    )
    with pytest.raises(guard.UpgradeError, match="mount metadata"):
        guard.check_storage("microscopy", tmp_path, tmp_path)


def test_reject_invalid_or_conflicting_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require one project name consistent with the process environment.

    Inputs: invalid name and conflicting override. Output: distinct refusals.
    """
    with pytest.raises(guard.UpgradeError, match="Invalid destination"):
        guard.check_storage("Microscopy", tmp_path, tmp_path)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "different")
    with pytest.raises(guard.UpgradeError, match="conflicting COMPOSE_PROJECT_NAME"):
        guard.check_storage("microscopy", tmp_path, tmp_path)


@pytest.mark.parametrize(
    ("inventory", "inspection", "message"),
    [
        ("", "", ""),
        ("not-an-id\n", "", "invalid Redis container inventory"),
        (f"{'a' * 64}\n", "{invalid", "unreadable Redis storage metadata"),
        (f"{'a' * 64}\n", "[]\n", "incomplete Redis storage metadata"),
    ],
)
def test_docker_inventory_boundaries(
    monkeypatch: pytest.MonkeyPatch, inventory: str, inspection: str, message: str
) -> None:
    """Handle empty Docker inventories without accepting corrupt metadata.

    Inputs: listing and inspection responses. Output: empty list or bounded error.
    """
    monkeypatch.setattr(guard.shutil, "which", lambda *_args, **_kwargs: "/test/docker")
    docker = Mock(side_effect=[inventory, inspection])
    monkeypatch.setattr(guard, "_docker_output", docker)
    if message:
        with pytest.raises(guard.UpgradeError, match=message):
            guard._redis_containers()
    else:
        assert guard._redis_containers() == []
        assert docker.call_count == 1


def test_only_read_only_selected_metadata_is_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep Redis preflight inspection targeted and free of environment reads.

    Inputs: one Compose Redis container. Output: bounded read-only Docker calls.
    """
    row = storage(tmp_path)
    monkeypatch.setattr(guard.shutil, "which", lambda *_args, **_kwargs: "/test/docker")
    identity = "f" * 64
    fake = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, identity + "\n", ""),
            subprocess.CompletedProcess([], 0, json.dumps(row) + "\n", ""),
        ]
    )
    monkeypatch.setattr(guard.subprocess, "run", fake)
    assert guard._redis_containers() == [row]
    listing, inspect = [call.args[0] for call in fake.call_args_list]
    assert listing[:4] == ["/test/docker", "container", "ls", "--all"]
    assert inspect[:3] == ["/test/docker", "container", "inspect"]
    assert (
        listing[listing.index("--filter") + 1]
        == "label=com.docker.compose.service=redis"
    )
    assert inspect[-1] == identity
    assert ".Config.Env" not in inspect[-2]
    assert all(call.kwargs["timeout"] == 15 for call in fake.call_args_list)


def test_cli_docker_unavailable_or_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Make Docker discovery and inspection failures safe to display.

    Inputs: absent Docker and failing Docker with private stderr.
    Output: exit 1 and sanitized diagnostics for each failure.
    """
    args = [
        "--project",
        "microscopy",
        "--installation",
        str(tmp_path),
        "--previous",
        str(tmp_path),
    ]
    monkeypatch.setattr(guard.shutil, "which", lambda *_args, **_kwargs: None)
    assert guard.main(args) == 1
    assert "Docker is required" in capsys.readouterr().err
    monkeypatch.setattr(guard.shutil, "which", lambda *_args, **_kwargs: "/test/docker")
    monkeypatch.setattr(
        guard.subprocess,
        "run",
        Mock(
            side_effect=subprocess.CalledProcessError(
                1, "docker", stderr="arbitrary private daemon output"
            )
        ),
    )
    assert guard.main(args) == 1
    stderr = capsys.readouterr().err
    assert "Could not inspect Redis storage" in stderr
    assert "private daemon output" not in stderr


def test_cli_success_and_unexpected_path_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report success and failure without exposing installation details.

    Inputs: valid fixture and failing path resolution.
    Output: success first, then an error without the private path.
    """
    args = [
        "--project",
        "microscopy",
        "--installation",
        str(tmp_path),
        "--previous",
        str(tmp_path),
    ]
    monkeypatch.setattr(guard, "_redis_containers", lambda: [storage(tmp_path)])
    assert guard.main(args) == 0
    assert capsys.readouterr().out == "Redis upgrade storage check passed.\n"
    monkeypatch.setattr(
        guard.Path, "resolve", Mock(side_effect=OSError("private path"))
    )
    assert guard.main(args) == 1
    assert (
        capsys.readouterr().err == "ERROR: Could not resolve Redis storage ownership.\n"
    )


def test_installer_blocks_before_either_shutdown() -> None:
    """Pin the ordering that keeps live services safe during preflight.

    Inputs: tracked installer source. Output: guard and env setup precede shutdown.
    """
    installer = (
        Path(__file__).resolve().parents[1] / "installation/installation_script.sh"
    )
    source = installer.read_text()
    after_guard = source[source.index("/tools/redis_upgrade_guard.py") :]
    assert "exit 1\nfi" in after_guard[: after_guard.index("ensure_installation_path")]
    assert after_guard.index("write_compose_dot_env") < after_guard.index(
        "stop_old_installation_containers"
    )
    assert after_guard.index("stop_old_installation_containers") < after_guard.index(
        "down --remove-orphans"
    )
    assert 'find "${OMERO_USER_DATA_PATH}" -name "*.lock" -delete' not in source


@pytest.mark.parametrize("exit_status", [0, 17])
def test_previous_shutdown_is_scoped_and_failure_stops_upgrade(
    tmp_path: Path, exit_status: int
) -> None:
    """Keep an upgrade from proceeding after a failed previous-project stop.

    Inputs: previous Compose fixture and Docker stop status.
    Output: unchanged settings; continues only after a successful stop.
    """
    source = (
        Path(__file__).resolve().parents[1] / "installation/installation_script.sh"
    ).read_text()
    helper = source[
        source.index("stop_old_installation_containers()") : source.index(
            "# Root-only safety check"
        )
    ]
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    settings = tmp_path / ".env"
    settings.write_text("COMPOSE_PROJECT_NAME=legacy\n")
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            """
set -euo pipefail
EXIT_STATUS="$2"
docker() {
    if [ "$1" != compose ]; then
        echo "Unexpected Docker operation" >&2
        return 88
    fi
    return "$EXIT_STATUS"
}
"""
            + helper
            + """
OMERO_INSTALLATION_PATH="$1/new"
stop_old_installation_containers "$1" "$1/db" "$1/plugin" "$1/data" /OMERO 1
echo "Continue"
""",
            "fixture",
            str(tmp_path),
            str(exit_status),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == exit_status
    assert ("previous deployment did not stop successfully" in result.stderr) is bool(
        exit_status
    )
    assert "Unexpected Docker operation" not in result.stderr
    assert ("\nContinue\n" in result.stdout) is (exit_status == 0)
    assert settings.read_text() == "COMPOSE_PROJECT_NAME=legacy\n"


def test_failed_current_shutdown_does_not_continue(tmp_path: Path) -> None:
    """Require the current services to stop before continuing the upgrade.

    Inputs: failed Compose shutdown. Output: nonzero exit before subsequent work.
    """
    source = (
        Path(__file__).resolve().parents[1] / "installation/installation_script.sh"
    ).read_text()
    start = source.index('echo "Stopping existing containers..."')
    end = source.index('    echo "Removing ALL images', start)
    shutdown = source[start:end]
    opening = 'if [ "${KEEP_IMAGES}" -ne 1 ]; then\n'
    assert shutdown.endswith(opening)
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            """
set -euo pipefail
KEEP_IMAGES=0
COMPOSE_FILE="$1/docker-compose.yml"
compose_with_installation_env() {
    printf '%s\\n' "$@"
    return 17
}
"""
            + shutdown.removesuffix(opening)
            + '\necho "Continue"\n',
            "fixture",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout.splitlines()[-4:] == [
        "down",
        "--remove-orphans",
        "--rmi",
        "all",
    ]
    assert "current deployment did not stop successfully" in result.stderr
    assert "\nContinue\n" not in result.stdout


def test_entry_point(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Exercise the script entry point with an invalid project name.

    Inputs: synthetic CLI options. Output: nonzero exit rather than storage access.
    """
    monkeypatch.setattr(
        sys,
        "argv",
        [
            guard.__file__,
            "--project",
            "Wrong",
            "--installation",
            str(tmp_path),
            "--previous",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(guard.__file__, run_name="__main__")
    assert stopped.value.code == 1
