import os
import warnings
from datetime import datetime

import django
import numpy as np
from django.test import RequestFactory

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

from omero_web_zarr import integration


class _FakeChannel:
    def __init__(self):
        self._label = "base"

    class _Color:
        def getHtml(self):
            return "FFFFFF"

    def getLabel(self):
        return self._label

    def getColor(self):
        return self._Color()

    def getEmissionWave(self):
        return None

    def getFamily(self):
        return None

    def getCoefficient(self):
        return None

    def getLut(self):
        return None

    def getWindowStart(self):
        return None

    def getWindowEnd(self):
        return None

    def getWindowMin(self):
        return 1.0

    def getWindowMax(self):
        return 9.0

    def isActive(self):
        return False

    def isInverted(self):
        return None


class _FakeImageDataImage:
    description = ""
    archived = False

    def __init__(self):
        self.id = 7
        self.name = "demo.zarr"
        self._channel_calls = []

    def getName(self):
        return self.name

    def getChannels(self, noRE=False):
        self._channel_calls.append(noRE)
        return [_FakeChannel()]

    def getProject(self):
        return None

    def listParents(self):
        return []

    def getAuthor(self):
        return "Test User"

    def getDate(self):
        return datetime(2026, 3, 23, 12, 0, 0)

    def getPixelsType(self):
        return "uint16"

    def canAnnotate(self):
        return False

    def canEdit(self):
        return True

    def canDelete(self):
        return True

    def canLink(self):
        return False

    def getSizeX(self):
        return 1024

    def getSizeY(self):
        return 512

    def getSizeZ(self):
        return 4

    def getSizeT(self):
        return 1

    def getSizeC(self):
        return 1

    def splitChannelDims(self):
        return {"g": {"width": 1026, "height": 514}}

    def getProjection(self):
        return "normal"

    def getPixelSizeX(self, units=None):
        return None

    def getPixelSizeY(self, units=None):
        return None

    def getPixelSizeZ(self, units=None):
        return None

    def getObjectiveSettings(self):
        return None


class _FakeConfigService:
    def getConfigValue(self, key):
        assert key == "omero.pixeldata.max_tile_length"
        return "1024"


class _FakeConnForTileSize:
    def getConfigService(self):
        return _FakeConfigService()


class _FakeResolution:
    def __init__(self, size_x, size_y):
        self.sizeX = size_x
        self.sizeY = size_y


class _FailingResolutionEngine:
    def getResolutionLevels(self):
        return 2

    def getTileSize(self):
        raise RuntimeError("ZarrReader.getOptimalTileWidth failed during getTileSize")

    def getResolutionDescriptions(self):
        return [_FakeResolution(1024, 512), _FakeResolution(512, 256)]

    def getDefaultZ(self):
        return 0

    def getDefaultT(self):
        return 0


class _FakeRegularTileFailureImage(_FakeImageDataImage):
    def __init__(self):
        super().__init__()
        self._re = _FailingResolutionEngine()
        self._conn = _FakeConnForTileSize()

    def _prepareRenderingEngine(self):
        return True

    def getPixelRange(self):
        return (0, 65535)

    def isGreyscaleRenderingModel(self):
        return False

    def isInvertedAxis(self):
        return False


class _PreparedRegionImage:
    def __init__(self):
        self._re = _FailingResolutionEngine()
        self.calls = []

    def _prepareRenderingEngine(self):
        return True

    def getSizeX(self):
        return 1024

    def getSizeY(self):
        return 512

    def renderJpegRegion(self, z, t, x, y, width, height, level=None, compression=None):
        self.calls.append(
            {
                "z": z,
                "t": t,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "level": level,
                "compression": compression,
            }
        )
        return b"jpeg"


def test_decorate_store_backed_channels_applies_metadata(monkeypatch):
    monkeypatch.setattr(
        integration,
        "get_store_backed_channel_overrides",
        lambda image, channels=None: [
            {
                "label": "DNA",
                "active": True,
                "color": (255, 0, 0),
                "window": (5.0, 15.0),
                "inverted": False,
            }
        ],
    )

    wrapped = integration._decorate_store_backed_channels(object(), [_FakeChannel()])

    assert len(wrapped) == 1
    assert wrapped[0].getLabel() == "DNA"
    assert wrapped[0].getColor().getHtml() == "FF0000"
    assert wrapped[0].getWindowStart() == 5.0
    assert wrapped[0].getWindowEnd() == 15.0
    assert wrapped[0].getWindowMin() == 1.0
    assert wrapped[0].getWindowMax() == 9.0
    assert wrapped[0].isActive() is True
    assert wrapped[0].isInverted() is False


