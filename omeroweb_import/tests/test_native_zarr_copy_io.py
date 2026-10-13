"""Real descriptor I/O at native Zarr's private staging-copy boundary."""

import os
import errno

import pytest

from omeroweb_import.views import core_functions as core


@pytest.mark.parametrize("repetitions", [19, 8193])
def test_staging_copy_completes_partial_writes(tmp_path, monkeypatch, repetitions):
    """Inputs: real files and short-write injection. Output: exact-copy assertions."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    payload = bytes(range(256)) * repetitions
    source.write_bytes(payload)
    write = os.write
    calls = []

    def partial_write(fd, data):
        """Inputs: descriptor and bytes. Output: a real write of at most 37 bytes."""
        calls.append(len(data))
        return write(fd, data[:37])

    monkeypatch.setattr(core.os, "write", partial_write)
    with source.open("rb") as incoming:
        core._copy_file_descriptor(incoming.fileno(), target)
        assert not incoming.closed
    assert target.read_bytes() == payload
    assert len(calls) > 1


def test_staging_copy_reports_a_non_progressing_write_and_closes_destination(
    tmp_path, monkeypatch
):
    """Inputs: a zero-write fixture. Output: failure and descriptor-close checks."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"must not silently disappear")
    destination_fds = []

    def zero_write(fd, _data):
        """Inputs: an output descriptor and data. Output: zero, recording the fd."""
        destination_fds.append(fd)
        return 0

    monkeypatch.setattr(core.os, "write", zero_write)
    with source.open("rb") as incoming:
        with pytest.raises(OSError, match="write"):
            core._copy_file_descriptor(incoming.fileno(), target)
        assert os.fstat(incoming.fileno())
    assert destination_fds
    for fd in destination_fds:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_failed_transfer_copy_preserves_original_and_cleans_partial_output(
    tmp_path, monkeypatch
):
    """Inputs: storage exhaustion after progress. Output: source/cleanup checks."""
    source = tmp_path / "upload.zarr"
    source.mkdir()
    payload = b"original data survives a full filesystem" * 100
    (source / "chunk").write_bytes(payload)
    transfers = tmp_path / "transfers"
    transfers.mkdir()
    monkeypatch.setattr(core, "_shared_zarr_transfer_root", lambda: transfers)
    write = os.write
    calls = []

    def full_filesystem(fd, data):
        """Inputs: fd and bytes. Output: one short write, then an ENOSPC error."""
        calls.append(fd)
        if len(calls) == 1:
            return write(fd, data[:37])
        raise OSError(errno.ENOSPC, "Synthetic full filesystem")

    monkeypatch.setattr(core.os, "write", full_filesystem)
    shared, parent, error = core._prepare_server_readable_zarr_source(source)

    assert shared is None and parent is None
    assert "Synthetic full filesystem" in error
    assert (source / "chunk").read_bytes() == payload
    assert list(transfers.iterdir()) == []
