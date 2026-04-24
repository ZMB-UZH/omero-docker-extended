import builtins
import os
import warnings
from datetime import datetime
from types import SimpleNamespace

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
        @staticmethod
        def getHtml():
            return "FFFFFF"

    def getLabel(self):
        return self._label

    def getColor(self):
        return self._Color()

    @staticmethod
    def getEmissionWave():
        return None

    @staticmethod
    def getFamily():
        return None

    @staticmethod
    def getCoefficient():
        return None

    @staticmethod
    def getLut():
        return None

    @staticmethod
    def getWindowStart():
        return None

    @staticmethod
    def getWindowEnd():
        return None

    @staticmethod
    def getWindowMin():
        return 1.0

    @staticmethod
    def getWindowMax():
        return 9.0

    @staticmethod
    def isActive():
        return False

    @staticmethod
    def isInverted():
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

    @staticmethod
    def getProject():
        return None

    @staticmethod
    def listParents():
        return []

    @staticmethod
    def getAuthor():
        return "Test User"

    @staticmethod
    def getDate():
        return datetime(2026, 3, 23, 12, 0, 0)

    @staticmethod
    def getPixelsType():
        return "uint16"

    @staticmethod
    def canAnnotate():
        return False

    @staticmethod
    def canEdit():
        return True

    @staticmethod
    def canDelete():
        return True

    @staticmethod
    def canLink():
        return False

    @staticmethod
    def getSizeX():
        return 1024

    @staticmethod
    def getSizeY():
        return 512

    @staticmethod
    def getSizeZ():
        return 4

    @staticmethod
    def getSizeT():
        return 1

    @staticmethod
    def getSizeC():
        return 1

    @staticmethod
    def splitChannelDims():
        return {"g": {"width": 1026, "height": 514}}

    @staticmethod
    def getProjection():
        return "normal"

    @staticmethod
    def getPixelSizeX(units=None):
        return None

    @staticmethod
    def getPixelSizeY(units=None):
        return None

    @staticmethod
    def getPixelSizeZ(units=None):
        return None

    @staticmethod
    def getObjectiveSettings():
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
    monkeypatch.setattr(integration.settings, "THUMBNAILS_BATCH", 2, raising=False)

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
        @staticmethod
        def getObject(object_type, iid):
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
        @staticmethod
        def getObject(object_type, iid):
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
    @staticmethod
    def getConfigValue(key):
        assert key == "omero.pixeldata.max_tile_length"
        return "1024"


class _FakeConnForTileSize:
    @staticmethod
    def getConfigService():
        return _FakeConfigService()


class _FakeResolution:
    def __init__(self, size_x, size_y):
        self.sizeX = size_x
        self.sizeY = size_y


class _FailingResolutionEngine:
    @staticmethod
    def getResolutionLevels():
        return 2

    @staticmethod
    def getTileSize():
        raise RuntimeError("ZarrReader.getOptimalTileWidth failed during getTileSize")

    @staticmethod
    def getResolutionDescriptions():
        return [_FakeResolution(1024, 512), _FakeResolution(512, 256)]

    @staticmethod
    def getDefaultZ():
        return 0

    @staticmethod
    def getDefaultT():
        return 0


class _FakeRegularTileFailureImage(_FakeImageDataImage):
    def __init__(self):
        super().__init__()
        self._re = _FailingResolutionEngine()
        self._conn = _FakeConnForTileSize()

    @staticmethod
    def _prepareRenderingEngine():
        return True

    @staticmethod
    def getPixelRange():
        return (0, 65535)

    @staticmethod
    def isGreyscaleRenderingModel():
        return False

    @staticmethod
    def isInvertedAxis():
        return False


