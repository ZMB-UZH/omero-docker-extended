import os
import sys
import types
import warnings
from datetime import datetime
from types import SimpleNamespace

import django
import numpy as np
import pytest
from django.http import Http404
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


class _Color:
    def __init__(self, html):
        self._html = html

    def getHtml(self):
        return self._html


class _Channel:
    def __init__(
        self,
        *,
        label="base",
        color="FFFFFF",
        active=False,
        inverted=None,
        window=(1.0, 5.0),
        raise_color=False,
    ):
        self._label = label
        self._color = color
        self._active = active
        self._inverted = inverted
        self._window = window
        self._raise_color = raise_color

    def getLabel(self):
        return self._label

    def getColor(self):
        if self._raise_color:
            raise RuntimeError("color failure")
        return _Color(self._color)

    def isActive(self):
        return self._active

    def isInverted(self):
        return self._inverted

    def getWindowStart(self):
        return self._window[0]

    def getWindowEnd(self):
        return self._window[1]


class _WellSampleParent:
    OMERO_CLASS = "WellSample"

    def __init__(self, well_id):
        self.well = SimpleNamespace(id=SimpleNamespace(val=well_id))


class _DatasetParent:
    OMERO_CLASS = "Dataset"

    def __init__(self, dataset_id, name, description):
        self.id = dataset_id
        self.name = name
        self.description = description


class _Resolution:
    def __init__(self, size_x, size_y):
        self.sizeX = size_x
        self.sizeY = size_y


class _RenderingEngine:
    def getResolutionLevels(self):
        return 2

    def getResolutionDescriptions(self):
        return [_Resolution(1024, 512), _Resolution(512, 256)]

    def getDefaultZ(self):
        return 3

    def getDefaultT(self):
        return 4


class _ObjectiveSettings:
    def getObjective(self):
        return SimpleNamespace(getNominalMagnification=lambda: 40)


class _MarshalImage:
    description = "description"
    archived = False

    def __init__(self, *, prepare_result=True, prepare_exception=None):
        self.id = 7
        self.name = "demo.zarr"
        self._prepare_result = prepare_result
        self._prepare_exception = prepare_exception
        self._re = _RenderingEngine()
        self._conn = object()

    def _prepareRenderingEngine(self):
        if self._prepare_exception is not None:
            raise self._prepare_exception
        return self._prepare_result

    def getName(self):
        return self.name

    def canAnnotate(self):
        return False

    def canEdit(self):
        return True

    def canDelete(self):
        return True

    def canLink(self):
        return False

    def getObjectiveSettings(self):
        return _ObjectiveSettings()

    def getSizeX(self):
        return 1024

    def getSizeY(self):
        return 512

    def getSizeZ(self):
        return 4

    def getSizeT(self):
        return 2

    def getSizeC(self):
        return 1

    def getPixelRange(self):
        raise TypeError("pixel range unavailable")

    def getChannels(self):
        return [_Channel(label="DNA")]

    def splitChannelDims(self):
        return {"g": {"width": 1024, "height": 512}}

    def isGreyscaleRenderingModel(self):
        return False

    def getProjection(self):
        return "normal"

    def isInvertedAxis(self):
        return False

    def getAuthor(self):
        return "Author"

    def getDate(self):
        return datetime(2026, 3, 30, 12, 0, 0)

    def getPixelsType(self):
        return "uint16"

    def getProject(self):
        return SimpleNamespace(id=11, name="Project", description="Project description")

    def listParents(self):
        return [
            _DatasetParent(12, "Dataset", "Dataset description"),
            _WellSampleParent(13),
        ]

    def getPixelSizeX(self, units=None):
        return SimpleNamespace(getValue=lambda: 0.5)

    def getPixelSizeY(self, units=None):
        return SimpleNamespace(getValue=lambda: 0.75)

    def getPixelSizeZ(self, units=None):
        return SimpleNamespace(getValue=lambda: 1.25)


