from __future__ import annotations

import logging
import time
from pathlib import Path
from types import SimpleNamespace

from django.test import RequestFactory

from omeroweb_omp_plugin.views import job_view, utils as view_utils, variable_set_view


class _LockStub:
    """Represent lock stub."""

    @staticmethod
    def acquire():
        """Acquire the lock.

        Inputs: none. Output: None.
        """
        return None

    @staticmethod
    def release():
        """Release the lock.

        Inputs: none. Output: None.
        """
        return None


class _ImageStub:
    """Represent image stub."""

    @staticmethod
    def getName():
        """Return the fake object name.

        Inputs: none. Output: 'image.ome.tif'.
        """
        return "image.ome.tif"


def test_job_progress_logs_escape_job_id_and_exception(
    monkeypatch, tmp_path: Path, caplog
):
    """Verify job progress logs escape job ID and exception.

    Inputs: `monkeypatch`, `tmp_path`, `caplog`. Output: None.
    """
    job = {
        "job_id": "bad\njob",
        "project_id": 1,
        "separator": "_",
        "var_names": [],
        "delete_mode": "keep",
        "image_ids": [7],
        "total": 1,
        "index": 0,
        "started": time.time(),
        "separator_mode": "chars",
        "chunk_size": 1,
        "username": "alice",
    }
    request = RequestFactory().get("/omp/job-progress/")

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(job_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(job_view, "load_job", lambda job_id: job)
    monkeypatch.setattr(job_view, "save_job", lambda job_dict: True)
    monkeypatch.setattr(
        job_view, "_job_lock_path", lambda job_id: tmp_path / "job.lock"
    )
    monkeypatch.setattr(
        job_view.portalocker, "Lock", lambda *args, **kwargs: _LockStub()
    )
    monkeypatch.setattr(
        job_view, "fetch_images_by_ids", lambda conn, batch_ids: {7: _ImageStub()}
    )
    monkeypatch.setattr(job_view, "get_text", lambda value: value)
    monkeypatch.setattr(
        job_view,
        "parse_filename",
        lambda filename, sep_pattern: (_ for _ in ()).throw(RuntimeError("bad\nparse")),
    )

    conn = SimpleNamespace(getUpdateService=object)
    with caplog.at_level(logging.ERROR, logger=job_view.logger.name):
        response = job_view.job_progress(request, job_id="bad\njob", conn=conn)

    assert response.status_code == 200
    assert "Error processing image 7 in job bad\\\\njob: bad\\\\nparse" in caplog.text
    assert "job bad\njob" not in caplog.text


def test_variable_set_view_logs_escape_exception_text(monkeypatch, caplog):
    """Verify variable set view logs escape exception text.

    Inputs: `monkeypatch`, `caplog`. Output: None.
    """
    request = RequestFactory().get("/omp/sets/")

    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(
        variable_set_view, "current_username", lambda request, conn: "alice"
    )
    monkeypatch.setattr(
        variable_set_view,
        "list_variable_sets",
        lambda username: (_ for _ in ()).throw(RuntimeError("boom\nforged")),
    )

    with caplog.at_level(logging.ERROR, logger=variable_set_view.logger.name):
        response = variable_set_view.list_sets(request, conn=None)

    assert response.status_code == 500
    assert "Unexpected error listing sets: boom\\\\nforged" in caplog.text
    assert "boom\nforged" not in caplog.text
