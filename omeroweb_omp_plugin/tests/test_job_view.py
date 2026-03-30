from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from django.conf import settings
from django.test import RequestFactory

from omeroweb_omp_plugin.views import job_view

TEST_AUTH_INPUT = "fixture-auth-input"


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _User:
    def __init__(self, name="alice"):
        self._name = name

    def getName(self):
        return self._name


class _Image:
    def __init__(self, image_id, name):
        self.id = image_id
        self._name = name
        self._obj = object()

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return self._name


class _Conn:
    def __init__(self, username="alice", host="omeroserver", port=4064):
        self.host = host
        self.port = port
        self._user = _User(username)
        self._update = SimpleNamespace(
            saveAndReturnObject=lambda link: SimpleNamespace(id=1)
        )

    def getUser(self):
        return self._user

    def getUpdateService(self):
        return self._update

    def getObjects(self, object_type):
        assert object_type == "Image"
        return iter([])


class _FakeMapAnnotation:
    def setNs(self, value):
        self.ns = value

    def setMapValue(self, values):
        self.values = list(values)


class _FakeLink:
    def setParent(self, parent):
        self.parent = parent

    def setChild(self, child):
        self.child = child


def _json_request(payload):
    factory = RequestFactory()
    return factory.post("/", data=json.dumps(payload), content_type="application/json")


def _json_payload(response):
    return json.loads(response.content.decode("utf-8"))


def test_parse_image_ids_and_regex_safety_helpers():
    assert job_view.parse_image_ids("1, 2, nope, 3") == [1, 2, 3]
    assert sorted(job_view.parse_image_ids({4, "5", "bad"})) == [4, 5]
    assert job_view._is_safe_separator_regex(r"[_-]+") is True
    assert job_view._is_safe_separator_regex(r"(a++)") is False
    assert job_view._is_safe_separator_regex(r"(.)\1") is False


def test_validate_user_password_handles_missing_details_and_auth_failure(monkeypatch):
    conn = _Conn()
    missing_host_conn = _Conn(host=None, port=None)

    valid, error = job_view._validate_user_password(missing_host_conn, TEST_AUTH_INPUT)
    assert valid is False
    assert error is not None

    class FailingClient:
        def createSession(self, username, password):
            raise RuntimeError("bad password")

        def closeSession(self):
            return None

    monkeypatch.setattr(job_view.omero, "client", lambda host, port: FailingClient())
    monkeypatch.setattr(settings, "OMERO_HOST", "omeroserver", raising=False)
    monkeypatch.setattr(settings, "OMERO_PORT", 4064, raising=False)

    valid, error = job_view._validate_user_password(conn, "wrong")

    assert valid is False
    assert error is not None


def test_resolve_image_ids_prefers_selected_ids_and_deduplicates_project_images(
    monkeypatch,
):
    conn = _Conn()
    monkeypatch.setattr(
        job_view,
        "collect_images_in_project",
        lambda current_conn, project_id: [
            _Image(2, "b"),
            _Image(1, "a"),
            _Image(2, "b"),
        ],
    )

    assert job_view._resolve_image_ids(conn, 1, [8, 8, 7]) == [7, 8]
    assert job_view._resolve_image_ids(conn, 1, []) == [1, 2]


def test_start_job_rejects_invalid_regex_and_persists_expected_payload(monkeypatch):
    conn = _Conn()
    saved = {}
    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [11, 12])
    monkeypatch.setattr(
        job_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved.update(payload) or True
    )
    monkeypatch.setattr(job_view.uuid, "uuid4", lambda: SimpleNamespace(hex="job123"))
    monkeypatch.setattr(job_view.time, "time", lambda: 50.0)

    invalid = inspect.unwrap(job_view.start_job)(
        _json_request({"project_id": 5, "separator_mode": "regex", "separator": "("}),
        conn=conn,
    )
    response = inspect.unwrap(job_view.start_job)(
        _json_request(
            {
                "project_id": 5,
                "separator": "_-",
                "separator_mode": "chars",
                "var_names": ["Cell", "Channel"],
                "delete_mode": "plugin",
                "chunk_size": 500,
            }
        ),
        conn=conn,
    )

    assert invalid.status_code == 400
    assert _json_payload(response) == {"job_id": "job123", "total": 2}
    assert saved == {
        "job_id": "job123",
        "username": "alice",
        "project_id": 5,
        "separator": "_-",
        "var_names": ["Cell", "Channel"],
        "delete_mode": "plugin",
        "image_ids": [11, 12],
        "total": 2,
        "index": 0,
        "started": 50.0,
        "separator_mode": "chars",
        "chunk_size": job_view.CHUNK_SIZE,
    }