class _SingleLevelImage:
    description = ""
    archived = False

    def __init__(self, *, objective_mode="raise", projection_mode="raise"):
        self.id = 9
        self.name = "single.zarr"
        self._objective_mode = objective_mode
        self._projection_mode = projection_mode
        self._conn = SimpleNamespace(
            getMaxPlaneSize=lambda: (_ for _ in ()).throw(RuntimeError("plane-size"))
        )

    def getChannels(self, noRE=False):
        return [_Channel(label="DNA")]

    def getProjection(self):
        if self._projection_mode == "raise":
            raise RuntimeError("projection")
        return "maximum"

    def getPixelSizeX(self, units=None):
        raise RuntimeError("x")

    def getPixelSizeY(self, units=None):
        return None

    def getPixelSizeZ(self, units=None):
        return SimpleNamespace(getValue=lambda: 1.5)

    def getObjectiveSettings(self):
        if self._objective_mode == "raise":
            raise RuntimeError("objective")
        if self._objective_mode == "none":
            return None
        return SimpleNamespace(
            getObjective=lambda: SimpleNamespace(getNominalMagnification=lambda: 63)
        )

    def canAnnotate(self):
        return True

    def canEdit(self):
        return False

    def canDelete(self):
        return False

    def canLink(self):
        return True

    def getSizeX(self):
        return 128

    def getSizeY(self):
        return 64

    def getSizeZ(self):
        return 2

    def getSizeT(self):
        return 1

    def getSizeC(self):
        return 1

    def splitChannelDims(self):
        return {"g": {"width": 128, "height": 64}}


def test_store_backed_render_helpers_cover_metadata_ranges_and_downloads(monkeypatch):
    monkeypatch.setenv("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")
    assert integration._safe_rendering_enabled() is True

    gateway_module = types.ModuleType("omero.gateway")
    gateway_module.ColorHolder = type(
        "ColorHolder",
        (),
        {"fromRGBA": staticmethod(lambda r, g, b, a: _Color(f"{r:02X}{g:02X}{b:02X}"))},
    )
    monkeypatch.setitem(sys.modules, "omero.gateway", gateway_module)

    wrapper = integration._StoreBackedChannelWrapper(
        _Channel(inverted=None),
        {
            "label": "DNA",
            "color": (255, 0, 0),
            "active": True,
            "window": (3.0, 9.0),
        },
    )
    assert wrapper.getLabel() == "DNA"
    assert wrapper.getColor().getHtml() == "FF0000"
    assert wrapper.isActive() is True
    assert wrapper.isInverted() is False
    assert wrapper.getWindowStart() == 3.0
    assert wrapper.getWindowEnd() == 9.0

    passthrough_wrapper = integration._StoreBackedChannelWrapper(
        _Channel(active=True), {}
    )
    assert passthrough_wrapper.isActive() is True
    assert passthrough_wrapper.getWindowStart() == 1.0
    assert passthrough_wrapper.getWindowEnd() == 5.0

    monkeypatch.setattr(
        integration,
        "get_store_backed_channel_overrides",
        lambda image, channels=None: [{"label": "Override"}],
    )
    decorated = integration._decorate_store_backed_channels(
        object(), [_Channel(label="one"), _Channel(label="two")]
    )
    assert [channel.getLabel() for channel in decorated] == ["Override", "two"]
    assert integration._decorate_store_backed_channels(object(), []) == []

    monkeypatch.setattr(
        integration,
        "is_store_backed_image",
        lambda image: getattr(image, "store_backed", False),
    )
    store_backed = SimpleNamespace(store_backed=True)
    conn = SimpleNamespace(getObject=lambda model, iid: store_backed)
    assert integration._get_store_backed_image(conn, 7) is store_backed
    conn = SimpleNamespace(
        getObject=lambda model, iid: SimpleNamespace(store_backed=False)
    )
    assert integration._get_store_backed_image(conn, 7) is None

    monkeypatch.setattr(
        integration,
        "render_store_backed_pil_image",
        lambda image, z=None, t=None: object(),
    )
    monkeypatch.setattr(
        integration,
        "encode_store_backed_pil_image",
        lambda pil_image, requested_format: (b"payload", "image/png", "png"),
    )
    request = SimpleNamespace(GET={"format": "png"})
    image = SimpleNamespace(id=7, getName=lambda: "demo.zarr")
    inline = integration._store_backed_render_response(image, request)
    assert inline.content == b"payload"
    assert inline["Content-Type"] == "image/png"

    download = integration._store_backed_render_response(image, request, download=True)
    assert download["Content-Type"] == "application/force-download"
    assert download["Content-Length"] == "7"
    assert download["Content-Disposition"].endswith("demo.zarr.png")

    contrast_node = SimpleNamespace(
        metadata={"contrast_limits": [[2, 8], [1, 9]]},
        data=[np.zeros((1,), dtype=np.uint16)],
    )
    assert integration._store_backed_pixel_range(contrast_node) == (1.0, 9.0)

    integer_node = SimpleNamespace(metadata={}, data=[np.zeros((1,), dtype=np.uint16)])
    assert integration._store_backed_pixel_range(integer_node) == (0, 65535)

    float_node = SimpleNamespace(metadata={}, data=[np.zeros((1,), dtype=np.float32)])
    assert integration._store_backed_pixel_range(float_node) == (0.0, 1.0)

    object_node = SimpleNamespace(
        metadata={}, data=[SimpleNamespace(dtype=np.dtype("O"))]
    )
    assert integration._store_backed_pixel_range(object_node) == (0, 255)

    assert (
        integration._store_backed_rendering_model([_Channel(), _Channel()]) == "color"
    )
    assert integration._store_backed_rendering_model([]) == "greyscale"
    assert (
        integration._store_backed_rendering_model([_Channel(color="00FF00")]) == "color"
    )
    assert (
        integration._store_backed_rendering_model([_Channel(raise_color=True)])
        == "greyscale"
    )

    image = _MarshalImage()
    metadata = integration._store_backed_metadata(image)
    assert metadata["projectName"] == "Project"
    assert metadata["datasetName"] == "Dataset"
    assert metadata["wellId"] == 13
    assert integration._pixel_size_in_microns(image) == {"x": 0.5, "y": 0.75, "z": 1.25}

    broken_image = SimpleNamespace(
        id=8,
        name=None,
        description="",
        archived=False,
        getName=lambda: "broken.zarr",
        getProject=lambda: (_ for _ in ()).throw(RuntimeError("project failure")),
        listParents=lambda: (_ for _ in ()).throw(RuntimeError("parent failure")),
        getAuthor=lambda: "Author",
        getDate=lambda: datetime(2026, 3, 30, 12, 0, 0),
        getPixelsType=lambda: "uint8",
        getPixelSizeX=lambda units=None: (_ for _ in ()).throw(RuntimeError("x")),
        getPixelSizeY=lambda units=None: None,
        getPixelSizeZ=lambda units=None: (_ for _ in ()).throw(RuntimeError("z")),
    )
    broken_metadata = integration._store_backed_metadata(broken_image)
    assert broken_metadata["projectName"] == "Multiple"
    assert broken_metadata["datasetName"] == "Multiple"
    assert integration._pixel_size_in_microns(broken_image) == {
        "x": None,
        "y": None,
        "z": None,
    }

    assert integration._exception_text(RuntimeError("boom")) == "boom"
    monkeypatch.setattr(integration, "is_known_tile_size_failure", lambda exc: False)
    exc = RuntimeError(
        "Error instantiating pixel buffer\nZarrPixelsService.getPixelBuffer"
    )
    assert integration._is_known_rendering_engine_failure(exc) is True


