from __future__ import annotations

from iter_test_helpers import next_or_fail

import inspect
import json
from types import SimpleNamespace

from django.conf import settings
from django.test import RequestFactory

from omeroweb_omp_plugin.views import job_view

TEST_AUTH_INPUT = "fixture-auth-input"


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _User:
    """Test double for user behavior in this module."""

    def __init__(self, name="alice"):
        """Create `_User` with `name`.

        Inputs: `name`. Output: None.
        """
        self._name = name

    def getName(self):
        """Return `_User`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name


class _Image:
    """Test double for image behavior in this module."""

    def __init__(self, image_id, name):
        """Create `_Image` with `image_id` and `name`.

        Inputs: `image_id`, `name`. Output: None.
        """
        self.id = image_id
        self._name = name
        self._obj = object()

    def getId(self):
        """Return `_Image`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_Image`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name


class _Conn:
    """Test double for conn behavior in this module."""

    def __init__(self, username="alice", host="omeroserver", port=4064):
        """Create `_Conn` with `username`, `host`, and `port`.

        Inputs: `username`, `host`, `port`. Output: None.
        """
        self.host = host
        self.port = port
        self._user = _User(username)
        self._update = SimpleNamespace(
            saveAndReturnObject=lambda link: SimpleNamespace(id=1)
        )

    def getUser(self):
        """Return the fake user.

        Inputs: none. Output: `self._user`.
        """
        return self._user

    def getUpdateService(self):
        """Return `_Conn`'s fake update service.

        Inputs: none. Output: `self._update`.
        """
        return self._update

    @staticmethod
    def getObjects(object_type):
        """Return the objects for `_Conn`.

        Inputs: `object_type`. Output: `iter` result.
        """
        assert object_type == "Image"
        return iter([])


class _FakeMapAnnotation:
    """Test double for fake map annotation."""

    def setNs(self, value):
        """Set the ns for `_FakeMapAnnotation`.

        Inputs: `value` input value. Output: None.
        """
        self.ns = value

    def setMapValue(self, values):
        """Set the map Value for `_FakeMapAnnotation`.

        Inputs: `values`. Output: None.
        """
        self.values = list(values)


class _FakeLink:
    """Test double for fake link."""

    def setParent(self, parent):
        """Set the parent for `_FakeLink`.

        Inputs: `parent`. Output: None.
        """
        self.parent = parent

    def setChild(self, child):
        """Set the child for `_FakeLink`.

        Inputs: `child`. Output: None.
        """
        self.child = child


class _FakeImageRef:
    """Test double for fake image ref."""

    def __init__(self, image_id, loaded):
        """Create `_FakeImageRef` with `image_id` and `loaded`.

        Inputs: `image_id`, `loaded`. Output: None.
        """
        self.image_id = image_id
        self.loaded = loaded


def _json_request(payload):
    """Return the JSON request.

    Inputs: `payload` payload. Output: `post` result.
    """
    factory = RequestFactory()
    return factory.post("/", data=json.dumps(payload), content_type="application/json")


def _json_payload(response):
    """Return the JSON payload.

    Inputs: `response` response object. Output: `loads` result.
    """
    return json.loads(response.content.decode("utf-8"))


def test_parse_image_ids_and_regex_safety_helpers():
    """Verify parse image IDs and regex safety helpers.

    Inputs: OMP service fakes. Output: fails on regressions in parse image IDs and regex safety helpers.
    """
    assert job_view.parse_image_ids("1, 2, nope, 3") == [1, 2, 3]
    assert sorted(job_view.parse_image_ids({4, "5", "bad"})) == [4, 5]
    assert job_view.parse_image_ids(object()) == []


def test_image_ids_from_objects_skips_unusable_ids() -> None:
    """Verify image IDs from objects skips unusable IDs.

    Inputs: OMP service fakes. Output: fails on regressions in image IDs from objects skips unusable IDs.
    """
    broken = SimpleNamespace(getId=lambda: "not-an-int")
    missing = SimpleNamespace(getId=lambda: None)
    valid = SimpleNamespace(getId=lambda: _Value(9))

    assert job_view._image_ids_from_objects([missing, broken, valid, valid]) == [9]
    assert job_view._is_safe_separator_regex(r"[_-]+") is True
    assert job_view._is_safe_separator_regex(123) is False
    assert job_view._is_safe_separator_regex("") is False
    assert job_view._is_safe_separator_regex("x" * 129) is False
    assert job_view._is_safe_separator_regex(r"(a++)") is False
    assert job_view._is_safe_separator_regex(r"(.)\1") is False


def test_job_view_helper_guards_cover_ownership_host_resolution_and_link_save(
    monkeypatch,
):
    """Verify job view helper guards cover ownership host resolution and link save.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job view helper guards cover ownership host resolution and link save.
    """
    request = RequestFactory().get("/")
    conn = _Conn()

    monkeypatch.setattr(job_view, "current_username", lambda *_args: "alice")
    assert job_view._job_owned_by_request({}, request, conn) is False
    assert job_view._job_owned_by_request({"username": "alice"}, request, conn) is True
    assert job_view._job_owned_by_request({"username": "bob"}, request, conn) is False
    assert job_view._job_owned_by_request([], request, conn) is False

    conn.host = None
    conn.port = "bad"
    monkeypatch.setattr(settings, "OMERO_HOST", "omeroserver", raising=False)
    monkeypatch.setattr(settings, "OMERO_PORT", "not-a-port", raising=False)
    assert job_view._resolve_omero_host_port(conn) == ("omeroserver", None)

    monkeypatch.setattr(job_view, "collect_images_in_project", lambda *_args: [])
    monkeypatch.setattr(
        job_view,
        "get_id",
        lambda obj: getattr(obj, "bad_id", None),
    )
    fallback_conn = _Conn()
    fallback_conn.getObjects = lambda kind: iter(
        [
            SimpleNamespace(bad_id=None),
            SimpleNamespace(bad_id=7),
            SimpleNamespace(bad_id=7),
            SimpleNamespace(bad_id=3),
        ]
    )
    assert job_view._resolve_image_ids(fallback_conn, 5, []) == []

    assert (
        job_view._save_annotation_link(
            SimpleNamespace(saveAndReturnObject=lambda link: None),
            object(),
        )
        is False
    )
    monkeypatch.setattr(job_view, "get_id", lambda obj: None)
    assert (
        job_view._save_annotation_link(
            SimpleNamespace(saveAndReturnObject=lambda link: object()),
            object(),
        )
        is False
    )


def test_annotation_mapping_helpers_preserve_user_keys_and_hash_marker(monkeypatch):
    """Verify annotation mapping helpers preserve user keys and hash marker.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in annotation mapping helpers preserve user keys and hash marker.
    """
    monkeypatch.setattr(job_view, "compute_plugin_hash", lambda mapping: "hash")

    mapping = {}
    first = job_view._unique_annotation_key(mapping, "")
    mapping[first] = "alpha"
    second = job_view._unique_annotation_key(mapping, None)
    mapping[second] = "beta"
    reserved = job_view._unique_annotation_key(mapping, job_view.HASH_KEY)
    mapping[reserved] = "gamma"
    duplicate_reserved = job_view._unique_annotation_key(mapping, job_view.HASH_KEY)
    mapping[duplicate_reserved] = "delta"

    assert mapping == {
        "Var": "alpha",
        "Var_2": "beta",
        f"{job_view.HASH_KEY}_2": "gamma",
        f"{job_view.HASH_KEY}_3": "delta",
    }

    hashed = job_view._with_plugin_hash(mapping)

    assert mapping == {
        "Var": "alpha",
        "Var_2": "beta",
        f"{job_view.HASH_KEY}_2": "gamma",
        f"{job_view.HASH_KEY}_3": "delta",
    }
    assert hashed == {
        **mapping,
        job_view.HASH_KEY: "hash",
    }
    assert job_view._with_plugin_hash({}) == {}


def test_save_image_map_annotation_builds_expected_link(monkeypatch):
    """Verify save image map annotation builds expected link.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in save image map annotation builds expected link.
    """
    saved_links = []
    image = _Image(7, "sample.ome.tif")

    def save_link(link):
        """Save the link.

        Inputs: `link`. Output: `link`.
        """
        saved_links.append(link)
        return link

    update = SimpleNamespace(saveAndReturnObject=save_link)

    monkeypatch.setattr(job_view, "MapAnnotationI", _FakeMapAnnotation)
    monkeypatch.setattr(job_view, "ImageAnnotationLinkI", _FakeLink)
    monkeypatch.setattr(job_view, "ImageI", _FakeImageRef)
    monkeypatch.setattr(job_view, "NamedValue", lambda key, value: (key, value))
    monkeypatch.setattr(job_view, "rstring", lambda value: value)
    monkeypatch.setattr(job_view, "get_id", lambda obj: getattr(obj, "id", 123))

    assert job_view._save_image_map_annotation(update, image, {"Plate": "P1"}) is True

    assert saved_links[0].parent.image_id == 7
    assert saved_links[0].parent.loaded is False
    assert saved_links[0].parent is not image._obj
    assert saved_links[0].child.ns == job_view.MAP_NS
    assert saved_links[0].child.values == [("Plate", "P1")]


def test_save_image_map_annotation_rejects_missing_or_invalid_image_id(monkeypatch):
    """Confirm save image map annotation rejects missing or invalid image ID is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in save image map annotation rejects missing or invalid image ID.
    """
    update = SimpleNamespace(saveAndReturnObject=lambda link: link)

    monkeypatch.setattr(job_view, "get_id", lambda obj: None)
    assert (
        job_view._save_image_map_annotation(update, object(), {"Plate": "P1"}) is False
    )

    monkeypatch.setattr(job_view, "get_id", lambda obj: "not-an-id")
    assert (
        job_view._save_image_map_annotation(update, object(), {"Plate": "P1"}) is False
    )


def test_validate_user_password_handles_missing_details_and_auth_failure(monkeypatch):
    """Check that validate user password handles missing details and auth failure keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when validate user password handles missing details and auth failure accepts unsafe input.
    when validation or the called operation fails.
    """
    conn = _Conn()
    missing_host_conn = _Conn(host=None, port=None)

    valid, error = job_view._validate_user_password(missing_host_conn, TEST_AUTH_INPUT)
    assert valid is False
    assert error is not None

    class FailingClient:
        """Test double for failing client behavior in this module."""

        @staticmethod
        def createSession(username, password):
            """Create the session for `FailingClient`.

            Inputs: `username` username, `password` password. Output: None. Raises:
            RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("bad password")

        @staticmethod
        def closeSession():
            """Close the session for `FailingClient`.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    monkeypatch.setattr(
        job_view.omero,
        "client",
        lambda host, port: FailingClient(),
        raising=False,
    )
    monkeypatch.setattr(settings, "OMERO_HOST", "omeroserver", raising=False)
    monkeypatch.setattr(settings, "OMERO_PORT", 4064, raising=False)

    valid, error = job_view._validate_user_password(conn, "wrong")

    assert valid is False
    assert error is not None


def test_resolve_image_ids_prefers_selected_ids_and_deduplicates_project_images(
    monkeypatch,
):
    """Verify resolve image IDs prefers selected IDs and deduplicates project images.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve image IDs prefers selected IDs and deduplicates project images.
    """
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

    assert job_view._resolve_image_ids(conn, 1, [8, 8, 7, "2", "bad"]) == [2]
    assert job_view._resolve_image_ids(conn, 1, []) == [1, 2]


def test_start_job_rejects_invalid_regex_and_persists_expected_payload(monkeypatch):
    """Confirm start job rejects invalid regex and persists expected payload is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in start job rejects invalid regex and persists expected payload.
    """
    conn = _Conn()
    saved = {}
    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [11, 12])
    monkeypatch.setattr(
        job_view, "check_major_action_rate_limit", lambda *_args: (True, 0)
    )
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved.update(payload) or True
    )
    monkeypatch.setattr(
        job_view, "_validate_user_password", lambda *_args: (True, None)
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
                "password": TEST_AUTH_INPUT,
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
    """Check that start acq and delete jobs apply types and password checks keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in start acq and delete jobs apply types and password checks.
    """
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


def test_start_job_variants_cover_methods_rate_limits_and_validation_errors(
    monkeypatch,
):
    """Verify start job variants cover methods rate limits and validation errors.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in start job variants cover methods rate limits and validation errors.
    """
    conn = _Conn()
    factory = RequestFactory()

    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [31])
    monkeypatch.setattr(
        job_view, "check_major_action_rate_limit", lambda *_args: (False, 12)
    )
    monkeypatch.setattr(
        job_view, "_validate_user_password", lambda *_args: (False, "bad password")
    )

    get_response = inspect.unwrap(job_view.start_job)(factory.get("/"), conn=conn)
    missing_project = inspect.unwrap(job_view.start_job)(
        _json_request({"separator": "_"}),
        conn=conn,
    )
    rate_limited = inspect.unwrap(job_view.start_job)(
        _json_request({"project_id": 5, "separator_mode": "wat", "chunk_size": "bad"}),
        conn=conn,
    )
    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [])
    no_images = inspect.unwrap(job_view.start_job)(
        _json_request({"project_id": 5}),
        conn=conn,
    )
    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [31])
    rejected_auth_input = TEST_AUTH_INPUT
    delete_forbidden = inspect.unwrap(job_view.start_job)(
        _json_request(
            {
                "project_id": 5,
                "delete_mode": "all",
                "password": rejected_auth_input,
            }
        ),
        conn=conn,
    )
    acq_get = inspect.unwrap(job_view.start_acq_job)(factory.get("/"), conn=conn)
    acq_missing = inspect.unwrap(job_view.start_acq_job)(
        _json_request({"chunk_size": "bad"}),
        conn=conn,
    )
    acq_rate_limited = inspect.unwrap(job_view.start_acq_job)(
        _json_request({"project_id": 5, "chunk_size": "bad"}),
        conn=conn,
    )
    delete_all_forbidden = inspect.unwrap(job_view.start_delete_all_job)(
        _json_request({"project_id": 5, "password": TEST_AUTH_INPUT}),
        conn=conn,
    )
    delete_plugin_forbidden = inspect.unwrap(job_view.start_delete_plugin_job)(
        _json_request({"project_id": 5, "password": TEST_AUTH_INPUT}),
        conn=conn,
    )

    assert get_response.status_code == 400
    assert missing_project.status_code == 400
    assert rate_limited.status_code == 429
    assert no_images.status_code == 400
    assert delete_forbidden.status_code == 403
    assert acq_get.status_code == 400
    assert acq_missing.status_code == 400
    assert acq_rate_limited.status_code == 429
    assert delete_all_forbidden.status_code == 403
    assert delete_plugin_forbidden.status_code == 403


def test_start_job_variants_cover_exception_paths(monkeypatch):
    """Confirm start job variants cover exception paths exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when start job variants cover exception paths stops reporting the expected error.
    """
    conn = _Conn()
    failing_request = _json_request({"project_id": 5})

    monkeypatch.setattr(
        job_view,
        "load_request_data",
        lambda request: (_ for _ in ()).throw(RuntimeError("bad request")),
    )
    start_error = inspect.unwrap(job_view.start_job)(failing_request, conn=conn)
    acq_error = inspect.unwrap(job_view.start_acq_job)(failing_request, conn=conn)
    delete_all_error = inspect.unwrap(job_view.start_delete_all_job)(
        failing_request,
        conn=conn,
    )
    delete_plugin_error = inspect.unwrap(job_view.start_delete_plugin_job)(
        failing_request,
        conn=conn,
    )

    assert start_error.status_code == 500
    assert acq_error.status_code == 500
    assert delete_all_error.status_code == 500
    assert delete_plugin_error.status_code == 500


def test_job_progress_rejects_other_users_and_reports_lock_contention(monkeypatch):
    """Confirm job progress rejects other users and reports lock contention is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job progress rejects other users and reports lock contention.
    LockException when validation or the called operation fails.
    """
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
        """Test double for busy lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `BusyLock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `BusyLock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            external operations fail.
            """
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
    """Verify job progress processes acquisition batches.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job progress processes acquisition batches.
    """
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    saved_jobs = []
    saved_links = []
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
        """Test double for lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `Lock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def release():
            """Release `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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
    monkeypatch.setattr(job_view.time, "time", lambda: 12.0)

    response = inspect.unwrap(job_view.job_progress)(request, "b" * 32, conn=conn)

    assert _json_payload(response) == {
        "done": 1,
        "total": 1,
        "percent": 100.0,
        "eta_seconds": 0,
        "finished": True,
        "last_log": "Image 11 (acq.ome.tif): saved 1+1 acquisition entries.",
    }
    assert saved_jobs[-1]["index"] == 1
    assert saved_links[0].child.values == [
        ("Laser", "405"),
        (job_view.HASH_KEY, "hash"),
    ]


def test_job_progress_processes_filename_mapping_and_duplicate_variable_names(
    monkeypatch,
):
    """Verify job progress processes filename mapping and duplicate variable names.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job progress processes filename mapping and duplicate variable names.
    """
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
        """Test double for lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `Lock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def release():
            """Release `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
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