def test_install_webgateway_overrides_routes_store_backed_channels_off_re(monkeypatch):
    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    calls = []
    def _fake_get_channels(self, *args, **kwargs):
        calls.append((args, kwargs))
        return [_FakeChannel()]

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        integration,
        "_decorate_store_backed_channels",
        lambda image, channels: ["wrapped", image.store_backed, len(channels)],
    )
    monkeypatch.setattr(webclient_gateway.ImageWrapper, "getChannels", _fake_get_channels)
    monkeypatch.setattr(webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None)
    monkeypatch.setattr(webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False)

    integration.install_webgateway_overrides()

    store_backed_image = type("StoreBackedImage", (), {"store_backed": True})()
    regular_image = type("RegularImage", (), {"store_backed": False})()

    assert webclient_gateway.ImageWrapper.getChannels(store_backed_image) == ["wrapped", True, 1]
    assert calls[0] == ((), {"noRE": True})

    assert isinstance(webclient_gateway.ImageWrapper.getChannels(regular_image), list)
    assert calls[1] == ((), {})


def test_store_backed_image_data_uses_store_metadata_without_re(monkeypatch):
    request = RequestFactory().get("/webclient/imgData/7/")
    request.session = {
        "server_settings": {
            "viewer": {
                "initial_zoom_level": 0,
                "interpolate_pixels": True,
            }
        }
    }
    image = _FakeImageDataImage()
    node = type(
        "FakeNode",
        (),
        {
            "data": [
                type(
                    "FakeArray",
                    (),
                    {
                        "shape": (1, 1, 512, 1024),
                        "dtype": np.dtype(np.uint16),
                        "chunks": ((1,), (1,), (128, 128, 128, 128), (256, 256, 256, 256)),
                    },
                )(),
                type(
                    "FakeArray",
                    (),
                    {
                        "shape": (1, 1, 256, 512),
                        "dtype": np.dtype(np.uint16),
                        "chunks": ((1,), (1,), (128, 128), (256, 256)),
                    },
                )(),
            ],
            "metadata": {
                "axes": ["t", "c", "y", "x"],
                "contrast_limits": [[5, 50]],
            },
        },
    )()

    monkeypatch.setattr(integration, "load_store_backed_image_node", lambda image: node)
    monkeypatch.setattr(
        integration,
        "get_store_backed_channel_overrides",
        lambda image, channels=None: [{}],
    )

    payload = integration._store_backed_image_data(image, request)

    assert image._channel_calls == [True]
    assert payload["tiles"] is True
    assert payload["tile_size"] == {"width": 256, "height": 128}
    assert payload["levels"] == 2
    assert payload["zoomLevelScaling"] == {0: 1.0, 1: 0.5}
    assert payload["pixel_range"] == (5.0, 50.0)
    assert payload["rdefs"]["defaultZ"] == 0


def test_store_backed_region_response_maps_viewer_tile_level(monkeypatch):
    image = object()
    request = RequestFactory().get(
        "/webclient/render_image_region/7/0/0/",
        {"tile": "0,1,2,64,32"},
    )
    node = type(
        "FakeNode",
        (),
        {
            "data": [
                type(
                    "FakeArray",
                    (),
                    {
                        "shape": (1, 1, 512, 1024),
                        "chunks": ((1,), (1,), (128, 128, 128, 128), (256, 256, 256, 256)),
                    },
                )(),
                type(
                    "FakeArray",
                    (),
                    {
                        "shape": (1, 1, 256, 512),
                        "chunks": ((1,), (1,), (128, 128), (256, 256)),
                    },
                )(),
            ],
            "metadata": {"axes": ["t", "c", "y", "x"]},
        },
    )()
    captured = {}

    monkeypatch.setattr(integration, "load_store_backed_image_node", lambda image: node)

    def fake_region(*args, **kwargs):
        captured.update(kwargs)
        from PIL import Image

        return Image.fromarray(np.full((32, 64), 127, dtype=np.uint8), mode="L")

    monkeypatch.setattr(integration, "render_store_backed_region_pil_image", fake_region)

    response = integration._store_backed_region_response(image, request, z=3, t=0, conn=None)

    assert response.status_code == 200
    assert captured == {
        "x": 64,
        "y": 64,
        "width": 64,
        "height": 32,
        "z": 3,
        "t": 0,
        "level": 1,
    }