def test_store_backed_image_data_covers_projection_tile_and_objective_fallbacks(
    monkeypatch,
):
    monkeypatch.setattr(integration, "load_store_backed_image_node", lambda image: None)
    monkeypatch.setattr(
        integration,
        "_decorate_store_backed_channels",
        lambda image, channels: channels,
    )
    monkeypatch.setattr(
        integration, "channelMarshal", lambda channel: channel.getLabel()
    )
    monkeypatch.setattr(
        integration,
        "_store_backed_metadata",
        lambda image: {"imageName": image.name},
    )

    request = SimpleNamespace(
        session={"server_settings": {"viewer": {"initial_zoom_level": -1}}}
    )
    fallback_payload = integration._store_backed_image_data(
        _SingleLevelImage(), request
    )

    assert fallback_payload["tiles"] is False
    assert fallback_payload["pixel_size"] == {"z": 1.5}
    assert fallback_payload["rdefs"]["projection"] == "normal"
    assert fallback_payload["init_zoom"] == 0
    assert "nominalMagnification" not in fallback_payload

    magnified_payload = integration._store_backed_image_data(
        _SingleLevelImage(objective_mode="value", projection_mode="value"),
        SimpleNamespace(session={"server_settings": {"viewer": {}}}),
    )
    assert magnified_payload["nominalMagnification"] == 63
    assert magnified_payload["rdefs"]["projection"] == "maximum"


