import os
import warnings
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "omeroweb.settings")
warnings.filterwarnings(
    "ignore",
    message=r"Deprecated\. utils\.__version__",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"distutils Version classes are deprecated\. Use packaging\.version instead\.",
    category=DeprecationWarning,
)
django.setup()

from omero_web_zarr import apps, integration, urls
from omero_web_zarr.templatetags import zarr_webclient


def test_zarr_module_contracts_cover_ready_routes_and_template_filter(monkeypatch):
    """Verify Zarr module contracts cover ready routes and template filter.

    Inputs: `monkeypatch`. Output: None.
    """
    installed = []
    monkeypatch.setattr(
        integration, "install_webgateway_overrides", lambda: installed.append(True)
    )
    monkeypatch.setattr(
        zarr_webclient,
        "_is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )

    config = apps.OmeroWebZarrAppConfig(apps.OmeroWebZarrAppConfig.name, apps)
    config.ready()

    assert installed == [True]
    route_names = [pattern.name for pattern in urls.urlpatterns]
    assert "omero_web_zarr_index" in route_names
    assert "zarr_image_chunk" in route_names
    assert "zarr_app" in route_names
    assert zarr_webclient.is_store_backed_image_filter(
        SimpleNamespace(store_backed=True)
    )
    assert zarr_webclient.is_store_backed_image_filter(None) is False
