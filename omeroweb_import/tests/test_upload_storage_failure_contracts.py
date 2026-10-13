"""Real upload files with injected cleanup failures, not successful-path mocks."""

import errno
import os
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions as core


@pytest.mark.parametrize("mode", ["append", "replace-missing", "replace-denied"])
def test_oversize_failure_never_reports_success_or_leaks_descriptors(
    tmp_path, monkeypatch, mode
):
    """Inputs: oversized chunks and failed cleanup. Output: size error, closed FDs, no public exception leak."""
    target = tmp_path / "upload.bin"
    target.write_bytes(b"old")
    monkeypatch.setattr(core, "_get_upload_staged_file_max_bytes", lambda: 8)
    real_fdopen, real_unlink = os.fdopen, os.unlink
    opened = []

    class Writer:
        """Delegate real writes while reproducing a failed truncate operation."""

        def __init__(self, fd, mode):
            """Inputs: actual managed descriptor. Output: owned native file handle."""
            self.handle = real_fdopen(fd, mode)
            opened.append(fd)

        def __enter__(self):
            """Inputs: context entry. Output: the fault-injecting writer."""
            return self

        def write(self, value):
            """Inputs: upload bytes. Output: bytes written to the real staged file."""
            return self.handle.write(value)

        def truncate(self, _size):
            """Inputs: rollback size. Output: representative filesystem failure."""
            raise OSError(errno.EIO, "private filesystem diagnostic")

        def __exit__(self, *_error):
            """Inputs: context outcome. Output: native descriptor closed on failure too."""
            self.handle.close()

    def unlink(name, **kwargs):
        """Inputs: cleanup target. Output: disappearance race or permission failure."""
        if mode == "replace-missing":
            real_unlink(name, **kwargs)
            raise FileNotFoundError(errno.ENOENT, "already removed")
        raise PermissionError(errno.EACCES, "private filesystem diagnostic")

    monkeypatch.setattr(core.os, "fdopen", Writer)
    upload = SimpleNamespace(chunks=lambda: iter((b"12", b"0123456789")))
    if mode == "append":
        result = core._append_upload_chunks_to_staged_path(
            tmp_path, target.name, upload
        )
        assert result[:2] == (None, None)
        assert target.read_bytes() == b"old12"
    else:
        monkeypatch.setattr(core.os, "unlink", unlink)
        result = core._replace_staged_upload_file(tmp_path, target.name, upload)
        assert result[0] is None
        if mode == "replace-missing":
            assert not target.exists()
        else:
            assert target.read_bytes() == b"12"
    assert result[-1] == core.errors.upload_file_too_large(8)
    assert "private filesystem diagnostic" not in str(result)
    assert len(opened) == 1
    for fd in opened:
        with pytest.raises(OSError) as error:
            os.fstat(fd)
        assert error.value.errno == errno.EBADF