def test_load_metadata_preview_with_safe_rendering_covers_share_well_and_reraises(
    monkeypatch,
):
    from omeroweb.webclient import views as webclient_views

    preview_image = SimpleNamespace(
        id=17,
        getAllRenderingDefs=lambda: (_ for _ in ()).throw(
            RuntimeError("renderer busy")
        ),
        getRenderingDefId=lambda: 3,
        getSizeX=lambda: 256,
        getSizeY=lambda: 128,
    )
    manager = SimpleNamespace(
        image=None,
        well=SimpleNamespace(getImage=lambda index: preview_image),
    )

    monkeypatch.setattr(webclient_views, "getIntOrDefault", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        webclient_views,
        "BaseContainer",
        lambda conn, **kwargs: manager,
    )
    monkeypatch.setattr(
        webclient_views,
        "BaseShare",
        lambda conn, share_id: f"share-{share_id}",
    )
    monkeypatch.setattr(
        integration,
        "_is_known_rendering_engine_failure",
        lambda exc: True,
    )

    context = integration._load_metadata_preview_with_safe_rendering(
        RequestFactory().get("/webclient/metadata_preview/"),
        "well",
        4,
        conn=SimpleNamespace(getMaxPlaneSize=lambda: (32, 32)),
        share_id=9,
    )
    assert context["share"] == "share-9"
    assert context["manager"] is manager
    assert context["tiledImage"] is True

    monkeypatch.setattr(
        integration,
        "_is_known_rendering_engine_failure",
        lambda exc: False,
    )
    with pytest.raises(RuntimeError, match="renderer busy"):
        integration._load_metadata_preview_with_safe_rendering(
            RequestFactory().get("/webclient/metadata_preview/"),
            "image",
            4,
            conn=SimpleNamespace(getMaxPlaneSize=lambda: (32, 32)),
        )


def test_region_helpers_cover_remaining_error_paths(monkeypatch):
    from omeroweb.webgateway import views as webgateway_views

    class _RegularImage:
        def __init__(self, levels=2, jpeg_payload=b"jpeg"):
            self._re = SimpleNamespace(getResolutionLevels=lambda: levels)
            self._jpeg_payload = jpeg_payload

        def _prepareRenderingEngine(self):
            return None

        def renderJpegRegion(self, *args, **kwargs):
            return self._jpeg_payload

    monkeypatch.setattr(
        integration,
        "get_safe_image_tile_size",
        lambda image, conn=None: (32, 16),
    )

    request = RequestFactory().get(
        "/webgateway/render_image_region/7/0/0/",
        {"tile": "-1,0,0,2048,2048"},
    )
    request.session = {"connector": {"server_id": 1}}
    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda *args, **kwargs: (_RegularImage(levels=2), 0.9),
    )
    response = integration._render_regular_image_region_with_safe_tile_size(
        request,
        7,
        0,
        0,
        conn=SimpleNamespace(
            getConfigService=lambda: (_ for _ in ()).throw(RuntimeError("config"))
        ),
    )
    assert response.status_code == 400

    zero_level_request = RequestFactory().get(
        "/webgateway/render_image_region/7/0/0/",
        {"tile": "1,0,0"},
    )
    zero_level_request.session = {"connector": {"server_id": 1}}
    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda *args, **kwargs: (_RegularImage(levels=1), 0.9),
    )
    invalid_level = integration._render_regular_image_region_with_safe_tile_size(
        zero_level_request,
        7,
        0,
        0,
    )
    assert invalid_level.status_code == 400

    missing_args_request = RequestFactory().get(
        "/webgateway/render_image_region/7/0/0/"
    )
    missing_args_request.session = {"connector": {"server_id": 1}}
    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda *args, **kwargs: (_RegularImage(levels=2), 0.9),
    )
    missing_args = integration._render_regular_image_region_with_safe_tile_size(
        missing_args_request,
        7,
        0,
        0,
    )
    assert missing_args.status_code == 400

    region_request = RequestFactory().get(
        "/webgateway/render_image_region/7/0/0/",
        {"region": "1,2,3,4"},
    )
    region_request.session = {"connector": {"server_id": 1}}
    monkeypatch.setattr(
        webgateway_views,
        "_get_prepared_image",
        lambda *args, **kwargs: (_RegularImage(levels=2, jpeg_payload=None), 0.9),
    )
    with pytest.raises(Http404):
        integration._render_regular_image_region_with_safe_tile_size(
            region_request,
            7,
            0,
            0,
        )

    monkeypatch.setattr(integration, "load_store_backed_image_node", lambda image: None)
    assert (
        integration._store_backed_region_response(
            SimpleNamespace(id=7),
            RequestFactory().get("/webgateway/render_image_region/7/0/0/"),
            conn=None,
        ).status_code
        == 400
    )

    fake_node = SimpleNamespace()
    monkeypatch.setattr(
        integration,
        "load_store_backed_image_node",
        lambda image: fake_node,
    )
    monkeypatch.setattr(integration, "get_store_backed_level_count", lambda node: 2)
    monkeypatch.setattr(
        integration,
        "get_store_backed_tile_size",
        lambda node: {"width": 64, "height": 32},
    )
    monkeypatch.setattr(
        integration,
        "select_store_backed_viewer_level",
        lambda node, viewer_level: 1 - viewer_level,
    )
    monkeypatch.setattr(
        integration,
        "render_store_backed_region_pil_image",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        integration,
        "encode_store_backed_pil_image",
        lambda image, requested_format: (b"payload", "image/jpeg", "jpg"),
    )

    store_request = RequestFactory().get(
        "/webgateway/render_image_region/7/0/0/",
        {"tile": "0,1,2,2048,2048"},
    )
    response = integration._store_backed_region_response(
        SimpleNamespace(id=7),
        store_request,
        conn=SimpleNamespace(
            getConfigService=lambda: (_ for _ in ()).throw(RuntimeError("config"))
        ),
    )
    assert response.status_code == 200
    assert response.content == b"payload"

    malformed_tile = integration._store_backed_region_response(
        SimpleNamespace(id=7),
        RequestFactory().get(
            "/webgateway/render_image_region/7/0/0/",
            {"tile": "0,nope,2"},
        ),
        conn=None,
    )
    assert malformed_tile.status_code == 400