def test_job_progress_preserves_reserved_hash_variable_name(monkeypatch):
    """Check that job progress preserves reserved hash variable name remains stable.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job progress preserves reserved hash variable name.
    """
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    saved_links = []
    job = {
        "job_id": "d" * 32,
        "username": "alice",
        "type": "parse",
        "index": 0,
        "total": 1,
        "var_names": [job_view.HASH_KEY, job_view.HASH_KEY],
        "delete_mode": "keep",
        "separator": "_",
        "image_ids": [33],
        "started": 30.0,
        "chunk_size": 5,
    }

    class Lock:
        """Test double for lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `Lock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def release():
            """Release `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    monkeypatch.setattr(job_view, "load_job", lambda *_args: job)
    monkeypatch.setattr(job_view.portalocker, "Lock", Lock)
    monkeypatch.setattr(job_view, "save_job", lambda payload: True)
    monkeypatch.setattr(
        job_view,
        "fetch_images_by_ids",
        lambda *_args: {33: _Image(33, "reserved_a_01.tif")},
    )
    monkeypatch.setattr(job_view, "parse_filename", lambda *_args: ["a", "01"])
    monkeypatch.setattr(job_view, "delete_existing_annotations", lambda *_args: None)
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
    monkeypatch.setattr(job_view.time, "time", lambda: 32.0)

    response = inspect.unwrap(job_view.job_progress)(request, "d" * 32, conn=conn)

    assert "saved 2+1 variables" in _json_payload(response)["last_log"]
    assert saved_links[0].child.values == [
        (f"{job_view.HASH_KEY}_2", "a"),
        (f"{job_view.HASH_KEY}_3", "01"),
        (job_view.HASH_KEY, "hash"),
    ]


def test_job_progress_covers_unknown_finished_delete_paths_and_save_failures(
    monkeypatch,
):
    """Check job progress covers unknown finished delete paths and save failures cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job progress covers unknown finished delete paths and save failures.
    """
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")

    class Lock:
        """Test double for lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `Lock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def release():
            """Release `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    monkeypatch.setattr(job_view.portalocker, "Lock", Lock)

    monkeypatch.setattr(job_view, "load_job", lambda *_args: None)
    unknown = inspect.unwrap(job_view.job_progress)(request, "d" * 32, conn=conn)
    assert unknown.status_code == 404
    assert _json_payload(unknown) == {
        "error": job_view.error_messages.unknown_job(),
        "finished": True,
    }

    finished_job = {
        "job_id": "e" * 32,
        "username": "alice",
        "index": 2,
        "total": 2,
        "var_names": [],
        "delete_mode": "keep",
        "separator": "_",
        "image_ids": [1, 2],
        "started": 10.0,
    }
    monkeypatch.setattr(job_view, "load_job", lambda *_args: finished_job)
    finished = inspect.unwrap(job_view.job_progress)(request, "e" * 32, conn=conn)
    assert _json_payload(finished)["finished"] is True

    unsafe_regex_job = {
        "job_id": "f" * 32,
        "username": "alice",
        "index": 0,
        "total": 1,
        "var_names": [],
        "delete_mode": "keep",
        "separator": "(a++)",
        "separator_mode": "regex",
        "image_ids": [1],
        "started": 10.0,
    }
    monkeypatch.setattr(job_view, "load_job", lambda *_args: unsafe_regex_job)
    unsafe = inspect.unwrap(job_view.job_progress)(request, "f" * 32, conn=conn)
    assert unsafe.status_code == 400

    delete_all_job = {
        "job_id": "a" * 32,
        "username": "alice",
        "type": "del_all",
        "index": 0,
        "total": 1,
        "var_names": [],
        "delete_mode": "all",
        "separator": "_",
        "image_ids": [41],
        "started": 10.0,
        "chunk_size": 5,
    }
    delete_plugin_job = {
        "job_id": "b" * 32,
        "username": "alice",
        "type": "del_plugin",
        "index": 0,
        "total": 1,
        "var_names": [],
        "delete_mode": "plugin",
        "separator": "_",
        "image_ids": [42],
        "started": 10.0,
        "chunk_size": 5,
    }
    parse_missing_job = {
        "job_id": "c" * 32,
        "username": "alice",
        "type": "parse",
        "index": 0,
        "total": 2,
        "var_names": ["Channel"],
        "delete_mode": "plugin",
        "separator": "_",
        "image_ids": [43, 44],
        "started": 10.0,
        "chunk_size": 5,
    }
    parse_no_values_job = {
        "job_id": "d" * 32,
        "username": "alice",
        "type": "parse",
        "index": 0,
        "total": 1,
        "var_names": [],
        "delete_mode": "keep",
        "separator": "_",
        "image_ids": [45],
        "started": 10.0,
        "chunk_size": 5,
    }
    acq_empty_job = {
        "job_id": "e" * 32,
        "username": "alice",
        "type": "acq",
        "index": 0,
        "total": 1,
        "var_names": [],
        "delete_mode": "keep",
        "separator": "_",
        "image_ids": [46],
        "started": 10.0,
        "chunk_size": 5,
    }

    current_job = {"value": delete_all_job}
    monkeypatch.setattr(job_view, "load_job", lambda *_args: current_job["value"])
    monkeypatch.setattr(job_view, "save_job", lambda payload: True)
    monkeypatch.setattr(
        job_view,
        "fetch_images_by_ids",
        lambda *_args: {
            41: _Image(41, "delete-all.ome.tif"),
            42: _Image(42, "delete-plugin.ome.tif"),
            45: _Image(45, "empty.ome.tif"),
            46: _Image(46, "acq-empty.ome.tif"),
        },
    )
    monkeypatch.setattr(
        job_view,
        "delete_existing_annotations",
        lambda *_args: (0, 0, 0) if _args[2].id == 41 else (1, 3, 2),
    )
    monkeypatch.setattr(job_view.time, "time", lambda: 12.0)
    monkeypatch.setattr(job_view, "MapAnnotationI", _FakeMapAnnotation)
    monkeypatch.setattr(job_view, "ImageAnnotationLinkI", _FakeLink)
    monkeypatch.setattr(job_view, "NamedValue", lambda key, value: (key, value))
    monkeypatch.setattr(job_view, "rstring", lambda value: value)
    monkeypatch.setattr(job_view, "compute_plugin_hash", lambda mapping: "hash")
    monkeypatch.setattr(job_view, "_save_annotation_link", lambda update, link: False)
    monkeypatch.setattr(job_view, "parse_filename", lambda *_args: [])
    monkeypatch.setattr(job_view, "extract_acquisition_metadata", lambda image: {})

    delete_all = inspect.unwrap(job_view.job_progress)(request, "a" * 32, conn=conn)
    assert "no key-value pairs to delete found" in _json_payload(delete_all)["last_log"]

    current_job["value"] = delete_plugin_job
    delete_plugin = inspect.unwrap(job_view.job_progress)(request, "b" * 32, conn=conn)
    plugin_log = _json_payload(delete_plugin)["last_log"]
    assert "deleted ONLY plugin key-value pairs" in plugin_log
    assert "warning - only confirmed 1 of 2 deletions" in plugin_log

    current_job["value"] = parse_missing_job
    missing_image = inspect.unwrap(job_view.job_progress)(request, "c" * 32, conn=conn)
    assert "Image 43: not found." in _json_payload(missing_image)["last_log"]

    current_job["value"] = parse_no_values_job
    no_values = inspect.unwrap(job_view.job_progress)(request, "d" * 32, conn=conn)
    assert (
        "Image 45 (empty.ome.tif): no variables."
        in _json_payload(no_values)["last_log"]
    )

    current_job["value"] = acq_empty_job
    no_acq = inspect.unwrap(job_view.job_progress)(request, "e" * 32, conn=conn)
    assert "Image 46: no acquisition metadata." in _json_payload(no_acq)["last_log"]


def test_job_progress_covers_error_logs_and_save_failures(monkeypatch):
    """Confirm job progress covers error logs and save failures exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when job progress covers error logs and save failures stops reporting the expected error.
    Raises: RuntimeError when validation or the called operation fails.
    """
    conn = _Conn()
    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")

    class Lock:
        """Test double for lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `Lock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def release():
            """Release `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    monkeypatch.setattr(job_view.portalocker, "Lock", Lock)
    monkeypatch.setattr(job_view.time, "time", lambda: 15.0)
    monkeypatch.setattr(job_view, "save_job", lambda payload: True)
    monkeypatch.setattr(job_view, "MapAnnotationI", _FakeMapAnnotation)
    monkeypatch.setattr(job_view, "ImageAnnotationLinkI", _FakeLink)
    monkeypatch.setattr(job_view, "NamedValue", lambda key, value: (key, value))
    monkeypatch.setattr(job_view, "rstring", lambda value: value)
    monkeypatch.setattr(job_view, "compute_plugin_hash", lambda mapping: "hash")

    jobs = {
        "del_all": {
            "job_id": "1" * 32,
            "username": "alice",
            "type": "del_all",
            "index": 0,
            "total": 1,
            "var_names": [],
            "delete_mode": "all",
            "separator": "_",
            "image_ids": [51],
            "started": 10.0,
            "chunk_size": 5,
        },
        "del_plugin": {
            "job_id": "2" * 32,
            "username": "alice",
            "type": "del_plugin",
            "index": 0,
            "total": 1,
            "var_names": [],
            "delete_mode": "plugin",
            "separator": "_",
            "image_ids": [52],
            "started": 10.0,
            "chunk_size": 5,
        },
        "acq": {
            "job_id": "3" * 32,
            "username": "alice",
            "type": "acq",
            "index": 0,
            "total": 1,
            "var_names": [],
            "delete_mode": "keep",
            "separator": "_",
            "image_ids": [53],
            "started": 10.0,
            "chunk_size": 5,
        },
        "parse": {
            "job_id": "4" * 32,
            "username": "alice",
            "type": "parse",
            "index": 0,
            "total": 1,
            "var_names": ["Channel", "Channel"],
            "delete_mode": "plugin",
            "separator": "_",
            "image_ids": [54],
            "started": 10.0,
            "chunk_size": 5,
        },
        "parse_error": {
            "job_id": "5" * 32,
            "username": "alice",
            "type": "parse",
            "index": 0,
            "total": 1,
            "var_names": ["Channel"],
            "delete_mode": "keep",
            "separator": "_",
            "image_ids": [55],
            "started": 10.0,
            "chunk_size": 5,
        },
    }
    current_job = {"value": jobs["del_all"]}

    monkeypatch.setattr(job_view, "load_job", lambda *_args: current_job["value"])
    monkeypatch.setattr(
        job_view,
        "fetch_images_by_ids",
        lambda *_args: {
            51: _Image(51, "delete-all.ome.tif"),
            52: _Image(52, "delete-plugin.ome.tif"),
            53: _Image(53, "acq.ome.tif"),
            54: _Image(54, "parse.ome.tif"),
            55: _Image(55, "broken.ome.tif"),
        },
    )

    def _delete_existing_annotations(*args):
        """Delete the existing annotations.

        Inputs: `*args` positional arguments. Output: `tuple`. Raises: RuntimeError when validation or the called operation fails.
        """
        image_id = args[2].id
        if image_id == 51:
            raise RuntimeError("delete all failed")
        if image_id == 52:
            return (0, 0, 2)
        return (0, 0, 0)

    monkeypatch.setattr(
        job_view,
        "delete_existing_annotations",
        _delete_existing_annotations,
    )
    monkeypatch.setattr(
        job_view,
        "extract_acquisition_metadata",
        lambda image: {"Laser": "405"} if image.id == 53 else {},
    )
    save_results = iter([False, False])
    monkeypatch.setattr(
        job_view,
        "_save_annotation_link",
        lambda update, link: next_or_fail(save_results),
    )
    monkeypatch.setattr(
        job_view,
        "parse_filename",
        lambda filename, pattern: (
            (_ for _ in ()).throw(RuntimeError("parse failed"))
            if "broken" in filename
            else ["a", "01"]
        ),
    )

    current_job["value"] = jobs["del_all"]
    delete_all = inspect.unwrap(job_view.job_progress)(request, "1" * 32, conn=conn)
    assert "ERROR deleting ALL key-value pairs" in _json_payload(delete_all)["last_log"]

    current_job["value"] = jobs["del_plugin"]
    delete_plugin = inspect.unwrap(job_view.job_progress)(request, "2" * 32, conn=conn)
    assert (
        "no key-value pairs deleted because deletions could not be confirmed"
        in _json_payload(delete_plugin)["last_log"]
    )

    current_job["value"] = jobs["acq"]
    acq = inspect.unwrap(job_view.job_progress)(request, "3" * 32, conn=conn)
    assert "ERROR confirming acquisition save" in _json_payload(acq)["last_log"]

    current_job["value"] = jobs["parse"]
    parse = inspect.unwrap(job_view.job_progress)(request, "4" * 32, conn=conn)
    assert "ERROR confirming variable save" in _json_payload(parse)["last_log"]

    current_job["value"] = jobs["parse_error"]
    parse_error = inspect.unwrap(job_view.job_progress)(request, "5" * 32, conn=conn)
    assert "Image 55: ERROR processing image." in _json_payload(parse_error)["last_log"]


