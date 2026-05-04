from omeroweb_imaris_connector import apps, urls


def test_imaris_module_contracts_cover_ready_hook_and_route(monkeypatch):
    """Verify imaris module contracts cover ready hook and route.

    Inputs: `monkeypatch`. Output: None.
    """
    configured = []
    monkeypatch.setattr(
        apps, "configure_omero_gateway_logging", lambda: configured.append(True)
    )

    config = apps.ImarisConnectorConfig(apps.ImarisConnectorConfig.name, apps)
    config.ready()

    assert configured == [True]
    route_names = [pattern.name for pattern in urls.urlpatterns]
    assert route_names == ["imaris_export"]
