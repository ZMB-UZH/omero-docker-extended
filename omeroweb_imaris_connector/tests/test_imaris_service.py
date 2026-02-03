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


def test_run_script_retries_until_processor_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_omero_stub()
    from omeroweb_imaris_connector import imaris_service

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
    from omeroweb_imaris_connector import imaris_service

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

    with pytest.raises(RuntimeError, match="No OMERO script processor is available"):
        imaris_service._run_script(None, script_id=1, image_id=2, wait_secs=0)
