from __future__ import annotations

import builtins
import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class NoProcessorAvailable(Exception):
    """Stub for OMERO NoProcessorAvailable exceptions."""


TEST_RUNTIME_ROOT = __import__("pathlib").Path(__file__).resolve().parent / "_runtime"


def _install_omero_stub() -> None:
    omero_module = types.ModuleType("omero")
    omero_module.NoProcessorAvailable = NoProcessorAvailable

    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rlong = lambda value: value
    rtypes_module.rint = lambda value: value

    omero_module.rtypes = rtypes_module

    sys.modules["omero"] = omero_module
    sys.modules["omero.rtypes"] = rtypes_module


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")
    monkeypatch.setenv("OMERO_IMS_EXPORT_DIR", str(TEST_RUNTIME_ROOT / "export"))
    monkeypatch.setenv("OMERO_IMS_EXPORT_TIMEOUT", "10")
    monkeypatch.setenv("OMERO_IMS_EXPORT_POLL_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_TMP_PATH", str(TEST_RUNTIME_ROOT / "tmp"))
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_TIMEOUT", "1")
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_RETRY_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL", "10")


def _import_imaris_service(monkeypatch: pytest.MonkeyPatch):
    _set_required_env(monkeypatch)
    sys.modules.pop("omeroweb_imaris_connector.imaris_service", None)
    package = sys.modules.get("omeroweb_imaris_connector")
    if package is not None and hasattr(package, "imaris_service"):
        delattr(package, "imaris_service")
    imaris_service = importlib.import_module("omeroweb_imaris_connector.imaris_service")
    imaris_service._PROCESSOR_CONFIG_CACHE["value"] = None
    imaris_service._PROCESSOR_CONFIG_CACHE["checked_at"] = 0.0

    return imaris_service


def test_process_job_file_helpers_cover_cleanup_and_timeout_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(imaris_service, "PROCESS_JOB_DIR", str(tmp_path))
    monkeypatch.setattr(
        imaris_service.os,
        "makedirs",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("mkdir failed")),
    )
    imaris_service._ensure_process_job_dir()

    real_open = builtins.open
    tmp_file = tmp_path / "proc-1.json.tmp"
    real_replace = imaris_service.os.replace
    monkeypatch.setattr(imaris_service, "_ensure_process_job_dir", lambda: None)

    def _tracking_open(path, mode="r", encoding=None):
        return real_open(path, mode, encoding=encoding)

    monkeypatch.setattr(builtins, "open", _tracking_open)
    monkeypatch.setattr(
        imaris_service.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
    )
    monkeypatch.setattr(
        imaris_service.os.path, "exists", lambda path: str(path) == str(tmp_file)
    )
    monkeypatch.setattr(
        imaris_service.os,
        "remove",
        lambda path: (_ for _ in ()).throw(OSError("remove failed")),
    )

    imaris_service._write_process_job_file("proc-1", {"job_id": "proc-1"})
    assert tmp_file.exists()

    monkeypatch.setattr(imaris_service.os, "replace", real_replace)
    assert imaris_service._read_process_job_file("missing") is None

    written = {}
    forgotten = []
    monkeypatch.setattr(
        imaris_service,
        "_wait_for_process",
        lambda proc, timeout: (None, {"Export_Name": SimpleNamespace(val="demo.ims")}),
    )
    monkeypatch.setattr(imaris_service.time, "time", lambda: 123.0)
    monkeypatch.setattr(
        imaris_service,
        "_write_process_job_file",
        lambda job_id, payload: written.update({"job_id": job_id, "payload": payload}),
    )
    monkeypatch.setattr(
        imaris_service, "_forget_process_job", lambda job_id: forgotten.append(job_id)
    )

    imaris_service._monitor_process_job("proc-2", object())

    assert written["job_id"] == "proc-2"
    assert written["payload"]["state"] == "TIMEOUT"
    assert written["payload"]["outputs"] == {"Export_Name": "demo.ims"}
    assert written["payload"]["error"] == "Timed out waiting for IMS export job."
    assert forgotten == ["proc-2"]


