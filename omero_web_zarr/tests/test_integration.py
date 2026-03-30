import os
import warnings
from datetime import datetime

import django
import numpy as np
import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import include, path

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
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
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
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", _fake_get_channels
    )
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_marshal, "imageMarshal", lambda image, key=None, request=None: {}
    )
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
    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )

    integration.install_webgateway_overrides()

    store_backed_image = type("StoreBackedImage", (), {"store_backed": True})()
    regular_image = type("RegularImage", (), {"store_backed": False})()

    assert webclient_gateway.ImageWrapper.getChannels(store_backed_image) == [
        "wrapped",
        True,
        1,
    ]
    assert calls[0] == ((), {"noRE": True})

    assert isinstance(webclient_gateway.ImageWrapper.getChannels(regular_image), list)
    assert calls[1] == ((), {})


def test_install_webgateway_overrides_preserves_regular_image_data_json(monkeypatch):
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    request = RequestFactory().get("/webclient/imgData/7/")
    request.session = {}
    regular_image = type("RegularImage", (), {"store_backed": False})()
    original_calls = []

    class _FakeConn:
        def getObject(self, object_type, iid):
            assert object_type == "Image"
            assert iid == 7
            return regular_image

    def original_image_data_json(request, conn=None, _internal=False, **kwargs):
        original_calls.append((conn, _internal, kwargs))
        return {"source": "original", "iid": kwargs["iid"]}

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", original_image_data_json)
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webgateway_views, "render_image_region", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_marshal, "imageMarshal", lambda image, key=None, request=None: {}
    )
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
    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )
    monkeypatch.setattr(
        integration,
        "_store_backed_image_data",
        lambda image, request: (_ for _ in ()).throw(
            AssertionError("unexpected store-backed path")
        ),
    )

    integration.install_webgateway_overrides()

    response = webgateway_views.imageData_json(request, conn=_FakeConn(), iid=7)

    assert response == {"source": "original", "iid": 7}
    assert len(original_calls) == 1


def test_install_webgateway_overrides_preserves_regular_render_image_region(
    monkeypatch,
):
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    request = RequestFactory().get(
        "/webclient/render_image_region/7/0/0/", {"tile": "0,0,0"}
    )
    request.session = {}
    regular_image = type("RegularImage", (), {"store_backed": False})()
    sentinel = HttpResponse(b"original-region", content_type="image/jpeg")
    original_calls = []

    class _FakeConn:
        def getObject(self, object_type, iid):
            assert object_type == "Image"
            assert iid == 7
            return regular_image

    def original_render_image_region(request, iid, z, t, conn=None, **kwargs):
        original_calls.append((iid, z, t, conn, kwargs))
        return sentinel

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webgateway_views, "render_image_region", original_render_image_region
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_marshal, "imageMarshal", lambda image, key=None, request=None: {}
    )
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
    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )
    monkeypatch.setattr(
        integration,
        "_store_backed_region_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected store-backed path")
        ),
    )

    integration.install_webgateway_overrides()

    response = webgateway_views.render_image_region(request, 7, 0, 0, conn=_FakeConn())

    assert response is sentinel
    assert len(original_calls) == 1


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
                        "chunks": (
                            (1,),
                            (1,),
                            (128, 128, 128, 128),
                            (256, 256, 256, 256),
                        ),
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
                        "chunks": (
                            (1,),
                            (1,),
                            (128, 128, 128, 128),
                            (256, 256, 256, 256),
                        ),
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

    monkeypatch.setattr(
        integration, "render_store_backed_region_pil_image", fake_region
    )

    response = integration._store_backed_region_response(
        image, request, z=3, t=0, conn=None
    )

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


class _FakeMetadataPreviewImage:
    id = 1061

    def getAllRenderingDefs(self):
        raise RuntimeError(
            "Error instantiating pixel buffer: managed/path\n"
            "at com.glencoesoftware.omero.zarr.ZarrPixelsService.getPixelBuffer"
        )

    def getRenderingDefId(self):
        raise AssertionError("rendering definition lookup should not run after failure")

    def getSizeX(self):
        return 4096

    def getSizeY(self):
        return 2048


class _FakeMetadataPreviewContainer:
    def __init__(self, conn, **kwargs):
        self.conn = conn
        self.kwargs = kwargs
        self.image = _FakeMetadataPreviewImage()