class _PreparedRegionImage:
    def __init__(self):
        self._re = _FailingResolutionEngine()
        self.calls = []

    @staticmethod
    def _prepareRenderingEngine():
        return True

    @staticmethod
    def getSizeX():
        return 1024

    @staticmethod
    def getSizeY():
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

    @staticmethod
    def getAllRenderingDefs():
        raise RuntimeError(
            "Error instantiating pixel buffer: managed/path\n"
            "at com.glencoesoftware.omero.zarr.ZarrPixelsService.getPixelBuffer"
        )

    @staticmethod
    def getRenderingDefId():
        raise AssertionError("rendering definition lookup should not run after failure")

    @staticmethod
    def getSizeX():
        return 4096

    @staticmethod
    def getSizeY():
        return 2048


class _FakeMetadataPreviewContainer:
    def __init__(self, conn, **kwargs):
        self.conn = conn
        self.kwargs = kwargs
        self.image = _FakeMetadataPreviewImage()


class _FakeMetadataPreviewConn:
    @staticmethod
    def getMaxPlaneSize():
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
    monkeypatch.setattr(
        integration.settings._wrapped, "THUMBNAILS_BATCH", 2, raising=False
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
        @staticmethod
        def getObject(object_type, iid):
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
    monkeypatch.setattr(
        integration.settings._wrapped, "THUMBNAILS_BATCH", 2, raising=False
    )

    integration.install_webgateway_overrides()

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


def test_render_tile_bad_request_does_not_reflect_user_input():
    """Tile parsing errors must not echo attacker-controlled values."""
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

        @staticmethod
        def _prepareRenderingEngine():
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
    assert body == "malformed tile argument"
    assert response["Content-Type"] == "text/plain; charset=utf-8"


def test_store_backed_render_response_and_pixel_helpers_cover_download_paths(
    monkeypatch,
):
    request = RequestFactory().get("/webclient/render_image/7/", {"format": "png"})

    class _Image:
        id = 7

        @staticmethod
        def getName():
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

        @staticmethod
        def getProject():
            return _Project()

        @staticmethod
        def listParents():
            return [_Dataset(), _WellSample()]

        def getName(self):
            return self.name

        @staticmethod
        def getAuthor():
            return "Alice"

        @staticmethod
        def getDate():
            return datetime(2026, 3, 30, 7, 0, 0)

        @staticmethod
        def getPixelsType():
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
        @staticmethod
        def getAllRenderingDefs():
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

        @staticmethod
        def getRenderingDefId():
            return 2

        @staticmethod
        def getSizeX():
            return 256

        @staticmethod
        def getSizeY():
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
    assert invalid_level.content.decode("utf-8") == "invalid resolution level"

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
        @staticmethod
        def getObject(object_type, iid):
            return {7: store_backed_image, 8: regular_image}.get(int(iid))

        @staticmethod
        def getThumbnailSet(ids, width):
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


def test_install_webgateway_overrides_cover_regular_fallback_and_error_paths(
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

    regular_image = type("RegularImage", (), {"store_backed": False})()
    store_backed_image = type("StoreBackedImage", (), {"store_backed": True})()

    class _ThumbMap:
        def __getitem__(self, image_id):
            if image_id == 3:
                raise KeyError(image_id)
            if image_id == 4:
                raise IndexError("thumbnail lookup failed")
            return b"thumb"

    class _Conn:
        def __init__(self, image_map):
            self._image_map = image_map

        def getObject(self, object_type, iid):
            assert object_type == "Image"
            return self._image_map.get(iid)

        @staticmethod
        def getThumbnailSet(ids, width):
            return _ThumbMap()

    thumb_calls = []
    original_thumb_calls = []
    original_render_image_calls = []
    marshal_calls = []
    fallback_region_calls = []

    def original_render_thumbnail(
        request, iid, w=None, h=None, conn=None, _defcb=None, **kwargs
    ):
        original_thumb_calls.append((iid, w, h))
        return HttpResponse(b"regular-thumb", content_type="image/jpeg")

    def original_get_thumbnails_json(request, w=None, conn=None, **kwargs):
        return {"source": "original", "width": w}

    def original_render_image(request, iid, z=None, t=None, conn=None, **kwargs):
        original_render_image_calls.append((iid, z, t, kwargs))
        return HttpResponse(b"regular-image", content_type="image/jpeg")

    def failing_render_image_region(request, iid, z, t, conn=None, **kwargs):
        raise RuntimeError("tile too large")

    def failing_image_data_json(request, conn=None, _internal=False, **kwargs):
        if kwargs["iid"] == 9:
            return {"source": "original", "iid": kwargs["iid"]}
        raise RuntimeError("tile too large")

    def failing_load_metadata_preview(
        request, c_type, c_id, conn=None, share_id=None, **kwargs
    ):
        raise RuntimeError("preview boom")

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        integration,
        "render_store_backed_thumbnail_bytes",
        lambda image, size, z=None, t=None: (
            thumb_calls.append((size, z, t, image.store_backed)) or b"store-thumb"
        ),
    )
    monkeypatch.setattr(
        integration,
        "_render_regular_image_region_with_safe_tile_size",
        lambda request, iid, z, t, conn=None: (
            fallback_region_calls.append((iid, z, t))
            or HttpResponse(b"fallback-region")
        ),
    )
    monkeypatch.setattr(
        integration,
        "_marshal_regular_image_data_with_safe_tile_size",
        lambda image, request: marshal_calls.append(image) or {"nested": {"value": 7}},
    )
    monkeypatch.setattr(
        integration,
        "_is_known_rendering_engine_failure",
        lambda exc: False,
    )
    monkeypatch.setattr(
        integration,
        "HttpJavascriptResponseServerError",
        lambda message: HttpResponse(message, status=500),
    )
    monkeypatch.setattr(
        integration, "settings", type("Settings", (), {"THUMBNAILS_BATCH": 2})()
    )
    monkeypatch.setattr(
        integration,
        "is_known_tile_size_failure",
        lambda exc: "tile too large" in str(exc),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", original_render_thumbnail
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", original_get_thumbnails_json
    )
    monkeypatch.setattr(webgateway_views, "render_image", original_render_image)
    monkeypatch.setattr(
        webgateway_views, "render_image_region", failing_render_image_region
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", failing_image_data_json)
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(
        webgateway_views,
        "getIntOrDefault",
        lambda request, name, default=None: request.GET.get(name, default),
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
        webclient_views, "load_metadata_preview", failing_load_metadata_preview
    )
    monkeypatch.setattr(webclient_views, "render_response", _identity_decorator)
    monkeypatch.setattr(webgateway_urls, "urlpatterns", [])
    monkeypatch.setattr(webclient_urls, "urlpatterns", [])
    monkeypatch.setattr(
        webgateway_views, "_omero_web_zarr_store_backed_overrides", False, raising=False
    )

    integration.install_webgateway_overrides()

    regular_conn = _Conn(
        {1: regular_image, 3: regular_image, 4: regular_image, 9: None}
    )
    store_conn = _Conn({2: store_backed_image})

    regular_thumb_request = RequestFactory().get("/webgateway/render_thumbnail/1/")
    regular_thumb_request.session = {}
    regular_thumb = webgateway_views._render_thumbnail(
        regular_thumb_request,
        1,
        w=16,
        h=20,
        conn=regular_conn,
    )
    assert regular_thumb.content == b"regular-thumb"
    assert original_thumb_calls == [(1, 16, 20)]

    store_thumb_request = RequestFactory().get(
        "/webgateway/render_thumbnail/2/",
        {"z": 3, "t": 4},
    )
    store_thumb_request.session = {}
    store_thumb = webgateway_views._render_thumbnail(
        store_thumb_request,
        2,
        w=16,
        h=24,
        conn=store_conn,
    )
    assert store_thumb == b"store-thumb"
    assert thumb_calls[-1] == (24, "3", "4", True)

    monkeypatch.setattr(webgateway_views, "get_longs", lambda request, name: [1])
    original_thumbs_request = RequestFactory().get("/webgateway/thumbs-json/")
    original_thumbs_request.session = {}
    assert webgateway_views.get_thumbnails_json(
        original_thumbs_request,
        w=32,
        conn=regular_conn,
    ) == {"source": "original", "width": 32}

    monkeypatch.setattr(
        webgateway_views,
        "get_longs",
        lambda request, name: [0, 1, 2],
    )
    too_many_request = RequestFactory().get("/webgateway/thumbs-json/")
    too_many_request.session = {}
    too_many = webgateway_views.get_thumbnails_json(
        too_many_request,
        conn=store_conn,
    )
    assert getattr(too_many, "status_code", 500) == 500

    integration.settings.THUMBNAILS_BATCH = 5
    monkeypatch.setattr(webgateway_views, "get_longs", lambda request, name: [2, 3, 4])
    monkeypatch.setattr(
        integration,
        "render_store_backed_thumbnail_bytes",
        lambda image, size, z=None, t=None: (_ for _ in ()).throw(
            RuntimeError("render failed")
        ),
    )
    mixed_thumbs_request = RequestFactory().get("/webgateway/thumbs-json/")
    mixed_thumbs_request.session = {}
    mixed_thumbs = webgateway_views.get_thumbnails_json(
        mixed_thumbs_request,
        w=None,
        conn=_Conn({2: store_backed_image, 3: regular_image, 4: regular_image}),
    )
    assert mixed_thumbs == {2: None, 3: None, 4: None}

    regular_image_response = webgateway_views.render_image(
        RequestFactory().get("/webgateway/render_image/1/"),
        1,
        z=0,
        t=1,
        conn=regular_conn,
    )
    assert regular_image_response.content == b"regular-image"
    assert original_render_image_calls == [(1, 0, 1, {})]

    fallback_region = webgateway_views.render_image_region(
        RequestFactory().get(
            "/webgateway/render_image_region/1/0/0/",
            {"tile": "0,0,0"},
        ),
        1,
        0,
        0,
        conn=regular_conn,
    )
    assert fallback_region.content == b"fallback-region"
    assert fallback_region_calls == [(1, 0, 0)]

    assert webgateway_views.imageData_json(
        RequestFactory().get("/webgateway/imgData/9/"),
        conn=regular_conn,
        iid=9,
    ) == {"source": "original", "iid": 9}
    assert (
        webgateway_views.imageData_json(
            RequestFactory().get("/webgateway/imgData/1/"),
            conn=_Conn({1: regular_image}),
            iid=1,
            key="nested.value",
        )
        == 7
    )
    assert marshal_calls == [regular_image]

    with pytest.raises(RuntimeError, match="preview boom"):
        webclient_views.load_metadata_preview(
            RequestFactory().get("/webclient/metadata_preview/"),
            "image",
            1,
            conn=regular_conn,
        )


def test_install_safe_image_marshal_overrides_handles_optional_import_failures(
    monkeypatch,
):
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import views as webgateway_views

    def original_image_marshal(image, key=None, request=None):
        return {"id": getattr(image, "id", None)}

    monkeypatch.setattr(webgateway_marshal, "imageMarshal", original_image_marshal)
    monkeypatch.setattr(webgateway_views, "imageMarshal", original_image_marshal)
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

    real_import = builtins.__import__

    def fake_import(name, global_vars=None, local_vars=None, fromlist=(), level=0):
        if name in {"omero_iviewer.views", "omero_figure.views"}:
            raise ImportError(f"{name} unavailable")
        return real_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    safe_image_marshal = integration._install_safe_image_marshal_overrides(
        webgateway_marshal
    )

    assert safe_image_marshal(SimpleNamespace(id=9)) == {"id": 9}
    assert webgateway_views.imageMarshal is safe_image_marshal


def test_install_webgateway_overrides_returns_when_imports_fail_or_already_installed(
    monkeypatch,
):
    real_import = builtins.__import__

    def failing_import(name, global_vars=None, local_vars=None, fromlist=(), level=0):
        if name == "omeroweb.webgateway":
            raise ImportError("webgateway unavailable")
        return real_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    integration.install_webgateway_overrides()
    monkeypatch.setattr(builtins, "__import__", real_import)

    from omeroweb.webgateway import views as webgateway_views

    monkeypatch.setattr(
        webgateway_views,
        "_omero_web_zarr_store_backed_overrides",
        True,
        raising=False,
    )
    integration.install_webgateway_overrides()


def test_install_webgateway_overrides_covers_store_backed_region_image_data_and_w_only_thumbnails(
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

    store_backed_image = type("StoreBackedImage", (), {"store_backed": True, "id": 7})()
    recorded_sizes = []

    class _Conn:
        @staticmethod
        def getObject(object_type, iid):
            return store_backed_image

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: HttpResponse()
    )
    monkeypatch.setattr(
        webgateway_views,
        "render_image_region",
        lambda *args, **kwargs: HttpResponse(b"regular-region"),
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        webgateway_views, "render_image", lambda *args, **kwargs: HttpResponse()
    )
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda request, key, default=None: None
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
        lambda image, size=96, z=None, t=None: (
            recorded_sizes.append(size) or b"store-thumb"
        ),
    )
    monkeypatch.setattr(
        integration,
        "_store_backed_region_response",
        lambda image, request, z=None, t=None, conn=None: HttpResponse(
            b"store-region",
            content_type="image/png",
        ),
    )
    monkeypatch.setattr(
        integration,
        "_store_backed_image_data",
        lambda image, request: {"payload": {"value": 11}},
    )

    integration.install_webgateway_overrides()

    thumbnail_request = RequestFactory().get("/webgateway/render_thumbnail/7/")
    thumbnail_request.session = {}
    assert (
        webgateway_views._render_thumbnail(
            thumbnail_request,
            7,
            w="48",
            h=None,
            conn=_Conn(),
        )
        == b"store-thumb"
    )
    assert recorded_sizes == [48]
    assert (
        webgateway_views.render_image_region(
            RequestFactory().get("/webgateway/render_image_region/7/0/0/"),
            7,
            0,
            0,
            conn=_Conn(),
        ).content
        == b"store-region"
    )
    assert (
        webgateway_views.imageData_json(
            RequestFactory().get("/webgateway/imgData/7/"),
            conn=_Conn(),
            iid=7,
            key="payload.value",
        )
        == 11
    )


def test_install_webgateway_overrides_re_raises_regular_tile_failures_when_safe_rendering_is_off(
    monkeypatch,
):
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "false")

    def _identity_decorator():
        return lambda func: func

    from omeroweb.webclient import urls as webclient_urls
    from omeroweb.webclient import views as webclient_views
    from omeroweb.webclient import webclient_gateway
    from omeroweb.webgateway import marshal as webgateway_marshal
    from omeroweb.webgateway import urls as webgateway_urls
    from omeroweb.webgateway import views as webgateway_views

    regular_image = type("RegularImage", (), {"store_backed": False, "id": 3})()

    class _Conn:
        @staticmethod
        def getObject(object_type, iid):
            return regular_image

    monkeypatch.setattr(integration, "login_required", _identity_decorator)
    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    monkeypatch.setattr(
        integration,
        "is_known_tile_size_failure",
        lambda exc: "tile too large" in str(exc),
    )
    monkeypatch.setattr(
        webclient_gateway.ImageWrapper, "getChannels", lambda self, *args, **kwargs: []
    )
    monkeypatch.setattr(
        webgateway_views, "_render_thumbnail", lambda *args, **kwargs: HttpResponse()
    )
    monkeypatch.setattr(
        webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        webgateway_views, "render_image", lambda *args, **kwargs: HttpResponse()
    )
    monkeypatch.setattr(
        webgateway_views,
        "render_image_region",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tile too large")),
    )
    monkeypatch.setattr(webgateway_views, "imageData_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(webgateway_views, "jsonp", lambda func: func)
    monkeypatch.setattr(
        webgateway_views, "getIntOrDefault", lambda request, name, default=None: default
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

    with pytest.raises(RuntimeError, match="tile too large"):
        webgateway_views.render_image_region(
            RequestFactory().get(
                "/webgateway/render_image_region/3/0/0/",
                {"tile": "0,0,0"},
            ),
            3,
            0,
            0,
            conn=_Conn(),
        )
