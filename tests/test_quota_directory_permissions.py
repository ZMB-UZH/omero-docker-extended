"""Real-filesystem checks for installation-time quota directory permissions."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from tools import prepare_quota_directories as permissions


@pytest.fixture
def ownership(monkeypatch):
    """Exercise real modes without requiring a privileged local test runner.

    Inputs: pytest monkeypatch. Output: requested descriptor ownership changes.
    """
    changes = []
    original = os.fchown

    def assign(descriptor, uid, gid):
        """Record requested ownership. Inputs: descriptor and IDs. Output: None."""
        changes.append((os.fstat(descriptor).st_ino, uid, gid))
        original(descriptor, os.getuid(), os.getgid())

    monkeypatch.setattr(permissions.os, "fchown", assign)
    return changes


def test_fresh_and_existing_quota_directories(tmp_path, ownership):
    """Create and repair only metadata directories, preserving every payload.

    Inputs: disposable installation root. Output: exact modes and ownership plan.
    """
    for _ in range(2):
        permissions.prepare(tmp_path, 1234)
        admin = tmp_path / ".admin-tools"
        quota = admin / "quota"
        assert stat.S_IMODE(admin.stat().st_mode) == 0o1770
        assert stat.S_IMODE(quota.stat().st_mode) == 0o700
        assert ownership[-2:] == [
            (admin.stat().st_ino, 0, 1234),
            (quota.stat().st_ino, 0, 0),
        ]
        for directory in (admin, quota):
            payload = directory / "existing-state"
            if payload.exists():
                assert payload.read_bytes() == b"existing\x00state"
                assert stat.S_IMODE(payload.stat().st_mode) == 0o600
            payload.write_bytes(b"existing\x00state")
            payload.chmod(0o600)
            directory.chmod(0o777)


@pytest.mark.parametrize("leaf", [".admin-tools", ".admin-tools/quota"])
@pytest.mark.parametrize("kind", ["symlink", "file"])
def test_unsafe_metadata_paths_fail_without_touching_targets(
    tmp_path, ownership, leaf, kind
):
    """Reject links and non-directories before any ownership or mode changes.

    Inputs: malicious metadata path shapes. Output: unchanged unrelated content.
    """
    victim = tmp_path / "unrelated"
    victim.mkdir(mode=0o750)
    (victim / "retain").write_bytes(b"untouched")
    target = tmp_path / leaf
    target.parent.mkdir(exist_ok=True)
    if kind == "symlink":
        target.symlink_to(victim, target_is_directory=True)
    else:
        target.write_bytes(b"not a directory")
    with pytest.raises(OSError):
        permissions.prepare(tmp_path, 1234)
    assert ownership == []
    assert stat.S_IMODE(victim.stat().st_mode) == 0o750
    assert (victim / "retain").read_bytes() == b"untouched"


@pytest.mark.parametrize("gid", [-1, 2**32 - 1])
def test_invalid_group_is_rejected_before_creation(tmp_path, gid):
    """Do not interpret sentinel or overflowing IDs as ownership requests.

    Inputs: invalid group identifiers. Output: no directory creation.
    """
    with pytest.raises(ValueError):
        permissions.prepare(tmp_path, gid)
    assert list(tmp_path.iterdir()) == []


def test_operator_selected_root_alias_is_supported(tmp_path, ownership):
    """Trusted deployment roots may be aliases; metadata children may not.

    Inputs: operator-selected root symlink. Output: safely prepared real root.
    """
    data = tmp_path / "data"
    data.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(data, target_is_directory=True)
    permissions.prepare(alias, 1234)
    assert stat.S_IMODE((data / ".admin-tools").stat().st_mode) == 0o1770


def test_directory_replacement_does_not_redirect_permission_changes(
    tmp_path, ownership, monkeypatch
):
    """Keep mutations on opened directories when a pathname changes afterward.

    Inputs: a renamed metadata directory and replacement link. Output: the
    unrelated link target retains its original mode and contents.
    """
    admin = tmp_path / ".admin-tools"
    quota = admin / "quota"
    quota.mkdir(parents=True)
    victim = tmp_path / "unrelated"
    victim.mkdir(mode=0o750)
    (victim / "retain").write_bytes(b"untouched")
    original = os.open

    def open_and_replace(path, flags, *args, **kwargs):
        """Inject a pathname race. Inputs: open arguments. Output: original FD."""
        descriptor = original(path, flags, *args, **kwargs)
        if path == "quota":
            quota.rename(admin / "opened-quota")
            quota.symlink_to(victim, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(permissions.os, "open", open_and_replace)
    with pytest.raises(ValueError, match="changed during"):
        permissions.prepare(tmp_path, 1234)
    assert stat.S_IMODE((admin / "opened-quota").stat().st_mode) == 0o700
    assert stat.S_IMODE(victim.stat().st_mode) == 0o750
    assert (victim / "retain").read_bytes() == b"untouched"


def test_cli_reports_success_and_permission_failure(tmp_path, ownership, capsys):
    """Return a failing status instead of ignoring inaccessible state paths.

    Inputs: valid and missing data roots. Output: explicit success/failure.
    """
    assert permissions.main([str(tmp_path), "1234"]) == 0
    assert "verified" in capsys.readouterr().out
    assert permissions.main([str(tmp_path / "missing"), "1234"]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_installer_uses_descriptor_scoped_permission_helper():
    """Keep the full installation path aligned with the runtime quota policy.

    Inputs: tracked installer. Output: no legacy world-writable normalization.
    """
    source = (
        Path(__file__).resolve().parents[1] / "installation/installation_script.sh"
    ).read_text()
    section = source.split("# Ensure .admin-tools directory", 1)[1].split(
        "# Tmp artifact cleaner installation", 1
    )[0]
    assert "tools/prepare_quota_directories.py" in section
    assert '"${OMERO_USER_DATA_PATH}" "${OMERO_WEB_GID}"' in section
    assert "0777" not in section