class _FakeMetadataPreviewConn:
    def getMaxPlaneSize(self):
        return (1024, 1024)


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

    payload = integration._marshal_regular_image_data_with_safe_tile_size(
        image, request
    )

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

    safe_image_marshal = integration._install_safe_image_marshal_overrides(
        webgateway_marshal
    )

    assert webgateway_marshal.imageMarshal is safe_image_marshal
    assert webgateway_views.imageMarshal is safe_image_marshal
    assert iviewer_views.imageMarshal is safe_image_marshal
    assert figure_views.imageMarshal is safe_image_marshal


def test_render_regular_image_region_with_safe_tile_size_uses_generic_fallback(
    monkeypatch,
):
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


def test_load_metadata_preview_with_safe_rendering_returns_empty_rdefs(monkeypatch):
    request = RequestFactory().get("/webclient/metadata_preview/image/1061/")
    request.session = {}

    from omeroweb.webclient import views as webclient_views

    def _build_metadata_preview_container(conn, **kwargs):
        return _FakeMetadataPreviewContainer(conn, **kwargs)

    monkeypatch.setattr(
        webclient_views,
        "BaseContainer",
        _build_metadata_preview_container,
    )
    monkeypatch.setattr(webclient_views, "BaseShare", lambda conn, share_id: object())
    monkeypatch.setattr(
        webclient_views,
        "getIntOrDefault",
        lambda request, key, default: default,
    )

    context = integration._load_metadata_preview_with_safe_rendering(
        request,
        "image",
        "1061",
        conn=_FakeMetadataPreviewConn(),
    )

    assert context["template"] == "webclient/annotations/metadata_preview.html"
    assert context["rdefs"] == []
    assert context["rdefsJson"] == "[]"
    assert context["tiledImage"] is True
    assert isinstance(context["manager"], _FakeMetadataPreviewContainer)


def test_install_webgateway_overrides_skips_safe_marshal_when_disabled(monkeypatch):
    """When OMERO_WEB_ZARR_ALTERNATIVE_RENDERING=false, the safe image
    marshal override is NOT installed — OMERO's built-in imageMarshal
    stays unpatched."""
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "false")

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    def original_image_marshal(image, key=None, request=None):
        return {"id": 999}

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webgateway_views, "render_image_region", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(webgateway_marshal, "imageMarshal", original_image_marshal)
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
    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )

    integration.install_webgateway_overrides()

    # imageMarshal must remain the original — NOT wrapped by safe marshal
    assert webgateway_marshal.imageMarshal is original_image_marshal
    assert not getattr(
        webgateway_marshal, "_omero_web_zarr_safe_image_marshal_installed", False
    )


def test_install_webgateway_overrides_propagates_tile_failure_when_safe_rendering_disabled(
    monkeypatch,
):
    """When safe rendering is disabled, tile-size failures in regular images
    must propagate as-is — OMERO's built-in error handling applies."""
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "false")

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    regular_image = type("RegularImage", (), {"store_backed": False})()

    class _FakeConn:
        def getObject(self, object_type, iid):
            return regular_image

    def failing_image_data_json(request, conn=None, _internal=False, **kwargs):
        raise RuntimeError("ZarrReader.getOptimalTileWidth failed during getTileSize")

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", failing_image_data_json)
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webgateway_views, "render_image_region", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_marshal, "imageMarshal", lambda image, key=None, request=None: {}
    )
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
    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )

    integration.install_webgateway_overrides()

    import pytest

    request = RequestFactory().get("/webclient/imgData/7/")
    request.session = {}

    with pytest.raises(RuntimeError, match="ZarrReader"):
        webgateway_views.imageData_json(request, conn=_FakeConn(), iid=7)


def test_install_webgateway_overrides_falls_back_for_metadata_preview_rendering_failure(
    monkeypatch,
):
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")

    def _identity_decorator():
        return lambda func: func

    request = RequestFactory().get("/webclient/metadata_preview/image/1061/")
    request.session = {}

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webgateway_views, "render_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        webgateway_views, "render_image_region", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(webgateway_views, "get_longs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        webgateway_marshal, "imageMarshal", lambda image, key=None, request=None: {}
    )
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
    monkeypatch.setattr(webclient_views, "BaseContainer", _FakeMetadataPreviewContainer)
    monkeypatch.setattr(webclient_views, "BaseShare", lambda conn, share_id: object())
    monkeypatch.setattr(
        webclient_views,
        "getIntOrDefault",
        lambda request, key, default: default,
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)

    def failing_load_metadata_preview(
        request, c_type, c_id, conn=None, share_id=None, **kwargs
    ):
        raise RuntimeError(
            "Error instantiating pixel buffer: managed/path\n"
            "at com.glencoesoftware.omero.zarr.ZarrPixelsService.getPixelBuffer"
        )

    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", failing_load_metadata_preview
    )
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )

    integration.install_webgateway_overrides()

    context = webclient_views.load_metadata_preview(
        request,
        "image",
        "1061",
        conn=_FakeMetadataPreviewConn(),
    )

    assert context["rdefs"] == []
    assert context["rdefsJson"] == "[]"
    assert context["tiledImage"] is True


