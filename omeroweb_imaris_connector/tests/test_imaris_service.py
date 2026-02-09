from __future__ import annotations

import sys
import types

import pytest


class NoProcessorAvailable(Exception):
    """Stub for OMERO NoProcessorAvailable exceptions."""


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
    monkeypatch.setenv("OMERO_IMS_EXPORT_DIR", "/tmp")
    monkeypatch.setenv("OMERO_IMS_EXPORT_TIMEOUT", "10")
    monkeypatch.setenv("OMERO_IMS_EXPORT_POLL_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_IMS_PROCESS_JOB_DIR", "/tmp")
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_TIMEOUT", "1")
    monkeypatch.setenv("OMERO_IMS_SCRIPT_START_RETRY_INTERVAL", "0.1")
    monkeypatch.setenv("OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL", "10")


def _import_imaris_service(monkeypatch: pytest.MonkeyPatch):
    _set_required_env(monkeypatch)
    sys.modules.pop("omeroweb_imaris_connector.imaris_service", None)
    from omeroweb_imaris_connector import imaris_service

    return imaris_service


def test_run_script_retries_until_processor_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        def __init__(self) -> None:
            self.calls = 0

        def runScript(self, *args, **kwargs):
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
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        def runScript(self, *args, **kwargs):
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

    with pytest.raises(RuntimeError, match="No script processor slot available"):
        imaris_service._run_script(None, script_id=1, image_id=2, wait_secs=0)


def test_run_script_fails_fast_when_processors_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        def __init__(self) -> None:
            self.calls = 0

        def runScript(self, *args, **kwargs):
            self.calls += 1
            raise NoProcessorAvailable("No processor available")

    class DummyConfigService:
        def getConfigValue(self, key):
            assert key == "omero.scripts.processors"
            return "0"

    class DummyServiceFactory:
        def getConfigService(self):
            return DummyConfigService()

    class DummyConn:
        def __init__(self) -> None:
            self.c = types.SimpleNamespace(sf=DummyServiceFactory())

        def isAdmin(self) -> bool:
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
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyService:
        def __init__(self) -> None:
            self.calls = 0

        def runScript(self, *args, **kwargs):
            self.calls += 1
            raise NoProcessorAvailable("No processor available")

    class DummyConfigService:
        def getConfigValue(self, key):
            if key == "omero.scripts.processors":
                return "2"
            if key == "omero.server.nodedescriptors":
                return "master:Blitz-0,Tables-0"
            raise AssertionError(f"Unexpected config key: {key}")

    class DummyServiceFactory:
        def getConfigService(self):
            return DummyConfigService()

    class DummyConn:
        def __init__(self) -> None:
            self.c = types.SimpleNamespace(sf=DummyServiceFactory())

        def isAdmin(self) -> bool:
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
    _install_omero_stub()
    imaris_service = _import_imaris_service(monkeypatch)

    class DummyProcess:
        def __init__(self) -> None:
            self.closed = False
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            return "FINISHED"

        def getResults(self, *_args):
            return {"Export_Path": "/tmp/export.ims"}

        def close(self, *_args):
            self.closed = True

    proc = DummyProcess()
    monkeypatch.setattr(imaris_service, "EXPORT_POLL_INTERVAL", 0)

    state, outputs = imaris_service._wait_for_process(proc, timeout=1)

    assert state == "FINISHED"
    assert outputs == {"Export_Path": "/tmp/export.ims"}
    assert proc.closed is True
