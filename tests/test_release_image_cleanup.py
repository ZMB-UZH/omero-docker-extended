"""Release-builder cleanup contracts without touching a Docker daemon."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from tools import prune_non_required_docker_images as cleanup


def result(stdout="", stderr="", status=0):
    """Inputs: Docker response fields. Output: deterministic subprocess result."""
    return subprocess.CompletedProcess([], status, stdout, stderr)


def test_default_runner_preserves_argument_boundaries(monkeypatch):
    """Inputs: exact Docker arguments. Output: direct argv execution without a shell."""
    run = Mock(return_value=result())
    monkeypatch.setattr(cleanup.shutil, "which", lambda _name: "/fixture/docker")
    monkeypatch.setattr(cleanup.subprocess, "run", run)
    cleanup.default_docker_runner(["image", "ls"])
    run.assert_called_once_with(
        ["/fixture/docker", "image", "ls"], check=False, capture_output=True, text=True
    )
    monkeypatch.setattr(cleanup.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="executable is required"):
        cleanup.default_docker_runner(["image", "ls"])


@pytest.mark.parametrize(
    "payload",
    [
        "broken",
        "null",
        "[]",
        '{"Repository":4,"Tag":"x"}',
        '{"Repository":"r","Tag":"x","ID":7}',
        '{"Repository":"r","Tag":"x"}',
    ],
)
def test_malformed_inventory_cannot_reach_deletion(tmp_path, monkeypatch, payload):
    """Inputs: malformed daemon inventory. Output: controlled error and no destructive call."""
    inventory = tmp_path / "required.txt"
    inventory.write_text("example.test/required:1\n")
    runner = Mock(side_effect=[result("sha256:required"), result(payload)])
    monkeypatch.setattr(cleanup, "default_docker_runner", runner)
    assert cleanup.main(["--required-images-file", str(inventory), "--execute"]) == 1
    assert runner.call_count == 2
    assert all(call.args[0][1] in {"inspect", "ls"} for call in runner.call_args_list)


def test_inventory_skips_unnamed_rows_and_keeps_required_aliases():
    """Inputs: mixed image inventory. Output: aliases of required IDs remain protected."""
    runner = Mock(
        side_effect=[result("sha256:required"), result(status=1), result(" ")]
    )
    ids = cleanup.inspect_present_required_image_ids(
        ["required:1", "absent:2", "empty:3"], runner
    )
    assert ids == {"sha256:required"}
    rows = [
        {"Repository": "required", "Tag": "1", "ID": "sha256:required"},
        {"Repository": "alias", "Tag": "2", "ID": "sha256:required"},
        {"Repository": "obsolete", "Tag": "3", "ID": "sha256:old"},
        {"Repository": "<none>", "Tag": "<none>", "ID": "sha256:dangling"},
    ]
    listed = cleanup.list_named_local_images(
        Mock(return_value=result("\n" + "\n".join(json.dumps(row) for row in rows)))
    )
    assert len(listed) == 3
    assert cleanup.removable_image_references(
        required_images=["required:1"], local_images=listed, required_image_ids=ids
    ) == ["obsolete:3"]
    with pytest.raises(RuntimeError, match="listing failed"):
        cleanup.list_named_local_images(
            Mock(return_value=result(stderr="listing failed", status=1))
        )


@pytest.mark.parametrize("failure", ["remove", "dangling"])
def test_cleanup_stops_at_first_daemon_failure(failure):
    """Inputs: removal or dangling-prune failure. Output: no later destructive operations."""
    replies = (
        [result(stderr="busy", status=1)]
        if failure == "remove"
        else [result(), result(stdout="busy", status=1)]
    )
    runner = Mock(side_effect=replies)
    with pytest.raises(RuntimeError, match="busy"):
        cleanup.prune_images(["obsolete:1"], runner)
    assert runner.call_count == len(replies)
    assert runner.call_args_list[0].args[0] == ["image", "rm", "obsolete:1"]
    if failure == "dangling":
        assert runner.call_args_list[1].args[0] == ["image", "prune", "--force"]


@pytest.mark.parametrize(
    ("execute", "old_image"), [(False, True), (True, True), (True, False)]
)
def test_cli_dry_run_and_execution_preserve_required_image(
    tmp_path, monkeypatch, capsys, execute, old_image
):
    """Inputs: required image and optional obsolete tag. Output: exact dry-run or deletion plan."""
    inventory = tmp_path / "required.txt"
    inventory.write_text("required:1\nrequired:1\n\n")
    rows = [{"Repository": "required", "Tag": "1", "ID": "sha256:required"}]
    if old_image:
        rows.append({"Repository": "obsolete", "Tag": "1", "ID": "sha256:old"})
    calls = []

    def docker(args):
        """Inputs: Docker arguments. Output: exact fixture inventory or recorded cleanup."""
        calls.append(args)
        if args[1] == "inspect":
            return result("sha256:required")
        if args[1] == "ls":
            return result("\n".join(json.dumps(row) for row in rows))
        return result()

    monkeypatch.setattr(cleanup, "default_docker_runner", docker)
    args = ["--required-images-file", str(inventory)] + (
        ["--execute"] if execute else []
    )
    assert cleanup.main(args) == 0
    destructive = calls[2:]
    assert destructive == (
        ([["image", "rm", "obsolete:1"]] if old_image else [])
        + [["image", "prune", "--force"]]
        if execute
        else []
    )
    assert "Required image references: 1" in capsys.readouterr().out
