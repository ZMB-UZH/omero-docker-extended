from __future__ import annotations

from types import SimpleNamespace

from omeroweb_import.strings import errors as import_errors
from omeroweb_import.views import core_functions


class _FakeGatewayConnection:
    """Test double for fake gateway connection."""

    def __init__(
        self,
        *,
        connect_result=True,
        connect_exception=None,
        last_error="last-error",
        group_calls=None,
    ):
        """Initialize the instance.

        Inputs: `connect_result`, `connect_exception`, `last_error`, `group_calls`.
        Output: None.
        """
        self._connect_result = connect_result
        self._connect_exception = connect_exception
        self._last_error = last_error
        self.closed = False
        self.group_calls = group_calls if group_calls is not None else []
        self.SERVICE_OPTS = SimpleNamespace(setOmeroGroup=self.group_calls.append)

    def connect(self):
        """Open the connection.

        Inputs: none. Output: `self._connect_result`. Raises on invalid or unavailable
        state.

        state.
        """
        if self._connect_exception is not None:
            raise self._connect_exception
        return self._connect_result

    def getLastError(self):
        """Return Last Error.

        Inputs: none. Output: `self._last_error`.
        """
        return self._last_error

    def close(self):
        """Close the resource.

        Inputs: none. Output: None.
        """
        self.closed = True


def test_prepare_job_import_datasets_marks_missing_roots_and_dataset_failures(
    tmp_path, monkeypatch
):
    """Verify prepare job import datasets marks missing roots and dataset failures.

    Inputs: `tmp_path`, `monkeypatch`. Output: `updated_jobs[job_id]`.
    """
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)

    updated_jobs = {}

    def update_job(job_id, mutator):
        """Update job.

        Inputs: `job_id`, `mutator`. Output: `updated_jobs[job_id]`.
        """
        current = dict(updated_jobs.get(job_id, {"job_id": job_id}))
        updated_jobs[job_id] = mutator(current)
        return updated_jobs[job_id]

    monkeypatch.setattr(core_functions, "_update_job", update_job)

    job_id = "a" * 32
    missing_root_job, missing_root_error = core_functions._prepare_job_import_datasets(
        job_id,
        {"job_id": job_id, "status": "ready"},
        conn=object(),
    )
    assert missing_root_error == import_errors.upload_folder_missing_on_server()
    assert missing_root_job["status"] == "error"
    assert missing_root_job["errors"] == [missing_root_error]

    updated_jobs.clear()
    (upload_root / job_id).mkdir()
    monkeypatch.setattr(
        core_functions, "_build_import_units", lambda job_dict, root: ["entry"]
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job_dict, entries, conn=None: (False, "dataset prep failed"),
    )

    dataset_error_job, dataset_error = core_functions._prepare_job_import_datasets(
        job_id,
        {"job_id": job_id, "status": "ready"},
        conn=object(),
    )
    assert dataset_error == "dataset prep failed"
    assert dataset_error_job["status"] == "error"
    assert dataset_error_job["errors"] == ["dataset prep failed"]


def test_prepare_job_import_datasets_reports_save_failures(tmp_path, monkeypatch):
    """Verify prepare job import datasets reports save failures.

    Inputs: `tmp_path`, `monkeypatch`. Output: None.
    """
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    job_id = "b" * 32
    (upload_root / job_id).mkdir()

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(
        core_functions, "_build_import_units", lambda job_dict, root: ["entry"]
    )
    monkeypatch.setattr(
        core_functions,
        "_ensure_job_dataset_targets",
        lambda job_dict, entries, conn=None: (True, None),
    )
    monkeypatch.setattr(core_functions, "_save_job", lambda job_dict: False)

    prepared_job, error = core_functions._prepare_job_import_datasets(
        job_id,
        {"job_id": job_id, "status": "ready"},
        conn=object(),
    )
    assert prepared_job is None
    assert error == import_errors.unable_update_upload_job_state()


