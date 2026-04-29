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
    """Handle install OMERO stub."""
    omero_module = types.ModuleType("omero")
    omero_module.NoProcessorAvailable = NoProcessorAvailable

    rtypes_module = types.ModuleType("omero.rtypes")
    rtypes_module.rlong = lambda value: value
    rtypes_module.rint = lambda value: value

    omero_module.rtypes = rtypes_module

    sys.modules["omero"] = omero_module
    sys.modules["omero.rtypes"] = rtypes_module


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handle set required env."""
    monkeypatch.setenv("OMERO_IMS_SCRIPT_NAME", "IMS_Export.py")
    monkeypatch.setenv("OMERO_IMS_EXPORT_DIR", str(TEST_RUNTIME_ROOT / "export"))
    monkeypatch.setenv("OMERO_IMS_EXPORT_TIMEOUT", "10")
    monkeypatch.setenv("OMERO_IMS_EXPORT_POLL_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_TMP_PATH", str(TEST_RUNTIME_ROOT / "tmp"))
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_TIMEOUT", "1")
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_RETRY_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL", "10")


def _import_imaris_service(monkeypatch: pytest.MonkeyPatch):
    """Handle import imaris service."""
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
    """Verify test process job file helpers cover cleanup a behavior."""
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
        """Handle tracking open."""
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
        imaris_service,
        "_forget_process_job",
        forgotten.append,
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
    """Verify test script service helpers cover discovery s behavior."""
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
        """Represent service."""

        @property
        def brokenScriptRunner(self):
            raise RuntimeError("broken attribute")

        @staticmethod
        def runScript():
            """Run run script."""
            return "run-script"

        @staticmethod
        def executeCustomScript():
            """Run execute custom script."""
            return "execute-script"

        @staticmethod
        def begin_runScript():
            """Handle begin run script."""
            raise AssertionError("begin_ methods must be ignored")

        @staticmethod
        def canRunScript():
            """Handle can run script."""
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
    """Verify test async and script start helpers cover get behavior."""
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class _AsyncResult:
        """Represent async result."""

        @staticmethod
        def waitForCompleted():
            """Handle wait for completed."""
            raise RuntimeError("wait failed")

        @staticmethod
        def getResponse():
            """Return get response."""
            raise RuntimeError("response failed")

        @staticmethod
        def getResult():
            """Return get result."""
            raise RuntimeError("result failed")

        @staticmethod
        def getResults():
            """Return get results."""
            raise RuntimeError("results failed")

        @staticmethod
        def get():
            """Return get."""
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
        """Represent retry service."""

        def __init__(self):
            self.calls = 0

        def runScript(self, *args):
            """Run run script."""
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
        """Handle status callback."""
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
    """Verify test config and job state helpers cover secur behavior."""
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    original_detach = imaris_service._detach_script_process

    class SecurityViolation(Exception):
        """Represent security violation."""

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
        """Handle fake time."""
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
        """Represent waiting process."""

        def __init__(self):
            self.poll_calls = 0

        def poll(self):
            """Handle poll."""
            self.poll_calls += 1
            if self.poll_calls == 1:
                raise RuntimeError("poll failed")
            return "done"

        @staticmethod
        def getResults(*_args):
            """Return get results."""
            raise RuntimeError("results failed")

    state, outputs = imaris_service._wait_for_process(_WaitingProcess(), timeout=1)
    assert state == "DONE"
    assert outputs is None
    assert detach_calls == ["process wait completed"]
    monkeypatch.setattr(imaris_service, "_detach_script_process", original_detach)

    class _BadValue:
        """Represent bad value."""

        @property
        def val(self):
            raise RuntimeError("val failed")

        @staticmethod
        def getValue():
            """Return get value."""
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
        """Represent failing detach."""

        @staticmethod
        def close(*args):
            """Handle close."""
            raise RuntimeError("detach failed")

    imaris_service._detach_script_process(_FailingDetach(), reason="detach failure")

    close_calls = []

    class _FallbackClose:
        """Represent fallback close."""

        @staticmethod
        def close(*args):
            """Handle close."""
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


def test_imaris_service_additional_helper_edges_cover_remaining_type_and_config_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test imaris service additional helper edges c behavior."""
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class _BadValue:
        """Represent bad value."""

        @staticmethod
        def getValue():
            """Return get value."""
            raise RuntimeError("getter exploded")

        def __str__(self):
            return "fallback"

    bad_value = _BadValue()
    assert imaris_service._unwrap_rtype(bad_value) is bad_value

    bad_script = SimpleNamespace(
        name="IMS_Export.py",
        path="scripts/IMS_Export.py",
        id=SimpleNamespace(val=None),
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [SimpleNamespace(getScripts=lambda: [bad_script])],
    )
    assert imaris_service._find_script_id(object()) is None
    assert imaris_service._is_process_handle(
        SimpleNamespace(poll=lambda: None, getResults=lambda *_args: {})
    )
    assert imaris_service._is_async_result(None) is False

    class _BrokenService:
        """Represent broken service."""

        @property
        def runScript(self):
            raise RuntimeError("broken preferred method")

        @staticmethod
        def executeScript():
            """Run execute script."""
            return "ok"

        def __dir__(self):
            return ["executeScript", "brokenExecScript"]

        @property
        def brokenExecScript(self):
            raise RuntimeError("broken discovered method")

    yielded = list(imaris_service._iter_script_methods(_BrokenService()))
    assert [name for name, _ in yielded] == ["executeScript"]

    noisy_config_conn = SimpleNamespace(
        c=SimpleNamespace(sf=SimpleNamespace(getConfigService=lambda: None))
    )
    assert imaris_service._get_script_processor_config(noisy_config_conn) is None
    assert imaris_service._can_read_script_config(None) is False
    assert (
        imaris_service._can_read_script_config(
            SimpleNamespace(
                isAdmin=lambda: (_ for _ in ()).throw(RuntimeError("admin exploded"))
            )
        )
        is False
    )
    assert imaris_service._get_node_descriptors_config(noisy_config_conn) is None
    assert (
        imaris_service._get_node_descriptors_config(
            SimpleNamespace(
                isAdmin=lambda: True,
                c=SimpleNamespace(
                    sf=SimpleNamespace(
                        getConfigService=lambda: types.SimpleNamespace(
                            getConfigValue=lambda _key: None
                        )
                    )
                ),
            )
        )
        is None
    )
    assert (
        imaris_service._get_node_descriptors_config(
            SimpleNamespace(
                isAdmin=lambda: True,
                c=SimpleNamespace(
                    sf=SimpleNamespace(
                        getConfigService=lambda: types.SimpleNamespace(
                            getConfigValue=lambda _key: "   "
                        )
                    )
                ),
            )
        )
        is None
    )
    assert imaris_service._format_script_exception(RuntimeError("plain failure")) == (
        "plain failure"
    )
    assert imaris_service._is_security_violation(
        RuntimeError("wrapped SecurityViolation response")
    )
    monkeypatch.setattr(
        imaris_service.omero,
        "NoProcessorAvailable",
        (NoProcessorAvailable,),
    )
    assert imaris_service._is_no_processor_available(
        RuntimeError("No processor available")
    )