def test_render_tile_bad_request_escapes_user_input():
    """HttpResponseBadRequest from tile parsing must HTML-escape reflected input.

    User-supplied tile/region values flow into error messages.  They must be
    escaped to prevent reflected XSS when a browser renders the response.
    """
    from django.utils.html import escape as html_escape
    from omeroweb.webgateway import views as webgateway_views

    xss_payload = '<script>alert("xss")</script>'
    factory = RequestFactory()
    request = factory.get(
        "/render_image_region/1/0/0/",
        {"tile": xss_payload},
    )
    request.session = {"connector": {"server_id": "1"}}

    class _FakeImage:
        _re = None

        def _prepareRenderingEngine(self):
            raise ValueError("forced")

    import unittest.mock as mock

    with mock.patch.object(
        webgateway_views,
        "_get_prepared_image",
        return_value=(_FakeImage(), 90),
    ):
        response = integration._render_regular_image_region_with_safe_tile_size(
            request,
            1,
            0,
            0,
            conn=None,
        )

    assert response.status_code == 400
    body = response.content.decode("utf-8")
    assert xss_payload not in body
    assert html_escape(xss_payload) in body
    assert response["Content-Type"] == "text/plain; charset=utf-8"


def test_store_backed_render_response_and_pixel_helpers_cover_download_paths(
    monkeypatch,
):
    request = RequestFactory().get("/webclient/render_image/7/", {"format": "png"})

    class _Image:
        id = 7

        def getName(self):
            return "demo image.zarr"

    monkeypatch.setattr(
        integration,
        "render_store_backed_pil_image",
        lambda image, z=None, t=None: object(),
    )
    monkeypatch.setattr(
        integration,
        "encode_store_backed_pil_image",
        lambda pil_image, requested_format: (b"image-bytes", "image/png", "png"),
    )

    response = integration._store_backed_render_response(
        _Image(), request, z=0, t=0, download=True
    )

    assert response.status_code == 200
    assert response["Content-Length"] == "11"
    assert response["Content-Disposition"] == "attachment; filename=demo_image.zarr.png"

    contrast_node = type(
        "Node",
        (),
        {
            "metadata": {"contrast_limits": [[5, 15], [2, 20]]},
            "data": [type("Array", (), {"dtype": np.dtype(np.uint16)})()],
        },
    )()
    float_node = type(
        "Node",
        (),
        {
            "metadata": {},
            "data": [type("Array", (), {"dtype": np.dtype(np.float32)})()],
        },
    )()

    assert integration._store_backed_pixel_range(contrast_node) == (2.0, 20.0)
    assert integration._store_backed_pixel_range(float_node) == (0.0, 1.0)
    assert integration._select_marshaled_key({"a": {"b": {"c": 9}}}, "a.b.c") == 9
    assert integration._select_marshaled_key({"a": 1}, "a.b") is None


def test_store_backed_metadata_and_rendering_model_cover_parent_resolution():
    class _Project:
        id = 51
        name = "Project A"
        description = "A project"

    class _Dataset:
        OMERO_CLASS = "Dataset"
        id = 61
        name = "Dataset A"
        description = "A dataset"

    class _Well:
        def __init__(self):
            self.id = type("Value", (), {"val": 71})()

    class _WellSample:
        OMERO_CLASS = "WellSample"

        def __init__(self):
            self.well = _Well()

    class _Image:
        id = 99
        name = "managed.zarr"
        description = "Store-backed image"
        archived = True

        def getProject(self):
            return _Project()

        def listParents(self):
            return [_Dataset(), _WellSample()]

        def getName(self):
            return self.name

        def getAuthor(self):
            return "Alice"

        def getDate(self):
            return datetime(2026, 3, 30, 7, 0, 0)

        def getPixelsType(self):
            return "uint16"

    metadata = integration._store_backed_metadata(_Image())
    assert metadata["projectName"] == "Project A"
    assert metadata["datasetName"] == "Dataset A"
    assert metadata["wellId"] == 71
    assert metadata["pixelsType"] == "uint16"

    assert integration._store_backed_rendering_model([_FakeChannel()]) == "greyscale"
    assert integration._store_backed_rendering_model(
        [_FakeChannel(), _FakeChannel()]
    ) == ("color")


