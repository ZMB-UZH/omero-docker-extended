from __future__ import annotations

import json
import os
import stat

import pytest

from omero_imaris_connector import session_handoff


def _handoff_file(tmp_path, ref="job-ref"):
    """Return the expected handoff file path for a test reference.

    Inputs: temporary root path and optional reference. Output: handoff file path.
    """
    return tmp_path / "omero-imaris-connector" / "session-handoff" / ref


def test_session_handoff_stores_pops_and_deletes_private_key(tmp_path, monkeypatch):
    """Verify session handoff files are private, one-time, and validated.

    Inputs: pytest fixtures. Output: asserts private one-time handoff behavior.
    """
    monkeypatch.setenv("OMERO_TMP_PATH", str(tmp_path))
    monkeypatch.setattr(session_handoff.time, "time", lambda: 100.0)

    assert (
        session_handoff.store_export_session_key(
            "job-ref", "session-key", ttl_seconds=0
        )
        == "job-ref"
    )

    path = _handoff_file(tmp_path)
    assert path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert session_handoff.pop_export_session_key("job-ref") == "session-key"
    assert not path.exists()
    assert session_handoff.pop_export_session_key("job-ref") is None

    session_handoff.delete_export_session_key(None)
    session_handoff.delete_export_session_key("missing-ref")


def test_session_handoff_covers_best_effort_permission_edges(tmp_path, monkeypatch):
    """Verify chmod failures and non-positive TTLs still keep safe handoff behavior.

    Inputs: pytest fixtures. Output: asserts chmod fallback and TTL handling.
    """
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir(mode=0o700)
    monkeypatch.setattr(
        session_handoff,
        "get_connector_tmp_dir",
        lambda *_args, **_kwargs: handoff_dir,
    )
    monkeypatch.setattr(
        session_handoff.os,
        "chmod",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("chmod failed")),
    )
    monkeypatch.setattr(session_handoff.time, "time", lambda: 100.0)

    assert session_handoff._handoff_dir() == handoff_dir
    assert (
        session_handoff.store_export_session_key(
            "job-ref", "session-key", ttl_seconds=-10
        )
        == "job-ref"
    )
    assert (handoff_dir / "job-ref").is_file()
    assert session_handoff.pop_export_session_key("job-ref") == "session-key"
    assert session_handoff.pop_export_session_key(None) is None


def test_session_handoff_rejects_invalid_refs_and_empty_keys(tmp_path, monkeypatch):
    """Verify unsafe handoff names and empty session keys fail closed.

    Inputs: pytest fixtures. Output: asserts invalid handoff inputs are rejected.
    """
    monkeypatch.setenv("OMERO_TMP_PATH", str(tmp_path))

    with pytest.raises(ValueError, match="session handoff reference"):
        session_handoff.store_export_session_key("../bad", "session-key")
    with pytest.raises(ValueError, match="session key"):
        session_handoff.store_export_session_key("job-ref", "")
    with pytest.raises(ValueError, match="session handoff reference"):
        session_handoff.pop_export_session_key("bad/path")


def test_session_handoff_ignores_expired_or_malformed_payloads(tmp_path, monkeypatch):
    """Verify malformed or expired handoff files do not yield a session key.

    Inputs: pytest fixtures. Output: asserts bad payloads return no session key.
    """
    monkeypatch.setenv("OMERO_TMP_PATH", str(tmp_path))
    monkeypatch.setattr(session_handoff.time, "time", lambda: 200.0)
    handoff_dir = _handoff_file(tmp_path).parent
    handoff_dir.mkdir(parents=True)

    for ref, payload in (
        ("expired", {"session_key": "old", "expires_at": 100.0}),
        ("not-dict", ["session-key"]),
        ("bad-expiry", {"session_key": "key", "expires_at": "never"}),
        ("missing-key", {"expires_at": 300.0}),
    ):
        (_handoff_file(tmp_path, ref)).write_text(json.dumps(payload), encoding="utf-8")
        assert session_handoff.pop_export_session_key(ref) is None


def test_session_handoff_rejects_unsafe_directory_state(tmp_path, monkeypatch):
    """Verify handoff directory symlink, file, and permissive states fail closed.

    Inputs: pytest fixtures. Output: asserts unsafe directories are rejected.
    """
    base = tmp_path / "handoff"
    monkeypatch.setattr(
        session_handoff, "get_connector_tmp_dir", lambda *_args, **_kwargs: base
    )

    base.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RuntimeError, match="handoff directory"):
        session_handoff._handoff_dir()
    base.unlink()

    target = tmp_path / "target"
    target.mkdir()
    base.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="handoff directory"):
        session_handoff._handoff_dir()
    base.unlink()

    base.mkdir(mode=0o777)
    monkeypatch.setattr(session_handoff.os, "chmod", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="too permissive"):
        session_handoff._handoff_dir()

    class BrokenStatPath:
        """Path-like object that raises only when mode is inspected."""

        @staticmethod
        def __fspath__():
            """Return the filesystem path for chmod compatibility.

            Inputs: none. Output: string path.
            """
            return str(base)

        @staticmethod
        def is_symlink():
            """Return whether this path is a symlink.

            Inputs: none. Output: False.
            """
            return False

        @staticmethod
        def is_dir():
            """Return whether this path is a directory.

            Inputs: none. Output: True.
            """
            return True

        @staticmethod
        def stat(*_args, **_kwargs):  # noqa: D401
            """Raise while inspecting the path.

            Inputs: ignored arguments. Output: raises OSError.
            """
            raise OSError("stat failed")

    broken = BrokenStatPath()
    monkeypatch.setattr(
        session_handoff, "get_connector_tmp_dir", lambda *_args, **_kwargs: broken
    )
    with pytest.raises(RuntimeError, match="Cannot inspect"):
        session_handoff._handoff_dir()


def test_session_handoff_removes_partial_file_when_write_fails(tmp_path, monkeypatch):
    """Verify partial handoff writes are deleted if serialization fails.

    Inputs: pytest fixtures. Output: asserts failed writes remove partial files.
    """
    monkeypatch.setenv("OMERO_TMP_PATH", str(tmp_path))

    def fail_dump(*_args, **_kwargs):
        """Raise during JSON serialization.

        Inputs: ignored arguments. Output: raises RuntimeError.
        """
        raise RuntimeError("serialize failed")

    monkeypatch.setattr(session_handoff.json, "dump", fail_dump)

    with pytest.raises(RuntimeError, match="serialize failed"):
        session_handoff.store_export_session_key("job-ref", "session-key")

    assert not _handoff_file(tmp_path).exists()