def test_no_processor_detector_ignores_non_exception_tuple_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test no processor detector ignores non except behavior."""
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)
    monkeypatch.setattr(
        imaris_service.omero,
        "NoProcessorAvailable",
        (object, NoProcessorAvailable),
    )

    assert (
        imaris_service._is_no_processor_available(RuntimeError("plain failure"))
        is False
    )
    assert (
        imaris_service._is_no_processor_available(
            NoProcessorAvailable("processor busy")
        )
        is True
    )


def test_imaris_service_remaining_job_state_and_output_paths_are_exercised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test imaris service remaining job state and o behavior."""
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    original_import = builtins.__import__

    def _failing_rlong_import(
        name, global_vars=None, local_vars=None, fromlist=(), level=0
    ):
        """Handle failing rlong import."""
        if name == "omero.rtypes" and tuple(fromlist or ()) == ("rlong",):
            raise ImportError("rlong missing")
        return original_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_rlong_import)
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [SimpleNamespace(runScript=lambda *args: {"args": args})],
    )
    result = imaris_service._run_script(object(), 7, 9, wait_secs=0)
    monkeypatch.setattr(builtins, "__import__", original_import)
    assert result["args"][1] == {"Image_ID": 9}

    get_jobs_fail_service = SimpleNamespace(
        getJobs=lambda: (_ for _ in ()).throw(RuntimeError("jobs exploded"))
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [get_jobs_fail_service],
    )
    assert imaris_service._get_job_state_and_outputs(object(), 12) == (None, None)

    class _NonNumericJobId:
        """Represent non numeric job identifier."""

        pass

    assert imaris_service._extract_job_id({"job_id": _NonNumericJobId()}) is None
    assert imaris_service._extract_output_value(None, "Export_Name") is None
    assert imaris_service._infer_finished_from_outputs({"Other": "value"}) is False


