"""Exercise configuration recovery against real filesystem failure boundaries."""

import os
from pathlib import Path

import pytest

from tools import env_safety_guard as guard


def make_backup(tmp_path: Path) -> tuple[Path, Path]:
    """Inputs: a private fixture root. Output: deployment and differing backup paths."""
    repo = tmp_path / "deployment"
    backup = repo / guard.BACKUP_DIR_NAME / "snapshot"
    backup.mkdir(parents=True)
    (repo / "settings.env").write_bytes(b"CURRENT=retained\n")
    (backup / "settings.env").write_bytes(b"PREVIOUS=restored\n")
    return repo, backup


@pytest.mark.parametrize("kind", ["file-link", "directory-link", "fifo"])
def test_invalid_backup_entry_does_not_partially_restore(tmp_path, kind):
    """Inputs: unsafe backup entries. Output: failure without deployment mutation."""
    repo, backup = make_backup(tmp_path)
    entry = backup / "z-invalid"
    if kind == "file-link":
        entry.symlink_to(repo / "settings.env")
    elif kind == "directory-link":
        entry.symlink_to(repo, target_is_directory=True)
    else:
        os.mkfifo(entry)

    assert guard.cmd_restore(repo, "snapshot") == 1
    assert (repo / "settings.env").read_bytes() == b"CURRENT=retained\n"
    assert not (repo / "z-invalid").exists()


@pytest.mark.parametrize("linked", ["root", "snapshot"])
@pytest.mark.parametrize("explicit", [False, True])
def test_restore_rejects_symlinked_backup_directories(tmp_path, linked, explicit):
    """Inputs: linked backup roots or snapshots. Output: fail-closed assertions."""
    repo, backup = make_backup(tmp_path)
    source = backup.parent if linked == "root" else backup
    moved = tmp_path / "external-backup"
    source.rename(moved)
    source.symlink_to(moved, target_is_directory=True)

    assert guard.cmd_restore(repo, "snapshot" if explicit else None) == 1
    assert (repo / "settings.env").read_bytes() == b"CURRENT=retained\n"


def test_restore_preserves_operator_owned_environment_symlink(tmp_path):
    """Inputs: a linked deployment env file. Output: restored bytes, retained link."""
    repo, _backup = make_backup(tmp_path)
    target = tmp_path / "canonical.env"
    (repo / "settings.env").rename(target)
    (repo / "settings.env").symlink_to(target)

    assert guard.cmd_restore(repo, "snapshot") == 0
    assert (repo / "settings.env").is_symlink()
    assert target.read_bytes() == b"PREVIOUS=restored\n"


def test_restore_rejects_nonregular_destination_before_copying(tmp_path):
    """Inputs: an incompatible destination. Output: no earlier file is overwritten."""
    repo, backup = make_backup(tmp_path)
    (backup / "z-directory.env").write_bytes(b"CONFIG=previous\n")
    (repo / "z-directory.env").mkdir()

    assert guard.cmd_restore(repo, "snapshot") == 1
    assert (repo / "settings.env").read_bytes() == b"CURRENT=retained\n"
    assert list((repo / "z-directory.env").iterdir()) == []


@pytest.mark.parametrize("kind", ["file", "dangling-link"])
def test_restore_rejects_invalid_parent_before_copying(tmp_path, kind):
    """Inputs: unusable destination parents. Output: no partial configuration restore."""
    repo, backup = make_backup(tmp_path)
    (backup / "z-parent").mkdir()
    (backup / "z-parent/settings.env").write_bytes(b"PREVIOUS=value\n")
    if kind == "file":
        (repo / "z-parent").write_bytes(b"preserve\n")
    else:
        (repo / "z-parent").symlink_to(tmp_path / "absent", target_is_directory=True)

    assert guard.cmd_restore(repo, "snapshot") == 1
    assert (repo / "settings.env").read_bytes() == b"CURRENT=retained\n"


def test_restore_reports_unreadable_subtree_before_copying(tmp_path, monkeypatch):
    """Inputs: a failed directory read. Output: reported failure without mutation."""
    repo, backup = make_backup(tmp_path)
    (backup / "nested").mkdir()
    scandir = guard.os.scandir

    def unreadable(path):
        """Inputs: a walk path. Output: real entries, or an injected I/O failure."""
        if Path(path) == backup / "nested":
            raise PermissionError("Synthetic unreadable backup directory")
        return scandir(path)

    monkeypatch.setattr(guard.os, "scandir", unreadable)
    assert guard.cmd_restore(repo, "snapshot") == 1
    assert (repo / "settings.env").read_bytes() == b"CURRENT=retained\n"
