from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from omeroweb_imaris_connector import apps


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_imaris_connector_app_ready_configures_gateway_logging(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(apps, "configure_omero_gateway_logging", lambda: calls.append("configured"))

    apps.ImarisConnectorConfig("omeroweb_imaris_connector", apps).ready()

    assert calls == ["configured"]


def test_imaris_connector_urls_publish_expected_route_contract(monkeypatch) -> None:
    package_module = types.ModuleType("omeroweb_imaris_connector")
    package_module.__path__ = [str(REPO_ROOT / "omeroweb_imaris_connector")]
    views_module = types.ModuleType("omeroweb_imaris_connector.views")
    views_module.imaris_export = lambda *args, **kwargs: "imaris-export"
    monkeypatch.setitem(sys.modules, "omeroweb_imaris_connector", package_module)
    monkeypatch.setitem(sys.modules, "omeroweb_imaris_connector.views", views_module)

    spec = importlib.util.spec_from_file_location(
        "omeroweb_imaris_connector.urls",
        REPO_ROOT / "omeroweb_imaris_connector" / "urls.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "omeroweb_imaris_connector.urls", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    route_map = {pattern.name: str(pattern.pattern) for pattern in module.urlpatterns}

    assert module.app_name == "omeroweb_imaris_connector"
    assert route_map == {"imaris_export": "imaris-export/"}