def test_start_acq_and_delete_jobs_apply_types_and_password_checks(monkeypatch):
    conn = _Conn()
    saved_jobs = []
    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [21, 22])
    monkeypatch.setattr(
        job_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved_jobs.append(dict(payload)) or True
    )
    monkeypatch.setattr(
        job_view.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=f"job{len(saved_jobs) + 1}"),
    )
    monkeypatch.setattr(job_view.time, "time", lambda: 75.0)
    monkeypatch.setattr(
        job_view, "_validate_user_password", lambda *_args: (True, None)
    )

    acq = inspect.unwrap(job_view.start_acq_job)(
        _json_request({"project_id": 5, "chunk_size": 3}),
        conn=conn,
    )
    delete_all = inspect.unwrap(job_view.start_delete_all_job)(
        _json_request({"project_id": 5, "password": TEST_AUTH_INPUT}),
        conn=conn,
    )
    delete_plugin = inspect.unwrap(job_view.start_delete_plugin_job)(
        _json_request({"project_id": 5, "password": TEST_AUTH_INPUT}),
        conn=conn,
    )

    assert _json_payload(acq)["job_id"] == "job1"
    assert _json_payload(delete_all)["job_id"] == "job2"
    assert _json_payload(delete_plugin)["job_id"] == "job3"
    assert [job["type"] for job in saved_jobs] == ["acq", "del_all", "del_plugin"]
    assert saved_jobs[0]["chunk_size"] == 3
    assert saved_jobs[1]["delete_mode"] == "all"
    assert saved_jobs[2]["delete_mode"] == "plugin"


def test_job_progress_rejects_other_users_and_reports_lock_contention(monkeypatch):
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    foreign_job = {"job_id": "a" * 32, "username": "bob", "index": 0, "total": 2}
    running_job = {
        "job_id": "a" * 32,
        "username": "alice",
        "index": 1,
        "total": 4,
        "var_names": [],
        "delete_mode": "keep",
        "separator": "_",
        "image_ids": [1, 2, 3, 4],
        "started": 1.0,
    }

    monkeypatch.setattr(job_view, "load_job", lambda job_id: foreign_job)
    forbidden = inspect.unwrap(job_view.job_progress)(request, "a" * 32, conn=conn)

    class BusyLock:
        def __init__(self, *_args, **_kwargs):
            return None

        def acquire(self):
            raise job_view.portalocker.exceptions.LockException("busy")

    monkeypatch.setattr(job_view, "load_job", lambda job_id: running_job)
    monkeypatch.setattr(job_view.portalocker, "Lock", BusyLock)
    busy = inspect.unwrap(job_view.job_progress)(request, "a" * 32, conn=conn)

    assert forbidden.status_code == 404
    assert _json_payload(forbidden)["finished"] is True
    assert _json_payload(busy) == {
        "done": 1,
        "total": 4,
        "percent": 25.0,
        "finished": False,
        "eta_seconds": None,
        "last_log": "",
    }


