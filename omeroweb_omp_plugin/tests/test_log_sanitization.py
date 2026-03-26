from __future__ import annotations

import logging
import time
from pathlib import Path
from types import SimpleNamespace

from django.test import RequestFactory

from omeroweb_omp_plugin.views import job_view, variable_set_view


class _LockStub:
    def acquire(self):
        return None

    def release(self):
        return None


class _ImageStub:
    def getName(self):
        return "image.ome.tif"


def test_job_progress_logs_escape_job_id_and_exception(
    monkeypatch, tmp_path: Path, caplog
):
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
    }
    request = RequestFactory().get("/omp/job-progress/")

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
    request = RequestFactory().get("/omp/sets/")

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