def test_job_view_start_helpers_cover_method_chunk_size_and_rate_limit_edges(
    monkeypatch,
):
    """Verify job view start helpers cover method chunk size and rate limit edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in job view start helpers cover method chunk size and rate limit edges.
    """
    conn = _Conn()
    factory = RequestFactory()
    saved_jobs = []
    monkeypatch.setattr(job_view, "_resolve_image_ids", lambda *_args: [7, 8])
    monkeypatch.setattr(
        job_view, "_validate_user_password", lambda *_args: (True, None)
    )
    monkeypatch.setattr(
        job_view, "check_major_action_rate_limit", lambda *_args: (False, 12)
    )
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved_jobs.append(dict(payload)) or True
    )

    get_delete_all = inspect.unwrap(job_view.start_delete_all_job)(
        factory.get("/"),
        conn=conn,
    )
    get_delete_plugin = inspect.unwrap(job_view.start_delete_plugin_job)(
        factory.get("/"),
        conn=conn,
    )
    assert get_delete_all.status_code == 400
    assert get_delete_plugin.status_code == 400

    missing_project_delete_all = inspect.unwrap(job_view.start_delete_all_job)(
        _json_request({"chunk_size": "bad", "password": TEST_AUTH_INPUT}),
        conn=conn,
    )
    missing_project_delete_plugin = inspect.unwrap(job_view.start_delete_plugin_job)(
        _json_request({"chunk_size": "bad", "password": TEST_AUTH_INPUT}),
        conn=conn,
    )
    assert missing_project_delete_all.status_code == 400
    assert missing_project_delete_plugin.status_code == 400

    rate_limited_acq = inspect.unwrap(job_view.start_acq_job)(
        _json_request({"project_id": 5, "chunk_size": 999}),
        conn=conn,
    )
    rate_limited_delete_all = inspect.unwrap(job_view.start_delete_all_job)(
        _json_request(
            {"project_id": 5, "password": TEST_AUTH_INPUT, "chunk_size": 999}
        ),
        conn=conn,
    )
    rate_limited_delete_plugin = inspect.unwrap(job_view.start_delete_plugin_job)(
        _json_request(
            {"project_id": 5, "password": TEST_AUTH_INPUT, "chunk_size": "bad"}
        ),
        conn=conn,
    )
    assert rate_limited_acq.status_code == 429
    assert rate_limited_delete_all.status_code == 429
    assert rate_limited_delete_plugin.status_code == 429

    monkeypatch.setattr(
        job_view, "check_major_action_rate_limit", lambda *_args: (True, None)
    )
    chunk_capped = inspect.unwrap(job_view.start_delete_plugin_job)(
        _json_request(
            {"project_id": 5, "password": TEST_AUTH_INPUT, "chunk_size": 999}
        ),
        conn=conn,
    )
    assert chunk_capped.status_code == 200
    assert saved_jobs[-1]["chunk_size"] == job_view.CHUNK_SIZE