def test_marshal_regular_image_data_with_safe_tile_size_uses_generic_fallback():
    request = RequestFactory().get("/webclient/imgData/7/")
    request.session = {
        "server_settings": {
            "viewer": {
                "initial_zoom_level": 0,
                "interpolate_pixels": True,
            }
        }
    }
    image = _FakeRegularTileFailureImage()

    payload = integration._marshal_regular_image_data_with_safe_tile_size(image, request)

    assert payload["tiles"] is True
    assert payload["tile_size"] == {"width": 1024, "height": 512}
    assert payload["levels"] == 2
    assert payload["resolutions"] == {
        0: {"sizeX": 1024, "sizeY": 512},
        1: {"sizeX": 512, "sizeY": 256},
    }
    assert payload["zoomLevelScaling"] == {0: 1.0, 1: 0.5}


def test_safe_regular_image_marshal_uses_generic_fallback_and_key_selection():
    request = RequestFactory().get("/webclient/imgData/7/")
    request.session = {
        "server_settings": {
            "viewer": {
                "initial_zoom_level": 0,
                "interpolate_pixels": True,
            }
        }
    }
    image = _FakeRegularTileFailureImage()

    def failing_image_marshal(image, key=None, request=None):
        raise RuntimeError("ZarrReader.getOptimalTileWidth failed during getTileSize")

    payload = integration._safe_regular_image_marshal(
        failing_image_marshal,
        image,
        request=request,
    )
    selected = integration._safe_regular_image_marshal(
        failing_image_marshal,
        image,
        key="tile_size.width",
        request=request,
    )

    assert payload["tile_size"] == {"width": 1024, "height": 512}
    assert selected == 1024


def test_install_safe_image_marshal_overrides_rebinds_loaded_view_modules(monkeypatch):
    from omero_figure import views as figure_views
    from omero_iviewer import views as iviewer_views
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import views as webgateway_views

    def original_image_marshal(image, key=None, request=None):
        return {"id": getattr(image, "id", None)}

    monkeypatch.setattr(webgateway_marshal, "imageMarshal", original_image_marshal)
    monkeypatch.setattr(webgateway_views, "imageMarshal", original_image_marshal)
    monkeypatch.setattr(iviewer_views, "imageMarshal", original_image_marshal)
    monkeypatch.setattr(figure_views, "imageMarshal", original_image_marshal)
    monkeypatch.setattr(
        webgateway_marshal,
        "_omero_web_zarr_safe_image_marshal_installed",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        webgateway_marshal,
        "_omero_web_zarr_original_image_marshal",
        None,
        raising=False,
    )

    safe_image_marshal = integration._install_safe_image_marshal_overrides(webgateway_marshal)

    assert webgateway_marshal.imageMarshal is safe_image_marshal
    assert webgateway_views.imageMarshal is safe_image_marshal
    assert iviewer_views.imageMarshal is safe_image_marshal
    assert figure_views.imageMarshal is safe_image_marshal


def test_render_regular_image_region_with_safe_tile_size_uses_generic_fallback(monkeypatch):
    request = RequestFactory().get(
        "/webclient/render_image_region/7/0/0/",
        {"tile": "0,1,2"},
    )
    request.session = {"connector": {"server_id": 1}}
    image = _PreparedRegionImage()

    from omeroweb.webgateway import views as webgateway_views

    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda request, iid, server_id=None, conn=None: (image, 0.85),
    )

    response = integration._render_regular_image_region_with_safe_tile_size(
        request,
        7,
        3,
        0,
        conn=_FakeConnForTileSize(),
    )

    assert response.status_code == 200
    assert image.calls == [
        {
            "z": 3,
            "t": 0,
            "x": 1024,
            "y": 1024,
            "width": 1024,
            "height": 512,
            "level": 1,
            "compression": 0.85,
        }
    ]