def test_marshal_regular_image_data_with_safe_tile_size_handles_engine_fallbacks(
    monkeypatch,
):
    monkeypatch.setattr(
        integration, "_store_backed_metadata", lambda image: {"imageName": image.name}
    )
    monkeypatch.setattr(
        integration, "get_safe_image_tile_size", lambda image, conn=None: (128, 64)
    )
    monkeypatch.setattr(
        integration, "channelMarshal", lambda channel: {"label": channel.getLabel()}
    )

    request = SimpleNamespace(
        session={
            "server_settings": {
                "viewer": {"initial_zoom_level": -1, "interpolate_pixels": False}
            }
        }
    )

    not_ready = integration._marshal_regular_image_data_with_safe_tile_size(
        _MarshalImage(prepare_result=False),
        request,
    )
    assert not_ready["meta"] == {"imageName": "demo.zarr"}
    assert "tiles" not in not_ready

    class _FakeConcurrencyException(Exception):
        def __init__(self, back_off):
            super().__init__("busy")
            self.backOff = back_off

    monkeypatch.setattr(
        integration.omero,
        "ConcurrencyException",
        _FakeConcurrencyException,
        raising=False,
    )
    concurrency = integration._marshal_regular_image_data_with_safe_tile_size(
        _MarshalImage(prepare_exception=_FakeConcurrencyException(12)),
        request,
    )
    assert concurrency == {"ConcurrencyException": {"backOff": 12}}

    error_payload = integration._marshal_regular_image_data_with_safe_tile_size(
        _MarshalImage(prepare_exception=RuntimeError("renderer exploded")),
        request,
    )
    assert error_payload["Exception"] == "renderer exploded"

    payload = integration._marshal_regular_image_data_with_safe_tile_size(
        _MarshalImage(),
        request,
    )
    assert payload["tiles"] is True
    assert payload["tile_size"] == {"width": 128, "height": 64}
    assert payload["levels"] == 2
    assert payload["resolutions"][1] == {"sizeX": 512, "sizeY": 256}
    assert payload["zoomLevelScaling"][1] == 0.5
    assert payload["init_zoom"] == 1
    assert payload["nominalMagnification"] == 40
    assert payload["pixel_size"] == {"x": 0.5, "y": 0.75, "z": 1.25}
    assert payload["pixel_range"] == (0, 0)
    assert payload["channels"] == ()
    assert payload["split_channel"] == ()
    assert payload["rdefs"] == {
        "model": "color",
        "projection": "normal",
        "defaultZ": 0,
        "defaultT": 0,
        "invertAxis": False,
    }
    assert integration._select_marshaled_key(payload, "tile_size.width") == 128
    assert integration._select_marshaled_key(payload, "tile_size.missing") is None