def test_job_progress_processes_acquisition_batches(monkeypatch):
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    saved_jobs = []
    job = {
        "job_id": "b" * 32,
        "username": "alice",
        "type": "acq",
        "index": 0,
        "total": 1,
        "var_names": [],
        "delete_mode": "keep",
        "separator": "_",
        "image_ids": [11],
        "started": 10.0,
        "chunk_size": 5,
    }

    class Lock:
        def __init__(self, *_args, **_kwargs):
            return None

        def acquire(self):
            return None

        def release(self):
            return None

    monkeypatch.setattr(job_view, "load_job", lambda *_args: job)
    monkeypatch.setattr(job_view.portalocker, "Lock", Lock)
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved_jobs.append(dict(payload)) or True
    )
    monkeypatch.setattr(
        job_view, "fetch_images_by_ids", lambda *_args: {11: _Image(11, "acq.ome.tif")}
    )
    monkeypatch.setattr(
        job_view, "extract_acquisition_metadata", lambda image: {"Laser": "405"}
    )
    monkeypatch.setattr(job_view, "_save_annotation_link", lambda update, link: True)
    monkeypatch.setattr(job_view, "MapAnnotationI", _FakeMapAnnotation)
    monkeypatch.setattr(job_view, "ImageAnnotationLinkI", _FakeLink)
    monkeypatch.setattr(job_view, "NamedValue", lambda key, value: (key, value))
    monkeypatch.setattr(job_view, "rstring", lambda value: value)
    monkeypatch.setattr(job_view, "compute_plugin_hash", lambda mapping: "hash")
    monkeypatch.setattr(job_view.time, "time", lambda: 12.0)

    response = inspect.unwrap(job_view.job_progress)(request, "b" * 32, conn=conn)

    assert _json_payload(response) == {
        "done": 1,
        "total": 1,
        "percent": 100.0,
        "eta_seconds": 0,
        "finished": True,
        "last_log": "Image 11 (acq.ome.tif): saved 2 acquisition entries.",
    }
    assert saved_jobs[-1]["index"] == 1


def test_job_progress_processes_filename_mapping_and_duplicate_variable_names(
    monkeypatch,
):
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    saved_jobs = []
    delete_calls = []
    saved_links = []
    job = {
        "job_id": "c" * 32,
        "username": "alice",
        "type": "parse",
        "index": 0,
        "total": 1,
        "var_names": ["Channel", "Channel"],
        "delete_mode": "plugin",
        "separator": "_",
        "image_ids": [22],
        "started": 20.0,
        "chunk_size": 5,
    }

    class Lock:
        def __init__(self, *_args, **_kwargs):
            return None

        def acquire(self):
            return None

        def release(self):
            return None

    monkeypatch.setattr(job_view, "load_job", lambda *_args: job)
    monkeypatch.setattr(job_view.portalocker, "Lock", Lock)
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved_jobs.append(dict(payload)) or True
    )
    monkeypatch.setattr(
        job_view,
        "fetch_images_by_ids",
        lambda *_args: {22: _Image(22, "parse_a_01.tif")},
    )
    monkeypatch.setattr(job_view, "parse_filename", lambda *_args: ["a", "01"])
    monkeypatch.setattr(
        job_view,
        "delete_existing_annotations",
        lambda *_args: delete_calls.append(_args[4]) or (1, 2, 1),
    )
    monkeypatch.setattr(
        job_view,
        "_save_annotation_link",
        lambda update, link: saved_links.append(link) or True,
    )
    monkeypatch.setattr(job_view, "MapAnnotationI", _FakeMapAnnotation)
    monkeypatch.setattr(job_view, "ImageAnnotationLinkI", _FakeLink)
    monkeypatch.setattr(job_view, "NamedValue", lambda key, value: (key, value))
    monkeypatch.setattr(job_view, "rstring", lambda value: value)
    monkeypatch.setattr(job_view, "compute_plugin_hash", lambda mapping: "hash")
    monkeypatch.setattr(job_view.time, "time", lambda: 22.0)

    response = inspect.unwrap(job_view.job_progress)(request, "c" * 32, conn=conn)

    assert (
        _json_payload(response)["last_log"]
        == "Image 22 (parse_a_01.tif): saved 2+1 variables."
    )
    assert delete_calls == ["plugin"]
    assert saved_jobs[-1]["index"] == 1
    assert saved_links[0].child.values == [
        ("Channel", "a"),
        ("Channel_2", "01"),
        (job_view.HASH_KEY, "hash"),
    ]
