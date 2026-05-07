from __future__ import annotations

from iter_test_helpers import next_or_fail

import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class NoProcessorAvailable(Exception):
    """Stub for OMERO NoProcessorAvailable exceptions."""


TEST_RUNTIME_ROOT = Path(__file__).resolve().parent / "_runtime"


def _install_omero_stub() -> None:
    """Install the OMERO stub.

    Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
    """
    omero_module = types.ModuleType("omero")
    omero_module.NoProcessorAvailable = NoProcessorAvailable

    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rlong = lambda value: value
    rtypes_module.rint = lambda value: value

    omero_module.rtypes = rtypes_module

    sys.modules["omero"] = omero_module
    sys.modules["omero.rtypes"] = rtypes_module


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the required environment.

    Inputs: `monkeypatch` (pytest.MonkeyPatch) pytest monkeypatch fixture. Output: None.
    """
    monkeypatch.setenv("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")
    monkeypatch.setenv("OMERO_IMS_EXPORT_DIR", str(TEST_RUNTIME_ROOT / "export"))
    monkeypatch.setenv("OMERO_IMS_EXPORT_TIMEOUT", "10")
    monkeypatch.setenv("OMERO_IMS_EXPORT_POLL_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_TMP_PATH", str(TEST_RUNTIME_ROOT / "tmp"))
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_TIMEOUT", "1")
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_RETRY_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL", "10")


def _import_imaris_service(monkeypatch: pytest.MonkeyPatch):
    """Import the Imaris service module with test-controlled settings.

    Inputs: `monkeypatch`. Output: `imaris_service`.
    """
    _set_required_env(monkeypatch)
    sys.modules.pop("omero_imaris_connector.imaris_service", None)
    from omero_imaris_connector import imaris_service

    return imaris_service


def test_run_script_retries_until_processor_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the run script retries until processor available execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run script retries until processor available integration.
    Raises: NoProcessorAvailable when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        """Test double for dummy service."""

        def __init__(self) -> None:
            """Create `DummyService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        def runScript(self, *args, **kwargs):
            """Run the script for `DummyService`.

            Inputs: `*args`, `**kwargs`. Output: run script result. Raises:
            NoProcessorAvailable when validation or the called operation fails.
            """
            self.calls += 1
            if self.calls == 1:
                raise NoProcessorAvailable("No processor available")
            return 123

    service = DummyService()

    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [service])
    monkeypatch.setattr(
        imaris_service,
        "_iter_script_methods",
        lambda svc: [("runScript", svc.runScript)],
    )
    monkeypatch.setattr(imaris_service, "SCRIPT_START_TIMEOUT", 1)
    monkeypatch.setattr(imaris_service, "SCRIPT_START_RETRY_INTERVAL", 0)
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_: None)

    job_id = imaris_service._run_script(None, script_id=1, image_id=2, wait_secs=0)
    assert job_id == 123
    assert service.calls == 2


def test_run_script_fails_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm run script fails after timeout exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run script fails after timeout integration.
    Raises: NoProcessorAvailable when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        """Test double for dummy service."""

        @staticmethod
        def runScript(*args, **kwargs):
            """Run the script for `DummyService`.

            Inputs: `*args`, `**kwargs`. Output: None. Raises: NoProcessorAvailable when validation or the called operation fails.
            """
            raise NoProcessorAvailable("No processor available")

    service = DummyService()

    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [service])
    monkeypatch.setattr(
        imaris_service,
        "_iter_script_methods",
        lambda svc: [("runScript", svc.runScript)],
    )
    monkeypatch.setattr(imaris_service, "SCRIPT_START_TIMEOUT", 0)
    monkeypatch.setattr(imaris_service, "SCRIPT_START_RETRY_INTERVAL", 0)
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_: None)

    with pytest.raises(
        RuntimeError, match="No script processor slot available"
    ) as exc_info:
        imaris_service._run_script(None, script_id=1, image_id=2, wait_secs=0)

    assert "Processor service is not running" in str(exc_info.value)


def test_run_script_fails_fast_when_processors_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirm run script fails fast when processors disabled exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run script fails fast when processors disabled integration.
    Raises: NoProcessorAvailable when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        """Test double for dummy service."""

        def __init__(self) -> None:
            """Create `DummyService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        def runScript(self, *args, **kwargs):
            """Run the script for `DummyService`.

            Inputs: `*args`, `**kwargs`. Output: None. Raises: NoProcessorAvailable when validation or the called operation fails.
            """
            self.calls += 1
            raise NoProcessorAvailable("No processor available")

    class DummyConfigService:
        """Test double for dummy config service."""

        @staticmethod
        def getConfigValue(key):
            """Return `DummyConfigService`'s fake config value.

            Inputs: `key`. Output: '0'.
            """
            assert key == "omero.scripts.processors"
            return "0"

    class DummyServiceFactory:
        """Test double for dummy service factory."""

        @staticmethod
        def getConfigService():
            """Return `DummyServiceFactory`'s fake config service.

            Inputs: none. Output: `DummyConfigService` result.
            """
            return DummyConfigService()

    class DummyConn:
        """Test double for dummy conn."""

        def __init__(self) -> None:
            """Create `DummyConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.c = types.SimpleNamespace(sf=DummyServiceFactory())

        @staticmethod
        def isAdmin() -> bool:
            """Report the admin boolean exposed by this OMERO-compatible object.

            Inputs: none. Output: `bool`.
            """
            return True

    service = DummyService()
    conn = DummyConn()

    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [service])
    monkeypatch.setattr(
        imaris_service,
        "_iter_script_methods",
        lambda svc: [("runScript", svc.runScript)],
    )
    monkeypatch.setattr(imaris_service, "SCRIPT_START_TIMEOUT", 999)
    monkeypatch.setattr(imaris_service, "SCRIPT_START_RETRY_INTERVAL", 0)
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="omero.scripts.processors=0"):
        imaris_service._run_script(conn, script_id=1, image_id=2, wait_secs=0)

    assert service.calls == 1


def test_run_script_fails_fast_when_processor_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirm run script fails fast when processor missing exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run script fails fast when processor missing integration.
    Raises: AssertionError, NoProcessorAvailable when validation or external operations
    fail.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        """Test double for dummy service."""

        def __init__(self) -> None:
            """Create `DummyService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        def runScript(self, *args, **kwargs):
            """Run the script for `DummyService`.

            Inputs: `*args`, `**kwargs`. Output: None. Raises: NoProcessorAvailable when validation or the called operation fails.
            """
            self.calls += 1
            raise NoProcessorAvailable("No processor available")

    class DummyConfigService:
        """Test double for dummy config service."""

        @staticmethod
        def getConfigValue(key):
            """Return `DummyConfigService`'s fake config value.

            Inputs: `key` lookup key. Output: `str`. Raises: AssertionError when validation or the called operation fails.
            """
            if key == "omero.scripts.processors":
                return "2"
            if key == "omero.server.nodedescriptors":
                return "master:Blitz-0,Tables-0"
            raise AssertionError(f"Unexpected config key: {key}")

    class DummyServiceFactory:
        """Test double for dummy service factory."""

        @staticmethod
        def getConfigService():
            """Return `DummyServiceFactory`'s fake config service.

            Inputs: none. Output: `DummyConfigService` result.
            """
            return DummyConfigService()

    class DummyConn:
        """Test double for dummy conn."""

        def __init__(self) -> None:
            """Create `DummyConn` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.c = types.SimpleNamespace(sf=DummyServiceFactory())

        @staticmethod
        def isAdmin() -> bool:
            """Report the admin boolean exposed by this OMERO-compatible object.

            Inputs: none. Output: `bool`.
            """
            return True

    service = DummyService()
    conn = DummyConn()

    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [service])
    monkeypatch.setattr(
        imaris_service,
        "_iter_script_methods",
        lambda svc: [("runScript", svc.runScript)],
    )
    monkeypatch.setattr(imaris_service, "SCRIPT_START_TIMEOUT", 999)
    monkeypatch.setattr(imaris_service, "SCRIPT_START_RETRY_INTERVAL", 0)
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        imaris_service,
        "_PROCESSOR_CONFIG_CACHE",
        {"value": None, "checked_at": 0.0},
    )

    with pytest.raises(
        RuntimeError, match="nodedescriptors does not include a Processor"
    ):
        imaris_service._run_script(conn, script_id=1, image_id=2, wait_secs=0)

    assert service.calls == 1


def test_wait_for_process_detaches_after_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify wait for process detaches after completion.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in wait for process detaches after completion.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyProcess:
        """Test double for dummy process."""

        def __init__(self) -> None:
            """Create `DummyProcess` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.closed = False
            self.poll_calls = 0

        def poll(self):
            """Return process completion status.

            Inputs: none. Output: 'FINISHED'.
            """
            self.poll_calls += 1
            return "FINISHED"

        @staticmethod
        def getResults(*_args):
            """Return the results for `DummyProcess`.

            Inputs: `*_args`. Output: `dict`.
            """
            return {"Export_Path": str(TEST_RUNTIME_ROOT / "export.ims")}

        def close(self, *_args):
            """Close `DummyProcess`'s fake resource handle.

            Inputs: `*_args`. Output: None.
            """
            self.closed = True

    proc = DummyProcess()
    monkeypatch.setattr(imaris_service, "EXPORT_POLL_INTERVAL", 0)

    state, outputs = imaris_service._wait_for_process(proc, timeout=1)

    assert state == "FINISHED"
    assert outputs == {"Export_Path": str(TEST_RUNTIME_ROOT / "export.ims")}
    assert proc.closed is True


def test_process_job_files_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Verify process job files round trip.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in process job files round trip.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "PROCESS_JOB_DIR", str(tmp_path))

    payload = {
        "job_id": "proc-1",
        "state": "RUNNING",
        "outputs": None,
        "error": None,
        "created": 123.0,
    }

    imaris_service._write_process_job_file("proc-1", payload)

    assert json.loads((tmp_path / "proc-1.json").read_text(encoding="utf-8")) == payload
    assert imaris_service._read_process_job_file("proc-1") == payload


def test_read_process_job_file_returns_none_for_invalid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Verify read process job file returns none for invalid JSON result shape.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in read process job file returns none for invalid JSON.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "PROCESS_JOB_DIR", str(tmp_path))
    (tmp_path / "proc-1.json").write_text("{bad", encoding="utf-8")

    assert imaris_service._read_process_job_file("proc-1") is None


def test_serialize_outputs_unwraps_rtypes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify serialize outputs unwraps rtypes.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in serialize outputs unwraps rtypes.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    wrapped = SimpleNamespace(val="demo.ims")

    assert imaris_service._serialize_outputs({"Export_Name": wrapped}) == {
        "Export_Name": "demo.ims"
    }
    assert imaris_service._serialize_outputs(["not", "a", "dict"]) is None


def test_poll_process_job_times_out_stale_disk_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Verify poll process job times out stale disk record.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in poll process job times out stale disk record.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "PROCESS_JOB_DIR", str(tmp_path))
    monkeypatch.setattr(imaris_service, "EXPORT_TIMEOUT", 10)
    monkeypatch.setattr(imaris_service.time, "time", lambda: 111.0)

    stale = {
        "job_id": "proc-1",
        "state": "RUNNING",
        "outputs": None,
        "error": None,
        "created": 100.0,
    }
    (tmp_path / "proc-1.json").write_text(json.dumps(stale), encoding="utf-8")

    state, outputs, error = imaris_service._poll_process_job("proc-1")

    assert state == "TIMEOUT"
    assert outputs is None
    assert error == "Timed out waiting for IMS export job."
    assert imaris_service._read_process_job_file("proc-1")["state"] == "TIMEOUT"


def test_poll_process_job_persists_completed_live_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Verify poll process job persists completed live process.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in poll process job persists completed live process.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "PROCESS_JOB_DIR", str(tmp_path))
    monkeypatch.setattr(imaris_service.time, "time", lambda: 105.0)
    detach_calls = []
    export_path = tmp_path / f"{tmp_path.name}.ims"
    monkeypatch.setattr(
        imaris_service,
        "_detach_script_process",
        lambda proc, reason="": detach_calls.append((proc, reason)),
    )

    class DummyProcess:
        """Test double for dummy process."""

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: none. Output: 'finished'.
            """
            return "finished"

        @staticmethod
        def getResults(*_args):
            """Return the results for `DummyProcess`.

            Inputs: `*_args`. Output: `dict`.
            """
            return {"Export_Path": SimpleNamespace(val=str(export_path))}

    proc = DummyProcess()
    imaris_service._PROCESS_JOBS.clear()
    imaris_service._PROCESS_JOBS["proc-1"] = {"handle": proc, "created": 100.0}

    state, outputs, error = imaris_service._poll_process_job("proc-1")

    assert state == "FINISHED"
    assert outputs == {"Export_Path": SimpleNamespace(val=str(export_path))}
    assert error is None
    assert imaris_service._get_process_job("proc-1") is None
    assert detach_calls == [(proc, "process job completed")]
    assert imaris_service._read_process_job_file("proc-1")["outputs"] == {
        "Export_Path": str(export_path)
    }


def test_resolve_async_result_prefers_service_end_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resolve async result prefers service end method result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve async result prefers service end method.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyAsyncResult:
        """Test double for dummy async result."""

        @staticmethod
        def waitForCompleted():
            """Wait for the for Completed for `DummyAsyncResult`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def getResponse():
            """Return the response for `DummyAsyncResult`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

    async_result = DummyAsyncResult()
    svc = SimpleNamespace(end_runScript=lambda result: ("ended", result))

    assert imaris_service._resolve_async_result(
        svc, "begin_runScript", async_result
    ) == ("ended", async_result)


def test_resolve_async_result_waits_and_uses_response_getter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resolve async result waits and uses response getter result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve async result waits and uses response getter.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    calls = []

    class DummyAsyncResult:
        """Test double for dummy async result."""

        @staticmethod
        def waitForCompleted():
            """Wait for the for Completed for `DummyAsyncResult`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            calls.append("wait")

        @staticmethod
        def getResponse():
            """Return the response for `DummyAsyncResult`.

            Inputs: none. Output: `dict`.
            """
            calls.append("response")
            return {"job": 7}

    result = imaris_service._resolve_async_result(
        SimpleNamespace(),
        "runScriptAsync",
        DummyAsyncResult(),
    )

    assert result == {"job": 7}
    assert calls == ["wait", "response"]


def test_call_script_method_retries_after_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirm call script method retries after type error exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when call script method retries after type error stops reporting the expected error.
    Raises: TypeError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "rint", lambda value: ("rint", value))
    seen_wait_values = []

    def fake_method(script_id, inputs, wait_value):
        """Simulate method so the surrounding test controls that dependency.

        Inputs: `script_id`, `inputs`, `wait_value`. Output: `dict`. Raises: TypeError
        when validation or the called operation fails.
        """
        seen_wait_values.append(wait_value)
        if isinstance(wait_value, tuple):
            raise TypeError("unsupported wrapper")
        return {"script_id": script_id, "wait": wait_value}

    result = imaris_service._call_script_method(
        fake_method,
        "runScript",
        17,
        {"Image_ID": 4},
        wait_secs=3,
    )

    assert result == {"script_id": 17, "wait": 3}
    assert seen_wait_values[:2] == [("rint", 3), 3]


def test_get_script_processor_config_caches_admin_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the get script processor config caches admin lookup execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get script processor config caches admin lookup integration.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    time_values = iter((100.0, 101.0))
    calls = {"count": 0}

    class DummyConfigService:
        """Test double for dummy config service."""

        @staticmethod
        def getConfigValue(key):
            """Return `DummyConfigService`'s fake config value.

            Inputs: `key`. Output: '3'.
            """
            calls["count"] += 1
            assert key == "omero.scripts.processors"
            return "3"

    conn = SimpleNamespace(
        isAdmin=lambda: True,
        c=SimpleNamespace(sf=SimpleNamespace(getConfigService=DummyConfigService)),
    )
    monkeypatch.setattr(imaris_service.time, "time", lambda: next_or_fail(time_values))
    monkeypatch.setattr(
        imaris_service,
        "_PROCESSOR_CONFIG_CACHE",
        {"value": None, "checked_at": 0.0},
    )

    assert imaris_service._get_script_processor_config(conn) == "3"
    assert imaris_service._get_script_processor_config(conn) == "3"
    assert calls["count"] == 1


def test_get_script_processor_config_skips_non_admin_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the get script processor config skips non admin sessions execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get script processor config skips non admin sessions integration.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    conn = SimpleNamespace(
        isAdmin=lambda: False,
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getConfigService=lambda: (_ for _ in ()).throw(
                    AssertionError("non-admin sessions must not read config")
                )
            )
        ),
    )

    assert imaris_service._get_script_processor_config(conn) is None
    assert imaris_service._get_node_descriptors_config(conn) is None


def test_exception_helpers_detect_chained_security_and_processor_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirm exception helpers detect chained security and processor errors exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when exception helpers detect chained security and processor errors stops reporting the expected error.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class SecurityViolation(Exception):
        """Test double for security violation behavior in this module."""

    outer = RuntimeError("outer")
    outer.__cause__ = SecurityViolation("permission denied")
    processor_exc = RuntimeError("wrapper")
    processor_exc.__cause__ = NoProcessorAvailable("No processor available")

    assert imaris_service._is_security_violation(outer) is True
    assert imaris_service._is_no_processor_available(processor_exc) is True
    assert (
        "No OMERO script processor is available"
        in imaris_service._format_script_exception(processor_exc)
    )


def test_no_processor_detector_ignores_non_type_omero_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify no processor detector ignores non type OMERO sentinel.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in no processor detector ignores non type OMERO sentinel.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(
        imaris_service.omero,
        "NoProcessorAvailable",
        SimpleNamespace(marker="not-a-type"),
        raising=False,
    )

    assert (
        imaris_service._is_no_processor_available(
            RuntimeError("No processor available")
        )
        is True
    )


def test_extract_job_id_handles_dict_sequence_and_accessor_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify extract job ID handles dict sequence and accessor objects.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in extract job ID handles dict sequence and accessor objects.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    assert imaris_service._extract_job_id({"JobID": SimpleNamespace(val="7")}) == 7
    assert imaris_service._extract_job_id(["bad", SimpleNamespace(val="8")]) == 8
    assert (
        imaris_service._extract_job_id(
            SimpleNamespace(getJobId=lambda: SimpleNamespace(val="9"))
        )
        == 9
    )


def test_get_job_state_and_outputs_supports_outputs_only_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify the get job state and outputs supports outputs only path safety boundary.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions when get job state and outputs supports outputs only path accepts unsafe input.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    outputs = {"Export_Path": SimpleNamespace(val=str(tmp_path / "export.ims"))}
    svc = SimpleNamespace(getJobOutputs=lambda job_id: outputs)
    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [svc])

    state, result_outputs = imaris_service._get_job_state_and_outputs(object(), 12)

    assert state == "FINISHED"
    assert result_outputs is outputs


def test_normalize_job_state_handles_wrapped_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check normalize job state handles wrapped values parsing against the documented contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in normalize job state handles wrapped values.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    assert (
        imaris_service._normalize_job_state(SimpleNamespace(val=" finished "))
        == "FINISHED"
    )
    assert (
        imaris_service._normalize_job_state(
            SimpleNamespace(getValue=lambda: " running ")
        )
        == "RUNNING"
    )
    assert (
        imaris_service._normalize_job_state(SimpleNamespace(name="succeeded"))
        == "SUCCEEDED"
    )


def test_detach_script_process_falls_back_to_close_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the detach script process falls back to close without flag execution contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in detach script process falls back to close without flag integration.
    Raises: TypeError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    calls = []

    class DummyProcess:
        """Test double for dummy process."""

        @staticmethod
        def close(*args):
            """Close `DummyProcess`'s fake resource handle.

            Inputs: `*args` positional arguments. Output: None. Raises: TypeError when validation or the called operation fails.
            """
            calls.append(args)
            if args:
                raise TypeError("close() takes 0 positional arguments")

    imaris_service._detach_script_process(DummyProcess(), reason="unit-test")

    assert calls == [(True,), ()]


def test_raw_file_generator_converts_memoryviews_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify raw file generator converts memoryviews and closes store.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in raw file generator converts memoryviews and closes store.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyStore:
        """Test double for dummy store."""

        def __init__(self):
            """Create `DummyStore` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.closed = False
            self.chunks = [memoryview(b"ab"), b"cd", b""]

        def read(self, _offset, _size):
            """Read data from the resource.

            Inputs: `_offset`, `_size`. Output: `self.chunks.pop` result.
            """
            return self.chunks.pop(0)

        def close(self):
            """Close `DummyStore`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self.closed = True

    store = DummyStore()

    assert list(imaris_service._raw_file_generator(store, 4, chunk_size=2)) == [
        b"ab",
        b"cd",
    ]
    assert store.closed is True


def test_sanitize_filename_strips_control_and_path_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that sanitize filename strips control and path content keeps sensitive data out of output.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when sanitize filename strips control and path content accepts unsafe input.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    assert imaris_service._sanitize_filename("../bad\x00name.ims") == "badname.ims"
    assert imaris_service._sanitize_filename(" .. ") == "export.ims"


def test_response_from_file_annotation_streams_file_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify response from file annotation streams file bytes result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in response from file annotation streams file bytes.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyStore:
        """Test double for dummy store."""

        def __init__(self):
            """Create `DummyStore` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.file_id = None
            self.closed = False
            self.chunks = [b"abc", memoryview(b"def"), b""]

        def setFileId(self, file_id):
            """Set the file ID for `DummyStore`.

            Inputs: `file_id`. Output: None.
            """
            self.file_id = file_id

        def read(self, _offset, _size):
            """Read data from the resource.

            Inputs: `_offset`, `_size`. Output: `self.chunks.pop` result.
            """
            return self.chunks.pop(0)

        def close(self):
            """Close `DummyStore`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self.closed = True

    store = DummyStore()
    original_file = SimpleNamespace(
        getName=lambda: "../unsafe\x00.ims",
        getSize=lambda: 6,
        getId=lambda: SimpleNamespace(val=55),
    )
    file_annotation = SimpleNamespace(getFile=lambda: original_file)
    conn = SimpleNamespace(
        getObject=lambda kind, obj_id: (
            file_annotation if (kind, obj_id) == ("FileAnnotation", 12) else None
        ),
        c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: store)),
    )

    response = imaris_service._response_from_file_annotation(conn, "12")

    assert response["Content-Length"] == "6"
    assert response["Content-Disposition"] == 'attachment; filename="unsafe.ims"'
    assert b"".join(response.streaming_content) == b"abcdef"
    assert store.file_id == 55
    assert store.closed is True


def test_unwrap_rtype_and_file_annotation_response_support_get_value_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify unwrap rtype and file annotation response support get value wrappers result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in unwrap rtype and file annotation response support get value wrappers.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class _GetValueWrapper:
        """Test double for get value wrapper behavior in this module."""

        def __init__(self, value):
            """Create `_GetValueWrapper` with `value`.

            Inputs: `value`. Output: None.
            """
            self._value = value

        def getValue(self):
            """Return `_GetValueWrapper`'s fake OMERO value.

            Inputs: none. Output: `self._value`.
            """
            return self._value

    class DummyStore:
        """Test double for dummy store."""

        def __init__(self):
            """Create `DummyStore` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.file_id = None
            self.closed = False
            self.chunks = [b"ab", b"cd", b""]

        def setFileId(self, file_id):
            """Set the file ID for `DummyStore`.

            Inputs: `file_id`. Output: None.
            """
            self.file_id = file_id

        def read(self, _offset, _size):
            """Read data from the resource.

            Inputs: `_offset`, `_size`. Output: `self.chunks.pop` result.
            """
            return self.chunks.pop(0)

        def close(self):
            """Close `DummyStore`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self.closed = True

    store = DummyStore()
    original_file = SimpleNamespace(
        getName=lambda: _GetValueWrapper("../wrapped export.ims"),
        getSize=lambda: _GetValueWrapper("4"),
        getId=lambda: _GetValueWrapper("66"),
    )
    file_annotation = SimpleNamespace(getFile=lambda: original_file)
    conn = SimpleNamespace(
        getObject=lambda kind, obj_id: (
            file_annotation if (kind, obj_id) == ("FileAnnotation", 12) else None
        ),
        c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: store)),
    )

    assert imaris_service._unwrap_rtype(_GetValueWrapper("wrapped")) == "wrapped"

    response = imaris_service._response_from_file_annotation(conn, "12")

    assert response["Content-Length"] == "4"
    assert (
        response["Content-Disposition"] == 'attachment; filename="wrapped export.ims"'
    )
    assert b"".join(response.streaming_content) == b"abcd"
    assert store.file_id == 66
    assert store.closed is True


def test_build_download_response_prefers_safe_export_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify build download response prefers safe export path result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when build download response prefers safe export path accepts unsafe input.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        export_root = Path(tmpdir) / "exports"
        export_file = export_root / "nested" / "demo.ims"
        export_file.parent.mkdir(parents=True, exist_ok=True)
        export_file.write_bytes(b"payload")
        monkeypatch.setattr(imaris_service, "EXPORT_ROOT", str(export_root))

        response = imaris_service._build_download_response(
            object(),
            {"Export_Path": str(export_file), "Export_Name": "../safe export.ims"},
        )

        try:
            assert response["Content-Type"] == "application/octet-stream"
            assert b"".join(response.streaming_content) == b"payload"
            assert "safe export.ims" in response["Content-Disposition"]
        finally:
            response.close()


def test_build_download_response_falls_back_to_file_annotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify build download response falls back to file annotation result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in build download response falls back to file annotation.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    sentinel = object()
    monkeypatch.setattr(
        imaris_service,
        "_response_from_file_annotation",
        lambda conn, file_ann_id, filename_fallback=None: sentinel,
    )

    assert (
        imaris_service._build_download_response(
            object(),
            {"File_Annotation_Id": "44", "Export_Name": "export.ims"},
        )
        is sentinel
    )


def test_build_download_response_reports_missing_or_invalid_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify build download response reports missing or invalid paths result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in build download response reports missing or invalid paths.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        export_root = Path(tmpdir) / "exports"
        export_root.mkdir(parents=True, exist_ok=True)
        outside_file = Path(tmpdir) / "outside.ims"
        outside_file.write_bytes(b"outside")
        monkeypatch.setattr(imaris_service, "EXPORT_ROOT", str(export_root))

        missing = imaris_service._build_download_response(object(), {})
        outside = imaris_service._build_download_response(
            object(),
            {"Export_Path": str(outside_file)},
        )
        absent = imaris_service._build_download_response(
            object(),
            {"Export_Path": str(export_root / "missing.ims")},
        )

    assert missing.status_code == 500
    assert missing.content.decode("utf-8") == "IMS export did not return a file path."
    assert outside.status_code == 500
    assert outside.content.decode("utf-8") == "IMS export path is invalid."
    assert absent.status_code == 404
    assert absent.content.decode("utf-8") == "IMS export file not found on server."


def test_register_and_monitor_process_job_persists_running_and_finished_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify register and monitor process job persists running and finished state.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in register and monitor process job persists running and finished state.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "PROCESS_JOB_DIR", str(tmp_path))
    export_name = f"{tmp_path.name}.ims"
    monkeypatch.setattr(
        imaris_service,
        "_wait_for_process",
        lambda proc, timeout: (
            "FINISHED",
            {"Export_Name": SimpleNamespace(val=export_name)},
        ),
    )
    monkeypatch.setattr(
        imaris_service.uuid, "uuid4", lambda: SimpleNamespace(hex="abc123")
    )

    class _ImmediateThread:
        """Test double for immediate thread behavior in this module."""

        def __init__(self, target, args=(), daemon=False):
            """Create `_ImmediateThread` with `target`, `args`, and `daemon`.

            Inputs: `target`, `args`, `daemon`. Output: None.
            """
            self._target = target
            self._args = args
            self.daemon = daemon

        def start(self):
            """Start `_ImmediateThread`'s fake operation.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self._target(*self._args)

    monkeypatch.setattr(imaris_service.threading, "Thread", _ImmediateThread)

    job_id = imaris_service._register_process_job(object())
    record = json.loads((tmp_path / f"{job_id}.json").read_text(encoding="utf-8"))

    assert job_id == "proc-abc123"
    assert record["state"] == "FINISHED"
    assert record["outputs"] == {"Export_Name": export_name}
    assert imaris_service._get_process_job(job_id) is None


def test_poll_process_job_covers_unknown_job_ids_and_live_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify poll process job covers unknown job IDs and live timeouts.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in poll process job covers unknown job IDs and live timeouts.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "_read_process_job_file", lambda job_id: None)

    assert imaris_service._poll_process_job("missing") == (
        None,
        None,
        "Unknown job id",
    )

    detached = []
    monkeypatch.setattr(
        imaris_service,
        "_detach_script_process",
        lambda proc, reason="": detached.append((proc, reason)),
    )
    monkeypatch.setattr(imaris_service, "EXPORT_TIMEOUT", 10)
    monkeypatch.setattr(imaris_service.time, "time", lambda: 100.0)
    handle = object()
    imaris_service._PROCESS_JOBS["proc-live"] = {
        "handle": handle,
        "created": 0.0,
    }

    assert imaris_service._poll_process_job("proc-live") == (
        "TIMEOUT",
        None,
        "Timed out waiting for IMS export job.",
    )
    assert detached == [(handle, "process job timeout")]
    assert imaris_service._get_process_job("proc-live") is None


def test_script_service_discovery_iteration_and_job_queries_cover_fallback_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify the script service discovery iteration and job queries fallback paths.

    Inputs: `monkeypatch` (pytest.MonkeyPatch) pytest monkeypatch fixture, `tmp_path`
    (Path) temporary path fixture. Output: fails on regressions in script discovery or job lookup
    fallback behavior. Raises: RuntimeError, TypeError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    resolved_export = tmp_path / "export.ims"

    raw_service = object()

    class _Conn:
        """Test double for conn behavior in this module."""

        @staticmethod
        def getScriptService():
            """Return the fake script service value used by this test double.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("gateway unavailable")

        c = SimpleNamespace(sf=SimpleNamespace(getScriptService=lambda: raw_service))

    assert imaris_service._get_script_services(_Conn()) == [raw_service]

    class _Service:
        """Test double for service behavior in this module."""

        @staticmethod
        def runScriptAsync():
            """The async script path.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def executeScript():
            """Execute the script for `_Service`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def begin_runScript():
            """Record that the fake script runner started execution.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def canRunScript():
            """Report the run script boolean exposed by this OMERO-compatible object.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

    method_names = [name for name, _ in imaris_service._iter_script_methods(_Service())]
    assert "runScriptAsync" in method_names
    assert "executeScript" in method_names
    assert "begin_runScript" not in method_names
    assert "canRunScript" not in method_names

    calls = []

    def async_method(*args):
        """Return the async method.

        Inputs: `*args` positional arguments. Output: `str`. Raises: TypeError for
        invalid call signatures.
        """
        calls.append(args)
        if len(args) != 2:
            raise TypeError("wrong signature")
        return "async-result"

    assert (
        imaris_service._call_script_method(
            async_method, "runScriptAsync", 7, {"a": 1}, 5
        )
        == "async-result"
    )
    assert calls[0] == (7, {"a": 1})

    class _DedicatedStateService:
        """Test double for dedicated state service behavior in this module."""

        @staticmethod
        def getJobStatus(job_id):
            """Return the fake job status value used by this test double.

            Inputs: `job_id`. Output: 'FINISHED'.
            """
            return "FINISHED"

        @staticmethod
        def getJobOutputs(job_id):
            """Return the fake job outputs value used by this test double.

            Inputs: `job_id`. Output: dict.
            """
            return {"Export_Path": str(resolved_export)}

    monkeypatch.setattr(
        imaris_service, "_get_script_services", lambda conn: [_DedicatedStateService()]
    )
    assert imaris_service._get_job_state_and_outputs(object(), 11) == (
        "FINISHED",
        {"Export_Path": str(resolved_export)},
    )

    class _JobInfoService:
        """Test double for job info service behavior in this module."""

        @staticmethod
        def getJobs():
            """Return the jobs for `_JobInfoService`.

            Inputs: none. Output: `list`.
            """
            return [
                SimpleNamespace(
                    id=SimpleNamespace(val=77),
                    status=SimpleNamespace(val="RUNNING"),
                )
            ]

    monkeypatch.setattr(
        imaris_service, "_get_script_services", lambda conn: [_JobInfoService()]
    )
    assert imaris_service._get_job_state_and_outputs(object(), 77) == ("RUNNING", None)


def test_find_script_id_and_async_result_resolution_prefer_official_paths_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify the find script ID and async result resolution prefer official paths and fallbacks execution contract.

    Inputs: `monkeypatch` (pytest.MonkeyPatch) pytest monkeypatch fixture, `tmp_path`
    (Path) temporary path fixture. Output: None. Raises: RuntimeError when validation or
    external operations fail.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    official_script_path = str(Path("omero") / "export" / imaris_service.SCRIPT_NAME)
    resolved_export = str(tmp_path / f"{tmp_path.name}.ims")

    script_service = SimpleNamespace(
        getScripts=lambda: [
            SimpleNamespace(
                name=imaris_service.SCRIPT_NAME,
                path=str(Path("custom") / imaris_service.SCRIPT_NAME),
                id=SimpleNamespace(val=9),
            ),
            SimpleNamespace(
                name=imaris_service.SCRIPT_NAME,
                path=official_script_path,
                id=SimpleNamespace(val=7),
            ),
            SimpleNamespace(
                name=imaris_service.SCRIPT_NAME,
                path=official_script_path,
                id=SimpleNamespace(val=11),
            ),
        ]
    )
    monkeypatch.setattr(
        imaris_service, "_get_script_services", lambda conn: [script_service]
    )

    assert imaris_service._find_script_id(object()) == 11

    class _AsyncResult:
        """Test double for async result behavior in this module."""

        @staticmethod
        def waitForCompleted():
            """Wait for the for Completed for `_AsyncResult`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            raise RuntimeError("wait failed")

        @staticmethod
        def getResponse():
            """Return the response for `_AsyncResult`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("response missing")

        @staticmethod
        def getResults():
            """Return the results for `_AsyncResult`.

            Inputs: none. Output: `dict`.
            """
            return {"Export_Path": resolved_export}

    class _AsyncService:
        """Test double for async service behavior in this module."""

        @staticmethod
        def end_runScript(result):
            """Record the fake script runner result or raise the configured failure.

            Inputs: `result`. Output: None. Raises: RuntimeError when validation or
            external operations fail.
            """
            raise RuntimeError("end failed")

    assert imaris_service._resolve_async_result(
        _AsyncService(),
        "begin_runScript",
        _AsyncResult(),
    ) == {"Export_Path": resolved_export}


def test_wait_for_process_timeout_and_request_bool_helpers_cover_remaining_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify wait for process timeout and request bool helpers cover remaining edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in wait for process timeout and request bool helpers cover remaining edges.
    Raises: AssertionError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    detached = []

    class _NeverFinishes:
        """Test double for never finishes behavior in this module."""

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        @staticmethod
        def getResults(*_args):
            """Return the results for `_NeverFinishes`.

            Inputs: `*_args`. Output: None. Raises: AssertionError when validation or
            external operations fail.
            """
            raise AssertionError("results should not be requested")

    time_values = iter([0.0, 0.5, 1.5])
    monkeypatch.setattr(imaris_service.time, "time", lambda: next_or_fail(time_values))
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        imaris_service,
        "_detach_script_process",
        lambda proc, reason="": detached.append((proc, reason)),
    )

    assert imaris_service._wait_for_process(_NeverFinishes(), timeout=1) == (None, None)
    assert detached[0][1] == "process wait completed"
    assert imaris_service._bool_from_request("YES") is True
    assert imaris_service._bool_from_request("0") is False
    assert imaris_service._bool_from_request(None) is None


def test_imaris_helper_fallbacks_cover_service_discovery_and_job_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify imaris helper fallbacks cover service discovery and job queries.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris helper fallbacks cover service discovery and job queries.
    Raises: RuntimeError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class _BrokenConn:
        """Test double for broken conn behavior in this module."""

        @staticmethod
        def getScriptService():
            """Return the fake script service value used by this test double.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("gateway missing")

        c = SimpleNamespace(
            sf=SimpleNamespace(
                getScriptService=lambda: (_ for _ in ()).throw(
                    RuntimeError("raw missing")
                )
            )
        )

    assert imaris_service._get_script_services(_BrokenConn()) == []

    class _BrokenService:
        """Test double for broken service behavior in this module."""

        @staticmethod
        def getScripts():
            """Return the scripts for `_BrokenService`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("script listing failed")

    monkeypatch.setattr(
        imaris_service, "_get_script_services", lambda conn: [_BrokenService()]
    )
    assert imaris_service._find_script_id(object()) is None
    assert (
        imaris_service._resolve_async_result(SimpleNamespace(), "runScript", None)
        is None
    )
    assert imaris_service._resolve_async_result(
        SimpleNamespace(), "runScript", {"job": 4}
    ) == {"job": 4}

    class _StateService:
        """Test double for state service behavior in this module."""

        @staticmethod
        def getJobStatus(_job_id):
            """Return the fake job status value used by this test double.

            Inputs: `_job_id`. Output: None. Raises: RuntimeError when validation or
            external operations fail.
            """
            raise RuntimeError("status failed")

        @staticmethod
        def getJobOutputs(_job_id):
            """Return the fake job outputs value used by this test double.

            Inputs: `_job_id`. Output: None. Raises: RuntimeError when validation or
            external operations fail.
            """
            raise RuntimeError("outputs failed")

        @staticmethod
        def getJobs():
            """Return the jobs for `_StateService`.

            Inputs: none. Output: `list`.
            """
            return [
                SimpleNamespace(
                    id=SimpleNamespace(val="bad"), status=SimpleNamespace(val="RUNNING")
                ),
                SimpleNamespace(
                    id=SimpleNamespace(val=19), status=SimpleNamespace(val="RUNNING")
                ),
            ]

    monkeypatch.setattr(
        imaris_service, "_get_script_services", lambda conn: [_StateService()]
    )
    assert imaris_service._get_job_state_and_outputs(object(), 19) == ("RUNNING", None)


def test_imaris_helper_fallbacks_cover_call_signatures_and_config_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify imaris helper fallbacks cover call signatures and config failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris helper fallbacks cover call signatures and config failures.
    Raises: AssertionError, TypeError, fail when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "rint", lambda value: ("rint", value))

    seen_args = []

    def _four_arg_method(*args):
        """Return the four arg method.

        Inputs: `*args` positional arguments. Output: `str`. Raises: TypeError for
        invalid call signatures.
        """
        seen_args.append(args)
        if len(args) != 4:
            raise TypeError("need four args")
        return "ok"

    assert (
        imaris_service._call_script_method(
            _four_arg_method,
            "runScript",
            7,
            {"Image_ID": 2},
            wait_secs=None,
        )
        == "ok"
    )
    assert seen_args[-1] == (7, {"Image_ID": 2}, None, None)

    with pytest.raises(TypeError):
        imaris_service._call_script_method(
            lambda *_args: (_ for _ in ()).throw(TypeError("bad signature")),
            "runScript",
            7,
            {"Image_ID": 2},
            wait_secs=None,
        )

    class SecurityViolation(Exception):
        """Test double for security violation behavior in this module."""

    class _ConfigService:
        """Test double for config service behavior in this module."""

        def __init__(self, *, processors="2", descriptors="Processor-0", fail=None):
            """Create `_ConfigService` with its default state.

            Inputs: `processors`, `descriptors`, `fail`. Output: None.
            """
            self.processors = processors
            self.descriptors = descriptors
            self.fail = fail

        def getConfigValue(self, key):
            """Return `_ConfigService`'s fake config value.

            Inputs: `key` lookup key. Output: `processors`. Raises: AssertionError, fail
            when validation or the called operation fails.
            """
            if self.fail is not None:
                raise self.fail
            if key == "omero.scripts.processors":
                return self.processors
            if key == "omero.server.nodedescriptors":
                return self.descriptors
            raise AssertionError(f"Unexpected key: {key}")

    monkeypatch.setattr(
        imaris_service,
        "_PROCESSOR_CONFIG_CACHE",
        {"value": None, "checked_at": 0.0},
    )
    monkeypatch.setattr(imaris_service.time, "time", lambda: 100.0)

    conn_none = SimpleNamespace(
        isAdmin=lambda: True,
        c=SimpleNamespace(sf=SimpleNamespace(getConfigService=lambda: None)),
    )
    assert imaris_service._get_script_processor_config(conn_none) is None

    conn_security = SimpleNamespace(
        isAdmin=lambda: True,
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getConfigService=lambda: _ConfigService(
                    fail=SecurityViolation("denied")
                )
            )
        ),
    )
    assert imaris_service._get_script_processor_config(conn_security) is None

    conn_descriptors = SimpleNamespace(
        isAdmin=lambda: True,
        c=SimpleNamespace(
            sf=SimpleNamespace(getConfigService=lambda: _ConfigService(descriptors=" "))
        ),
    )
    assert imaris_service._get_node_descriptors_config(conn_descriptors) is None


def test_imaris_file_and_output_helpers_cover_invalid_annotations_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check imaris file and output helpers cover invalid annotations and cleanup cleanup behavior.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris file and output helpers cover invalid annotations and cleanup.
    Raises: RuntimeError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    assert imaris_service._infer_finished_from_outputs(None) is False
    assert (
        imaris_service._infer_finished_from_outputs({"Export_Name": "demo.ims"}) is True
    )
    assert (
        imaris_service._response_from_file_annotation(
            SimpleNamespace(getObject=lambda *_args: None), "bad"
        )
        is None
    )
    assert (
        imaris_service._response_from_file_annotation(
            SimpleNamespace(getObject=lambda *_args: None),
            "12",
        )
        is None
    )

    conn_missing_file = SimpleNamespace(
        getObject=lambda kind, obj_id: SimpleNamespace(getFile=lambda: None),
    )
    assert (
        imaris_service._response_from_file_annotation(conn_missing_file, "12") is None
    )

    class _BrokenStore:
        """Test double for broken store behavior in this module."""

        def __init__(self):
            """Create `_BrokenStore` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.closed = False

        @staticmethod
        def read(_offset, _size):
            """Read data from the resource.

            Inputs: `_offset`, `_size`. Output: b''.
            """
            return b""

        def close(self):
            """Close `_BrokenStore`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            self.closed = True
            raise RuntimeError("close failed")

    store = _BrokenStore()
    assert (
        list(imaris_service._raw_file_generator(store, size=None, chunk_size=2)) == []
    )
    assert store.closed is True

    class _InvalidSizeFile:
        """Test double for invalid size file behavior in this module."""

        @staticmethod
        def getName():
            """Return `_InvalidSizeFile`'s fake object name.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("name missing")

        @staticmethod
        def getSize():
            """Return the size for `_InvalidSizeFile`.

            Inputs: none. Output: `str`.
            """
            return "bad-size"

        @staticmethod
        def getId():
            """Return `_InvalidSizeFile`'s fake OMERO identifier.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val=77)

    raw_store = SimpleNamespace(
        setFileId=lambda file_id: setattr(raw_store, "file_id", file_id),
        read=lambda _offset, _size: b"",
        close=lambda: None,
    )
    file_annotation = SimpleNamespace(getFile=_InvalidSizeFile)
    conn = SimpleNamespace(
        getObject=lambda kind, obj_id: (
            file_annotation if (kind, obj_id) == ("FileAnnotation", 12) else None
        ),
        c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
    )

    response = imaris_service._response_from_file_annotation(
        conn,
        "12",
        filename_fallback="fallback.ims",
    )

    assert "Content-Length" not in response
    assert response["Content-Disposition"] == 'attachment; filename="fallback.ims"'


def test_imaris_helper_edges_cover_runtime_fallbacks_and_filename_safety(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify imaris helper edges cover runtime fallbacks and filename safety.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in imaris helper edges cover runtime fallbacks and filename safety.
    Raises: AttributeError, RuntimeError when validation or the called operation fails.
    """
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    assert imaris_service._get_script_services(None) == []

    direct_service = object()
    raw_service = object()

    class _Conn:
        """Test double for conn behavior in this module."""

        @staticmethod
        def getScriptService():
            """Return the fake script service value used by this test double.

            Inputs: none. Output: `direct_service`.
            """
            return direct_service

        c = SimpleNamespace(sf=SimpleNamespace(getScriptService=lambda: raw_service))

    assert imaris_service._get_script_services(_Conn()) == [direct_service, raw_service]

    monkeypatch.setattr(imaris_service.time, "time", lambda: 5.0)
    monkeypatch.setattr(imaris_service, "EXPORT_TIMEOUT", 10)
    imaris_service._PROCESS_JOBS["proc-running"] = {
        "handle": SimpleNamespace(
            poll=lambda: (_ for _ in ()).throw(RuntimeError("poll exploded"))
        ),
        "created": 0.0,
    }
    assert imaris_service._poll_process_job("proc-running") == (None, None, None)

    detached = []
    persisted = {}
    monkeypatch.setattr(
        imaris_service,
        "_detach_script_process",
        lambda proc, reason="": detached.append((proc, reason)),
    )
    monkeypatch.setattr(
        imaris_service,
        "_write_process_job_file",
        persisted.setdefault,
    )
    handle = SimpleNamespace(
        poll=lambda: "FINISHED",
        getResults=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("results exploded")
        ),
    )
    imaris_service._PROCESS_JOBS["proc-finished"] = {
        "handle": handle,
        "created": 0.0,
    }
    assert imaris_service._poll_process_job("proc-finished") == (
        "FINISHED",
        None,
        None,
    )
    assert detached[-1] == (handle, "process job completed")
    assert persisted["proc-finished"]["outputs"] is None

    class _ScriptId:
        """Test double for script identifier behavior in this module."""

        def __init__(self):
            """Create `_ScriptId` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.calls = 0

        @property
        def val(self):
            """Return the fake value.

            Inputs: none. Output: val result.
            """
            self.calls += 1
            return None if self.calls == 1 else 13

    official_script = SimpleNamespace(
        name=imaris_service.SCRIPT_NAME,
        path="omero/export/IMS_Export.py",
        id=_ScriptId(),
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [SimpleNamespace(getScripts=lambda: [official_script])],
    )
    assert imaris_service._find_script_id(object()) == 13

    class _BrokenAsyncResult:
        """Test double for broken async result behavior in this module."""

        @staticmethod
        def waitForCompleted():
            """Wait for the for Completed for `_BrokenAsyncResult`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            return None

        @staticmethod
        def getResponse():
            """Return the response for `_BrokenAsyncResult`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("response exploded")

        @staticmethod
        def getResult():
            """Return the result for `_BrokenAsyncResult`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("result exploded")

        @staticmethod
        def getResults():
            """Return the results for `_BrokenAsyncResult`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("results exploded")

        @staticmethod
        def get():
            """Return the requested value.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("get exploded")

    async_result = _BrokenAsyncResult()
    assert (
        imaris_service._resolve_async_result(
            SimpleNamespace(),
            "runScript_async",
            async_result,
        )
        is async_result
    )

    class _BrokenService:
        """Test double for broken service behavior in this module."""

        def __getattr__(self, name):
            """Return a dynamic attribute value by name.

            Inputs: `name` name. Output: None. Raises: AttributeError when validation or
            external operations fail.
            """
            raise AttributeError("attribute exploded")

        def __dir__(self):
            """Return advertised dynamic attributes.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("dir exploded")

    assert list(imaris_service._iter_script_methods(_BrokenService())) == []
    assert imaris_service._extract_job_id(None) is None
    assert (
        imaris_service._extract_job_id(
            SimpleNamespace(
                getId=lambda: "bad",
                getValue=lambda: "also-bad",
            )
        )
        is None
    )

    monkeypatch.setattr(imaris_service.os, "altsep", "\\", raising=False)
    assert imaris_service._sanitize_filename("") == "export.ims"
    assert (
        imaris_service._sanitize_filename(r"..\\unsafe\name.ims") == "__unsafe_name.ims"
    )

    raw_store = SimpleNamespace(
        setFileId=lambda file_id: setattr(raw_store, "file_id", file_id),
        read=lambda _offset, _size: b"",
        close=lambda: None,
    )

    class _OriginalFile:
        """Test double for original file behavior in this module."""

        @staticmethod
        def getName():
            """Return `_OriginalFile`'s fake object name.

            Inputs: none. Output: '..\\\\unsafe\\name.ims'.
            """
            return r"..\\unsafe\name.ims"

        @staticmethod
        def getSize():
            """Return the size for `_OriginalFile`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("size exploded")

        @staticmethod
        def getId():
            """Return `_OriginalFile`'s fake OMERO identifier.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(val=77)

    def _get_original_file_annotation(kind, obj_id):
        """Return original file annotation.

        Inputs: `kind`, `obj_id`. Output: `SimpleNamespace` result.
        """
        assert (kind, obj_id) == ("FileAnnotation", 12)
        return SimpleNamespace(getFile=_OriginalFile)

    conn = SimpleNamespace(
        getObject=_get_original_file_annotation,
        c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
    )
    response = imaris_service._response_from_file_annotation(conn, "12")
    assert "Content-Length" not in response
    assert response["Content-Disposition"] == 'attachment; filename="__unsafe_name.ims"'
