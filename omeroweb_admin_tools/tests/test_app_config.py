from __future__ import annotations

from omeroweb_admin_tools import apps


def test_admin_tools_app_ready_configures_gateway_logging(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(apps, "configure_omero_gateway_logging", lambda: calls.append("configured"))

    apps.AdminToolsPluginConfig("omeroweb_admin_tools", apps).ready()

    assert calls == ["configured"]