def test_load_metadata_preview_with_safe_rendering_dedupes_rendering_defs(
    monkeypatch,
):
    request = RequestFactory().get("/webclient/metadata_preview/image/42/")
    request.session = {}

    class _Image:
        def getAllRenderingDefs(self):
            return [
                {
                    "id": 1,
                    "owner": {"id": 7, "name": "alice"},
                    "c": [
                        {
                            "active": True,
                            "color": "FF0000",
                            "start": 0,
                            "end": 255,
                            "inverted": False,
                        }
                    ],
                    "model": "color",
                },
                {
                    "id": 2,
                    "owner": {"id": 7, "name": "alice"},
                    "c": [
                        {
                            "active": False,
                            "lut": "ice",
                            "start": 5,
                            "end": 10,
                            "inverted": True,
                        }
                    ],
                    "model": "greyscale",
                },
            ]

        def getRenderingDefId(self):
            return 2

        def getSizeX(self):
            return 256

        def getSizeY(self):
            return 256

    class _Manager:
        def __init__(self, conn, **kwargs):
            self.image = _Image()

    from omeroweb.webclient import views as webclient_views

    monkeypatch.setattr(webclient_views, "BaseContainer", _Manager)
    monkeypatch.setattr(webclient_views, "BaseShare", lambda conn, share_id: share_id)
    monkeypatch.setattr(
        webclient_views,
        "getIntOrDefault",
        lambda request, key, default: default,
    )

    context = integration._load_metadata_preview_with_safe_rendering(
        request,
        "image",
        "42",
        conn=type("Conn", (), {"getMaxPlaneSize": lambda self: (1024, 1024)})(),
    )

    assert context["tiledImage"] is False
    assert context["rdefs"][0]["id"] == 2
    assert '"m": "g"' in context["rdefsJson"]
    assert "5:10r$ice" in context["rdefsJson"]


def test_store_backed_region_response_rejects_invalid_requests(monkeypatch):
    node = type(
        "FakeNode",
        (),
        {
            "data": [
                type(
                    "FakeArray",
                    (),
                    {"shape": (1, 1, 8, 8), "chunks": ((1,), (1,), (4, 4), (4, 4))},
                )(),
                type(
                    "FakeArray",
                    (),
                    {"shape": (1, 1, 4, 4), "chunks": ((1,), (1,), (4,), (4,))},
                )(),
            ],
            "metadata": {"axes": ["t", "c", "y", "x"]},
        },
    )()

    monkeypatch.setattr(integration, "load_store_backed_image_node", lambda image: node)

    invalid_level = integration._store_backed_region_response(
        object(),
        RequestFactory().get(
            "/webclient/render_image_region/7/0/0/", {"tile": "3,0,0"}
        ),
        z=0,
        t=0,
        conn=None,
    )
    malformed_region = integration._store_backed_region_response(
        object(),
        RequestFactory().get(
            "/webclient/render_image_region/7/0/0/", {"region": "1,2"}
        ),
        z=0,
        t=0,
        conn=None,
    )
    missing_args = integration._store_backed_region_response(
        object(),
        RequestFactory().get("/webclient/render_image_region/7/0/0/"),
        z=0,
        t=0,
        conn=None,
    )

    assert invalid_level.status_code == 400
    assert invalid_level.content.decode("utf-8") == "invalid resolution level"
    assert malformed_region.status_code == 400
    assert malformed_region.content.decode("utf-8") == "malformed region argument"
    assert missing_args.status_code == 400
    assert missing_args.content.decode("utf-8") == "tile or region argument required"