def test_script_service_helpers_cover_discovery_selection_and_introspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    raw_service = object()
    conn = SimpleNamespace(
        getScriptService=lambda: (_ for _ in ()).throw(RuntimeError("primary failed")),
        c=SimpleNamespace(
            sf=SimpleNamespace(getScriptService=lambda: raw_service),
        ),
    )
    assert imaris_service._get_script_services(conn) == [raw_service]

    failing_service = SimpleNamespace(
        getScripts=lambda: (_ for _ in ()).throw(RuntimeError("script lookup failed"))
    )
    official_script = SimpleNamespace(
        name=None,
        path="/opt/official/omero/export/IMS_Export.py",
        id=SimpleNamespace(val="9"),
    )
    regular_script = SimpleNamespace(
        name="IMS_Export",
        path="/custom/path/IMS_Export.py",
        id=SimpleNamespace(val="8"),
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [
            failing_service,
            SimpleNamespace(getScripts=lambda: [regular_script, official_script]),
        ],
    )
    assert imaris_service._find_script_id(object()) == 9

    class _Service:
        @property
        def brokenScriptRunner(self):
            raise RuntimeError("broken attribute")

        def runScript(self):
            return "run-script"

        def executeCustomScript(self):
            return "execute-script"

        def begin_runScript(self):
            raise AssertionError("begin_ methods must be ignored")

        def canRunScript(self):
            raise AssertionError("canRun methods must be ignored")

        def __dir__(self):
            return [
                "runScript",
                "executeCustomScript",
                "begin_runScript",
                "canRunScript",
                "brokenScriptRunner",
            ]

    yielded = list(imaris_service._iter_script_methods(_Service()))
    assert [name for name, _ in yielded] == ["runScript", "executeCustomScript"]


def test_async_and_script_start_helpers_cover_getter_failures_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class _AsyncResult:
        def waitForCompleted(self):
            raise RuntimeError("wait failed")

        def getResponse(self):
            raise RuntimeError("response failed")

        def getResult(self):
            raise RuntimeError("result failed")

        def getResults(self):
            raise RuntimeError("results failed")

        def get(self):
            return {"job": 5}

    resolved = imaris_service._resolve_async_result(
        SimpleNamespace(
            end_runScript=lambda result: (_ for _ in ()).throw(
                RuntimeError("end failed")
            )
        ),
        "begin_runScript",
        _AsyncResult(),
    )
    assert resolved == {"job": 5}

    monkeypatch.setattr(
        imaris_service,
        "rint",
        lambda value: (_ for _ in ()).throw(RuntimeError("rint failed")),
    )

    with pytest.raises(ValueError, match="bad args"):
        imaris_service._call_script_method(
            lambda *args: (_ for _ in ()).throw(ValueError("bad args")),
            "runScript",
            7,
            {"Image_ID": 1},
            None,
        )

    with pytest.raises(ValueError, match="bad args"):
        imaris_service._call_script_method(
            lambda *args: (_ for _ in ()).throw(ValueError("bad args")),
            "runScript",
            7,
            {"Image_ID": 1},
            5,
        )

    monkeypatch.setattr(imaris_service, "rint", lambda value: value)
    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [])
    with pytest.raises(RuntimeError, match="ScriptService unavailable"):
        imaris_service._run_script(None, 1, 2, wait_secs=0)

    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [SimpleNamespace(runScript=lambda *args: None)],
    )
    with pytest.raises(RuntimeError, match="returned no process handle"):
        imaris_service._run_script(None, 1, 2, wait_secs=0)

    class _RetryService:
        def __init__(self):
            self.calls = 0

        def runScript(self, *args):
            self.calls += 1
            if self.calls == 1:
                raise NoProcessorAvailable("No processor available")
            return {"job_id": 12}

    retry_service = _RetryService()
    callback_events = []
    monkeypatch.setattr(
        imaris_service, "_get_script_services", lambda conn: [retry_service]
    )
    monkeypatch.setattr(
        imaris_service, "_get_script_processor_config", lambda conn: "bad"
    )
    monkeypatch.setattr(
        imaris_service, "_get_node_descriptors_config", lambda conn: None
    )
    monkeypatch.setattr(imaris_service, "SCRIPT_START_TIMEOUT", 1)
    monkeypatch.setattr(imaris_service, "SCRIPT_START_RETRY_INTERVAL", 0)
    monkeypatch.setattr(imaris_service.time, "time", lambda: 0.0)
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_args: None)

    def _status_callback(state, payload):
        callback_events.append((state, payload["attempt"]))
        raise RuntimeError("callback failed")

    result = imaris_service._run_script(
        object(),
        1,
        2,
        wait_secs=0,
        status_callback=_status_callback,
    )

    assert result == {"job_id": 12}
    assert callback_events == [("waiting_for_processor", 1)]