def test_imaris_service_covers_remaining_descriptor_and_job_iteration_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify test imaris service covers remaining descript behavior."""
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class _BrokenId:
        """Represent broken identifier."""

        def __init__(self):
            self._reads = 0

        @property
        def val(self):
            self._reads += 1
            if self._reads < 3:
                return None
            raise RuntimeError("bad id")

    broken_id_script = SimpleNamespace(
        name="IMS_Export.py",
        path="scripts/IMS_Export.py",
        id=_BrokenId(),
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [SimpleNamespace(getScripts=lambda: [broken_id_script])],
    )
    assert imaris_service._find_script_id(object()) is None

    weird_service = SimpleNamespace(
        runScript=lambda *_args: None,
        helperScript=lambda *_args: None,
    )
    assert list(imaris_service._iter_script_methods(weird_service)) == [
        ("runScript", weird_service.runScript)
    ]

    class _TypeOnlyMethod:
        """Represent type only method."""

        def __call__(self, *args):
            raise TypeError("bad signature")

    with pytest.raises(TypeError, match="bad signature"):
        imaris_service._call_script_method(_TypeOnlyMethod(), "runScript", 1, {}, 0)

    assert (
        imaris_service._get_script_processor_config(
            SimpleNamespace(
                isAdmin=lambda: True,
                c=SimpleNamespace(
                    sf=SimpleNamespace(
                        getConfigService=lambda: SimpleNamespace(
                            getConfigValue=lambda _key: None
                        )
                    )
                ),
            )
        )
        is None
    )
    assert (
        imaris_service._is_no_processor_available(
            RuntimeError("backend said NoProcessorAvailable")
        )
        is True
    )

    class _NonNumericValue:
        """Represent non numeric value."""

        pass

    class _BadJobId:
        """Represent bad job identifier."""

        @staticmethod
        def getValue():
            """Return get value."""
            return _NonNumericValue()

    assert imaris_service._extract_job_id(_BadJobId()) is None

    class _BadAccessorJob:
        """Represent bad accessor job."""

        job_id = 19

        @staticmethod
        def getJobId():
            """Return get job identifier."""
            return _NonNumericValue()

    assert imaris_service._extract_job_id(_BadAccessorJob()) == 19

    running_job = SimpleNamespace(
        id=SimpleNamespace(val=7),
        status=SimpleNamespace(val="RUNNING"),
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [
            SimpleNamespace(
                getJobs=lambda: [running_job],
                getJobOutputs=lambda _job_id: {},
            )
        ],
    )
    assert imaris_service._get_job_state_and_outputs(object(), 7) == ("RUNNING", {})

    class _BrokenStatus:
        """Represent broken status."""

        @property
        def val(self):
            raise RuntimeError("bad status")

    broken_status_job = SimpleNamespace(
        id=SimpleNamespace(val=8),
        status=_BrokenStatus(),
    )
    monkeypatch.setattr(
        imaris_service,
        "_get_script_services",
        lambda conn: [SimpleNamespace(getJobs=lambda: [broken_status_job])],
    )
    assert imaris_service._get_job_state_and_outputs(object(), 8) == (None, None)
