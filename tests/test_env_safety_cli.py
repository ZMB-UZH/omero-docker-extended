"""Real private-file tests for deployment configuration CLI safety contracts."""

import os
from pathlib import Path
import runpy
import secrets
import stat
import sys

import pytest

from tools import env_safety_guard as guard


@pytest.fixture
def deployment(tmp_path):
    """Inputs: private directory. Output: owned env fixtures and independently retained bytes."""
    values = {
        "env/web.env": f"CONFIG_VALUE={secrets.token_urlsafe(24)}\n".encode(),
        "installation_paths.env": b"# Preserve comments and blank lines\n\nSETTING=value\n",
    }
    (tmp_path / guard.MANIFEST_NAME).write_text(
        "\n".join(values) + "\n", encoding="utf-8"
    )
    for name, content in values.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    return tmp_path, values


@pytest.mark.parametrize("kind", ["directory", "fifo", "symlink-directory"])
def test_check_rejects_non_file_manifest_entries(deployment, capsys, kind):
    """Inputs: non-file configuration entry. Output: failure without reading a FIFO or leaking values."""
    root, values = deployment
    entry = root / "invalid.env"
    if kind == "directory":
        entry.mkdir()
    elif kind == "fifo":
        os.mkfifo(entry)
    else:
        entry.symlink_to(root / "env", target_is_directory=True)
    with (root / guard.MANIFEST_NAME).open("a", encoding="utf-8") as manifest:
        manifest.write("invalid.env\n")
    assert guard.main(["--repo-root", str(root), "check"]) == 1
    output = capsys.readouterr()
    assert "not regular files" in output.err
    assert "invalid.env" in output.err
    for content in values.values():
        assert content.decode() not in output.out + output.err


def test_backup_restore_round_trip_preserves_contents_modes_and_symlinks(
    deployment, capsys
):
    """Inputs: env files with an operator symlink. Output: exact restoration without replacing the link."""
    root, values = deployment
    target = root / "operator-owned.env"
    original = root / "env/web.env"
    original.rename(target)
    original.symlink_to(target)
    assert guard.main(["--repo-root", str(root), "check"]) == 0
    assert guard.main(["--repo-root", str(root), "backup"]) == 0
    backups_root = root / guard.BACKUP_DIR_NAME
    [backup] = backups_root.iterdir()
    assert stat.S_IMODE(backups_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert stat.S_IMODE((backup / "env").stat().st_mode) == 0o700
    for name, content in values.items():
        assert (backup / name).read_bytes() == content
        assert not (backup / name).is_symlink()
        (root / name).write_bytes(b"CHANGED=1\n")
    assert guard.main(["--repo-root", str(root), "list"]) == 0
    assert (
        guard.main(["--repo-root", str(root), "restore", "--backup-name", backup.name])
        == 0
    )
    assert original.is_symlink() and original.resolve() == target
    for name, content in values.items():
        assert (root / name).read_bytes() == content
        assert stat.S_IMODE((root / name).stat().st_mode) == 0o640
    output = capsys.readouterr()
    assert "(2 files)" in output.out and "Restored 2 file(s)" in output.out
    for content in values.values():
        assert content.decode() not in output.out + output.err


@pytest.mark.parametrize(
    "arguments",
    [
        ["compose-guard"],
        ["dot-env-check"],
        ["template-check"],
        ["runtime-env-check"],
        ["runtime-env-check", "--skip-dot-env"],
    ],
)
def test_read_only_commands_fail_closed_on_incomplete_installation(
    deployment, capsys, arguments
):
    """Inputs: incomplete installation contracts. Output: a nonzero result and no configuration changes."""
    root, values = deployment
    assert guard.main(["--repo-root", str(root), *arguments]) == 1
    output = capsys.readouterr()
    assert output.err
    for name, content in values.items():
        assert (root / name).read_bytes() == content
        assert content.decode() not in output.out + output.err
    assert not (root / guard.BACKUP_DIR_NAME).exists()


def test_empty_backup_directory_and_missing_named_backup_are_explicit(
    deployment, capsys
):
    """Inputs: empty or incomplete backup inventory. Output: clear failure without overwriting env files."""
    root, values = deployment
    assert guard.main(["--repo-root", str(root), "list"]) == 0
    backups = root / guard.BACKUP_DIR_NAME
    backups.mkdir()
    assert guard.main(["--repo-root", str(root), "list"]) == 0
    assert guard.main(["--repo-root", str(root), "restore"]) == 1
    (backups / "20260101T000000Z").mkdir()
    assert guard.main(["--repo-root", str(root), "restore"]) == 1
    assert (
        guard.main(["--repo-root", str(root), "restore", "--backup-name", "missing"])
        == 1
    )
    output = capsys.readouterr()
    assert "No backups directory found" in output.out
    assert "No backups found" in output.out
    assert "nothing restored" in output.err and "Backup not found" in output.err
    for name, content in values.items():
        assert (root / name).read_bytes() == content


def test_no_command_prints_help_and_missing_manifest_fails(tmp_path, capsys):
    """Inputs: no command or absent manifest. Output: help or an explicit manifest failure."""
    assert guard.main(["--repo-root", str(tmp_path)]) == 0
    assert "usage:" in capsys.readouterr().out
    with pytest.raises(SystemExit) as result:
        guard.main(["--repo-root", str(tmp_path), "check"])
    assert result.value.code == 2
    assert "Manifest file not found" in capsys.readouterr().err


def test_direct_entrypoint_checks_real_env_files(deployment, monkeypatch, capsys):
    """Inputs: the actual script CLI. Output: file validation without printed values."""
    root, values = deployment
    monkeypatch.setattr(
        sys, "argv", ["env_safety_guard", "--repo-root", str(root), "check"]
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(guard.__file__)), run_name="__main__")
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "All 2 manifest entries" in output
    for content in values.values():
        assert content.decode() not in output