def test_open_admin_connection_and_group_name_cover_failure_and_success_paths(
    monkeypatch,
):
    """Verify open admin connection and group name cover failure and success paths.

    Inputs: `monkeypatch`. Output: `conn`.
    """
    monkeypatch.delenv("ROOTPASS", raising=False)
    assert core_functions._open_admin_connection("omeroserver", 4064) is None

    monkeypatch.setenv("ROOTPASS", "root-password")
    monkeypatch.setattr(
        core_functions,
        "_get_job_service_credentials",
        lambda: ("job-service", "unused", "", False),
    )

    connections = [
        _FakeGatewayConnection(connect_result=False),
        _FakeGatewayConnection(connect_exception=RuntimeError("connect exploded")),
        _FakeGatewayConnection(connect_result=True),
    ]
    created = []

    def gateway(*args, **kwargs):
        """Gateway.

        Inputs: `*args`, `**kwargs`. Output: `conn`.
        """
        conn = connections.pop(0)
        created.append((args, kwargs, conn))
        return conn

    monkeypatch.setattr(core_functions, "BlitzGateway", gateway)

    assert core_functions._open_admin_connection("omeroserver", 4064) is None
    assert created[0][2].closed is True

    assert core_functions._open_admin_connection("omeroserver", 4064) is None
    assert created[1][2].closed is True

    success = core_functions._open_admin_connection("omeroserver", 4064)
    assert success is created[2][2]
    assert success.group_calls == ["-1"]
    assert created[2][1]["secure"] is False

    cached_name = core_functions._resolve_group_name(None, 1, " users ")
    assert cached_name == "users"
    assert core_functions._resolve_group_name(None, 1) is None
    assert (
        core_functions._resolve_group_name(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("lookup failed")
                )
            ),
            4,
        )
        is None
    )
    assert (
        core_functions._resolve_group_name(
            SimpleNamespace(getObject=lambda *_args, **_kwargs: None),
            4,
        )
        is None
    )
    assert (
        core_functions._resolve_group_name(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: SimpleNamespace(
                    getName=lambda: (_ for _ in ()).throw(RuntimeError("bad name"))
                )
            ),
            4,
        )
        is None
    )
    assert (
        core_functions._resolve_group_name(
            SimpleNamespace(
                getObject=lambda *_args, **_kwargs: SimpleNamespace(
                    getName=lambda: "managed-group"
                )
            ),
            4,
        )
        == "managed-group"
    )


def test_job_service_credentials_and_session_helpers_cover_env_and_cleanup(monkeypatch):
    """Verify job service credentials and session helpers cover environment and cleanup.

    Inputs: `monkeypatch`. Output: None.
    """
    monkeypatch.delenv(core_functions.JOB_SERVICE_USER_ENV, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_AUTH_ENV, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_GROUP_ENV, raising=False)
    monkeypatch.delenv(core_functions.JOB_SERVICE_SECURE_ENV, raising=False)
    monkeypatch.setenv(core_functions.JOB_SERVICE_USER_ENV_FALLBACK, "fallback-user")
    monkeypatch.setenv(core_functions.JOB_SERVICE_AUTH_ENV_FALLBACK, "fallback-pass")
    monkeypatch.setenv(core_functions.JOB_SERVICE_GROUP_ENV_FALLBACK, "7")
    monkeypatch.setenv(core_functions.JOB_SERVICE_SECURE_ENV_FALLBACK, "off")

    assert core_functions._get_job_service_credentials() == (
        "fallback-user",
        "fallback-pass",
        "7",
        False,
    )

    scoped_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=lambda value: None)
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda session_key, host, port: scoped_conn,
    )
    assert (
        core_functions._open_group_scoped_session_connection("", "host", 4064) is None
    )
    assert (
        core_functions._open_group_scoped_session_connection(
            "session-key",
            "host",
            4064,
            group_id=5,
        )
        is scoped_conn
    )

    failing_group_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(
            setOmeroGroup=lambda value: (_ for _ in ()).throw(
                RuntimeError("scope fail")
            )
        )
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda session_key, host, port: failing_group_conn,
    )
    assert (
        core_functions._open_group_scoped_session_connection(
            "session-key",
            "host",
            4064,
            group_id=5,
        )
        is failing_group_conn
    )


def test_background_connection_helpers_require_independent_session_keys(monkeypatch):
    """Verify background connection helpers require independent session keys.

    Inputs: `monkeypatch`. Output: None.
    """
    assert (
        core_functions._open_user_owned_background_connection(
            "alice",
            purpose="dataset preparation",
        )
        is None
    )

    group_calls = []
    session_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(setOmeroGroup=group_calls.append)
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda session_key, host, port: session_conn,
    )
    assert (
        core_functions._open_user_owned_background_connection(
            "alice",
            session_key="session-key",
            host="omeroserver",
            port=4064,
            group_id=4,
            purpose="dataset preparation",
        )
        is session_conn
    )
    assert group_calls == ["4"]

    warning_conn = SimpleNamespace(
        SERVICE_OPTS=SimpleNamespace(
            setOmeroGroup=lambda value: (_ for _ in ()).throw(
                RuntimeError("scope fail")
            )
        )
    )
    monkeypatch.setattr(
        core_functions,
        "_open_session_connection",
        lambda session_key, host, port: warning_conn,
    )
    assert (
        core_functions._open_user_owned_background_connection(
            "alice",
            session_key="session-key",
            host="omeroserver",
            port=4064,
            group_id=4,
            purpose="dataset preparation",
        )
        is warning_conn
    )