def test_validate_user_password_and_job_progress_cover_remaining_logging_and_regex_edges(
    monkeypatch,
):
    """Check that validate user password and job progress cover remaining logging and regex edges keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in validate user password and job progress cover remaining logging and regex edges.
    Raises: RuntimeError when validation or the called operation fails.
    """
    conn = _Conn()

    class _Client:
        """Test double for client behavior in this module."""

        @staticmethod
        def createSession(username, password):
            """Create the session for `_Client`.

            Inputs: `username` username, `password` password. Output: None.
            """
            return None

        @staticmethod
        def closeSession():
            """Close the session for `_Client`.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close exploded")

    monkeypatch.setattr(
        job_view.omero,
        "client",
        lambda host, port: _Client(),
        raising=False,
    )
    monkeypatch.setattr(settings, "OMERO_HOST", "omeroserver", raising=False)
    monkeypatch.setattr(settings, "OMERO_PORT", 4064, raising=False)
    assert job_view._validate_user_password(conn, TEST_AUTH_INPUT) == (True, None)

    request = RequestFactory().get("/")
    request.user = SimpleNamespace(username="alice")
    saved_jobs = []

    class Lock:
        """Test double for lock behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `Lock` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        @staticmethod
        def acquire():
            """Acquire `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def release():
            """Release `Lock`'s fake lock.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    jobs = {
        "regex_parse": {
            "job_id": "6" * 32,
            "username": "alice",
            "type": "parse",
            "index": 0,
            "total": 1,
            "var_names": ["", "Var1", "Var1"],
            "delete_mode": "keep",
            "separator": r"[_-]+",
            "separator_mode": "regex",
            "image_ids": [61],
            "started": 10.0,
            "chunk_size": 5,
        },
        "delete_all_warn": {
            "job_id": "7" * 32,
            "username": "alice",
            "type": "del_all",
            "index": 0,
            "total": 1,
            "var_names": [],
            "delete_mode": "all",
            "separator": "_",
            "image_ids": [62],
            "started": 10.0,
            "chunk_size": 5,
        },
        "delete_plugin_empty": {
            "job_id": "8" * 32,
            "username": "alice",
            "type": "del_plugin",
            "index": 0,
            "total": 1,
            "var_names": [],
            "delete_mode": "plugin",
            "separator": "_",
            "image_ids": [63],
            "started": 10.0,
            "chunk_size": 5,
        },
        "delete_plugin_error": {
            "job_id": "9" * 32,
            "username": "alice",
            "type": "del_plugin",
            "index": 0,
            "total": 1,
            "var_names": [],
            "delete_mode": "plugin",
            "separator": "_",
            "image_ids": [64],
            "started": 10.0,
            "chunk_size": 5,
        },
    }
    current_job = {"value": jobs["regex_parse"]}

    monkeypatch.setattr(job_view.portalocker, "Lock", Lock)
    monkeypatch.setattr(job_view, "load_job", lambda *_args: current_job["value"])
    monkeypatch.setattr(
        job_view, "save_job", lambda payload: saved_jobs.append(dict(payload)) or True
    )
    monkeypatch.setattr(
        job_view,
        "fetch_images_by_ids",
        lambda *_args: {
            61: _Image(61, "regex-A_01_02.tif"),
            62: _Image(62, "delete-all.ome.tif"),
            63: _Image(63, "delete-plugin-empty.ome.tif"),
            64: _Image(64, "delete-plugin-error.ome.tif"),
        },
    )
    monkeypatch.setattr(job_view, "parse_filename", lambda *_args: ["a", "01", "02"])
    monkeypatch.setattr(job_view, "MapAnnotationI", _FakeMapAnnotation)
    monkeypatch.setattr(job_view, "ImageAnnotationLinkI", _FakeLink)
    monkeypatch.setattr(job_view, "NamedValue", lambda key, value: (key, value))
    monkeypatch.setattr(job_view, "rstring", lambda value: value)
    monkeypatch.setattr(job_view, "compute_plugin_hash", lambda mapping: "hash")
    monkeypatch.setattr(job_view, "_save_annotation_link", lambda update, link: True)
    monkeypatch.setattr(job_view.time, "time", lambda: 14.0)

    def _delete_annotations(*args):
        """Delete the annotations.

        Inputs: `*args` positional arguments. Output: `tuple`. Raises: RuntimeError when validation or the called operation fails.
        """
        image_id = args[2].id
        if image_id == 62:
            return (1, 3, 2)
        if image_id == 63:
            return (0, 0, 0)
        if image_id == 64:
            raise RuntimeError("plugin delete exploded")
        return (0, 0, 0)

    monkeypatch.setattr(job_view, "delete_existing_annotations", _delete_annotations)

    regex_response = inspect.unwrap(job_view.job_progress)(
        request,
        "6" * 32,
        conn=conn,
    )
    regex_payload = _json_payload(regex_response)
    assert regex_payload["finished"] is True
    assert "saved 3+1 variables" in regex_payload["last_log"]

    current_job["value"] = jobs["delete_all_warn"]
    delete_all = inspect.unwrap(job_view.job_progress)(request, "7" * 32, conn=conn)
    assert (
        "warning - only confirmed 1 of 2 deletions"
        in _json_payload(delete_all)["last_log"]
    )

    current_job["value"] = {
        **jobs["delete_all_warn"],
        "job_id": "a" * 32,
        "index": 0,
        "image_ids": [62],
    }
    monkeypatch.setattr(
        job_view, "delete_existing_annotations", lambda *_args: (0, 0, 1)
    )
    delete_all_unconfirmed = inspect.unwrap(job_view.job_progress)(
        request,
        "a" * 32,
        conn=conn,
    )
    assert (
        "deletions could not be confirmed"
        in _json_payload(delete_all_unconfirmed)["last_log"]
    )
    monkeypatch.setattr(job_view, "delete_existing_annotations", _delete_annotations)

    current_job["value"] = jobs["delete_plugin_empty"]
    delete_plugin_empty = inspect.unwrap(job_view.job_progress)(
        request,
        "8" * 32,
        conn=conn,
    )
    assert (
        "no key-value pairs to delete found"
        in _json_payload(delete_plugin_empty)["last_log"]
    )

    current_job["value"] = jobs["delete_plugin_error"]
    delete_plugin_error = inspect.unwrap(job_view.job_progress)(
        request,
        "9" * 32,
        conn=conn,
    )
    assert (
        "ERROR deleting plugin key-value pairs"
        in _json_payload(delete_plugin_error)["last_log"]
    )