def test_config_and_job_state_helpers_cover_security_getjobs_and_cleanup_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    original_detach = imaris_service._detach_script_process

    class SecurityViolation(Exception):
        pass

    assert imaris_service._get_script_processor_config(None) is None
    assert imaris_service._get_node_descriptors_config(None) is None
    assert (
        imaris_service._can_read_script_config(
            SimpleNamespace(
                isAdmin=lambda: (_ for _ in ()).throw(RuntimeError("admin failed"))
            )
        )
        is False
    )

    protected_conn = SimpleNamespace(
        isAdmin=lambda: True,
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getConfigService=lambda: (_ for _ in ()).throw(
                    SecurityViolation("SecurityViolation")
                )
            )
        ),
    )
    assert imaris_service._get_script_processor_config(protected_conn) is None
    assert imaris_service._get_node_descriptors_config(protected_conn) is None

    noisy_conn = SimpleNamespace(
        isAdmin=lambda: True,
        c=SimpleNamespace(
            sf=SimpleNamespace(
                getConfigService=lambda: (_ for _ in ()).throw(
                    RuntimeError("config unavailable")
                )
            )
        ),
    )
    assert imaris_service._get_script_processor_config(noisy_conn) is None
    assert imaris_service._get_node_descriptors_config(noisy_conn) is None

    assert imaris_service._extract_job_id("bad-id") is None
    assert (
        imaris_service._extract_job_id(
            {"job_id": "bad", "id": SimpleNamespace(val="11")}
        )
        == 11
    )
    assert (
        imaris_service._extract_job_id(
            SimpleNamespace(
                getJobId=lambda: (_ for _ in ()).throw(RuntimeError("bad accessor")),
                value=SimpleNamespace(val="12"),
            )
        )
        == 12
    )

    broken_job = SimpleNamespace(id=SimpleNamespace(val=None), status=None)
    matched_job = SimpleNamespace(
        id=SimpleNamespace(val="14"),
        status=SimpleNamespace(val="finished"),
    )
    svc = SimpleNamespace(
        getJobStatus=lambda job_id: (_ for _ in ()).throw(
            RuntimeError("status failed")
        ),
        getJobOutputs=lambda job_id: (_ for _ in ()).throw(
            RuntimeError("outputs failed")
        ),
        getJobs=lambda: [broken_job, matched_job],
    )
    monkeypatch.setattr(imaris_service, "_get_script_services", lambda conn: [svc])
    assert imaris_service._get_job_state_and_outputs(object(), 14) == ("finished", None)

    time_values = iter((0.0, 0.0, 0.5))

    def _fake_time():
        try:
            return next(time_values)
        except StopIteration:
            return 1.0

    monkeypatch.setattr(imaris_service.time, "time", _fake_time)
    monkeypatch.setattr(imaris_service.time, "sleep", lambda *_args: None)
    detach_calls = []
    monkeypatch.setattr(
        imaris_service,
        "_detach_script_process",
        lambda proc, reason="": detach_calls.append(reason),
    )

    class _WaitingProcess:
        def __init__(self):
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls == 1:
                raise RuntimeError("poll failed")
            return "done"

        def getResults(self, *_args):
            raise RuntimeError("results failed")

    state, outputs = imaris_service._wait_for_process(_WaitingProcess(), timeout=1)
    assert state == "DONE"
    assert outputs is None
    assert detach_calls == ["process wait completed"]
    monkeypatch.setattr(imaris_service, "_detach_script_process", original_detach)

    class _BadValue:
        @property
        def val(self):
            raise RuntimeError("val failed")

        def getValue(self):
            raise RuntimeError("getValue failed")

        @property
        def name(self):
            raise RuntimeError("name failed")

        def __str__(self):
            raise TypeError("str failed")

    assert imaris_service._normalize_job_state("") is None
    assert imaris_service._normalize_job_state(_BadValue()) is None

    imaris_service._detach_script_process(None, reason="no-op")
    imaris_service._detach_script_process(SimpleNamespace(), reason="no-close")

    class _FailingDetach:
        def close(self, *args):
            raise RuntimeError("detach failed")

    imaris_service._detach_script_process(_FailingDetach(), reason="detach failure")

    close_calls = []

    class _FallbackClose:
        def close(self, *args):
            close_calls.append(args)
            if args:
                raise TypeError("flag unsupported")
            raise RuntimeError("close failed")

    imaris_service._detach_script_process(_FallbackClose(), reason="fallback close")
    assert close_calls == [(True,), ()]
    assert (
        imaris_service._infer_finished_from_outputs({"Export_Name": "demo.ims"}) is True
    )
    assert imaris_service._infer_finished_from_outputs(["not", "a", "dict"]) is False