def test_render_regular_image_region_with_safe_tile_size_rejects_invalid_levels_and_missing_image(
    monkeypatch,
):
    from omeroweb.webgateway import views as webgateway_views

    request = RequestFactory().get(
        "/webclient/render_image_region/7/0/0/",
        {"tile": "3,0,0,2048,0"},
    )
    request.session = {"connector": {"server_id": 1}}
    image = _PreparedRegionImage()

    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda request, iid, server_id=None, conn=None: (image, 0.9),
    )

    invalid_level = integration._render_regular_image_region_with_safe_tile_size(
        request,
        7,
        0,
        0,
        conn=_FakeConnForTileSize(),
    )
    assert invalid_level.status_code == 400
    assert invalid_level.content.decode("utf-8").startswith("Invalid resolution level")

    request = RequestFactory().get(
        "/webclient/render_image_region/7/0/0/",
        {"region": "bad"},
    )
    request.session = {"connector": {"server_id": 1}}
    malformed_region = integration._render_regular_image_region_with_safe_tile_size(
        request,
        7,
        0,
        0,
        conn=_FakeConnForTileSize(),
    )
    assert malformed_region.status_code == 400
    assert "malformed region argument" in malformed_region.content.decode("utf-8")

    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda request, iid, server_id=None, conn=None: None,
    )
    with pytest.raises(integration.Http404):
        integration._render_regular_image_region_with_safe_tile_size(
            request,
            7,
            0,
            0,
            conn=_FakeConnForTileSize(),
        )


def test_patch_urlpatterns_updates_nested_routes():
    def original_view(request):
        return HttpResponse("original")

    def replacement_view(request):
        return HttpResponse("replacement")

    urlpatterns = [
        path("root/", original_view, name="root"),
        path(
            "nested/",
            include(
                (
                    [
                        path("child/", original_view, name="child"),
                    ],
                    "nested",
                )
            ),
        ),
    ]

    integration._patch_urlpatterns(
        urlpatterns,
        {
            "root": replacement_view,
            "child": replacement_view,
        },
    )

    root_response = urlpatterns[0].callback(RequestFactory().get("/root/"))
    child_response = (
        urlpatterns[1].url_patterns[0].callback(RequestFactory().get("/nested/child/"))
    )

    assert root_response.content == b"replacement"
    assert child_response.content == b"replacement"


def test_install_webgateway_overrides_renders_store_backed_thumbnails_and_images(
    monkeypatch,
):
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")
    monkeypatch.setattr(integration.settings, "THUMBNAILS_BATCH", 10, raising=False)

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    request = RequestFactory().get("/webgateway/render/7/", {"id": ["7", "8"]})
    request.session = {"server_settings": {"browser": {"thumb_default_size": 64}}}

    store_backed_image = type("StoreBackedImage", (), {"store_backed": True, "id": 7})()
    regular_image = type("RegularImage", (), {"store_backed": False, "id": 8})()

    class _Conn:
        def getObject(self, object_type, iid):
            return {7: store_backed_image, 8: regular_image}.get(int(iid))

        def getThumbnailSet(self, ids, width):
            return {8: b"regular-thumb"}

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: HttpResponse()
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        webgateway_views,
        "render_image",
        lambda *args, **kwargs: HttpResponse(b"regular", content_type="image/jpeg"),
    )
    monkeypatch.setattr(
        webgateway_views,
        "render_image_region",
        lambda *args, **kwargs: HttpResponse(
            b"regular-region", content_type="image/jpeg"
        ),
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(
        webgateway_views,
        "get_longs",
        lambda request, key: [7, 8],
    )
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda request, key, default: default
    )
    monkeypatch.setattr(
        webgateway_marshal, "imageMarshal", lambda image, key=None, request=None: {}
    )
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
    monkeypatch.setattr(
        webclient_views, "load_metadata_preview", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )
    monkeypatch.setattr(
        integration,
        "render_store_backed_thumbnail_bytes",
        lambda image, size=96, z=None, t=None: b"store-thumb",
    )
    monkeypatch.setattr(
        integration,
        "_store_backed_render_response",
        lambda image, request, z=None, t=None, download=False: HttpResponse(
            b"store-image", content_type="image/png"
        ),
    )

    integration.install_webgateway_overrides()

    thumb_response = webgateway_views._render_thumbnail(
        request,
        7,
        w=None,
        h=None,
        conn=_Conn(),
    )
    thumbs_json = webgateway_views.get_thumbnails_json(request, w=64, conn=_Conn())
    image_response = webgateway_views.render_image(request, 7, z=0, t=0, conn=_Conn())

    assert thumb_response == b"store-thumb"
    assert thumbs_json[7].startswith("data:image/jpeg;base64,")
    assert thumbs_json[8].startswith("data:image/jpeg;base64,")
    assert image_response.content == b"store-image"
