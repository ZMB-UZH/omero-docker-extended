import json
import os
import warnings
from pathlib import Path
from types import SimpleNamespace

import django
import numpy as np
import pytest
import requests
from django.http import Http404
from django.http import HttpResponseRedirect
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

from omero_web_zarr import views


class _FakeLength:
    def __init__(self, value, symbol):
        self._value = value
        self._symbol = symbol

    def getValue(self):
        return self._value

    def getSymbol(self):
        return self._symbol

    def getUnit(self):
        return self._symbol


class _FakePixelsType:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _FakePrimaryPixels:
    def __init__(self, pixel_type, tile_value=7):
        self._pixel_type = pixel_type
        self._tile_value = tile_value

    def getPixelsType(self):
        return _FakePixelsType(self._pixel_type)

    def getTile(self, _z, _c, _t, tile):
        _x, _y, width, height = tile
        dtype = views.PIXEL_TYPES[self._pixel_type]
        return np.full((height, width), self._tile_value, dtype=dtype)


class _FakeChannel:
    def __init__(self, label="Channel-1"):
        self.label = label


class _FakeResolutionDescription:
    def __init__(self, size_x, size_y):
        self.sizeX = size_x
        self.sizeY = size_y


class _FakeResolutionEngine:
    def __init__(self, descriptions, default_z=0, default_t=0):
        self._descriptions = descriptions
        self._default_z = default_z
        self._default_t = default_t

    def getResolutionDescriptions(self):
        return self._descriptions

    def getDefaultZ(self):
        return self._default_z

    def getDefaultT(self):
        return self._default_t


class _FakeRawPixelsStore:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.closed = False

    def setPixelsId(self, pixels_id, _bypass):
        self.calls.append(("setPixelsId", pixels_id))

    def setResolutionLevel(self, level):
        self.calls.append(("setResolutionLevel", level))

    def getTile(self, z, c, t, x, y, width, height):
        self.calls.append(("getTile", z, c, t, x, y, width, height))
        return self.payload[: width * height]

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, image):
        self._image = image

    def getObject(self, object_type, iid):
        assert object_type == "Image"
        assert iid == self._image.id
        return self._image


class _FakeImage:
    def __init__(
        self,
        *,
        image_id=1,
        name="demo",
        size_t=1,
        size_c=1,
        size_z=1,
        size_y=4,
        size_x=6,
        pyramid=False,
        resolution_descriptions=None,
        color=False,
        pixel_sizes=None,
        primary_pixels=None,
        conn=None,
        lsid=None,
    ):
        self.id = image_id
        self._name = name
        self._sizes = {
            "T": size_t,
            "C": size_c,
            "Z": size_z,
            "Y": size_y,
            "X": size_x,
        }
        self._pyramid = pyramid
        self._re = _FakeResolutionEngine(
            resolution_descriptions or [_FakeResolutionDescription(size_x, size_y)],
            default_z=2,
            default_t=1,
        )
        pixel_type = next(iter(views.PIXEL_TYPES))
        self._primary_pixels = primary_pixels or _FakePrimaryPixels(pixel_type)
        self._channels = [_FakeChannel("DNA")]
        self._color = color
        self._pixel_sizes = pixel_sizes or {}
        self._conn = conn
        self._details = SimpleNamespace(
            externalInfo=SimpleNamespace(lsid=SimpleNamespace(val=lsid))
        )

    def getDetails(self):
        return self._details

    def getName(self):
        return self._name

    def getSizeT(self):
        return self._sizes["T"]

    def getSizeC(self):
        return self._sizes["C"]

    def getSizeZ(self):
        return self._sizes["Z"]

    def getSizeY(self):
        return self._sizes["Y"]

    def getSizeX(self):
        return self._sizes["X"]

    def requiresPixelsPyramid(self):
        return self._pyramid

    def getZoomLevelScaling(self):
        return [1.0] * len(self._re.getResolutionDescriptions())

    def getChannels(self):
        return self._channels

    def isGreyscaleRenderingModel(self):
        return not self._color

    def getPrimaryPixels(self):
        return self._primary_pixels

    def getPixelsId(self):
        return 17

    def getPixelSizeX(self, units=True):
        return self._pixel_sizes.get("x")

    def getPixelSizeY(self, units=True):
        return self._pixel_sizes.get("y")

    def getPixelSizeZ(self, units=True):
        return self._pixel_sizes.get("z")


class _FakeChunkWriter:
    def __init__(self, root):
        self.root = Path(root)

    def __setitem__(self, _key, value):
        (self.root / "0.0").write_bytes(value.tobytes())


def test_index_and_image_zgroup_return_non_store_defaults(monkeypatch):
    def fake_reverse(name, kwargs=None):
        if name == "omero_web_zarr_index":
            return "/zarr/"
        if name == "zarr_app":
            return f"/zarr/{kwargs['app']}/"
        raise AssertionError(name)

    monkeypatch.setattr(views, "reverse", fake_reverse)

    response = views.index.__wrapped__(RequestFactory().get("/zarr/"))
    zgroup = views.image_zgroup(RequestFactory().get("/zarr/v0.4/image/1.zarr/.zgroup"))

    assert response.status_code == 200
    assert "/zarr/v0.4/image/[IMAGE_ID].zarr" in response.content.decode("utf-8")
    assert json.loads(zgroup.content) == {"zarr_format": 2}


def test_image_zattrs_builds_non_store_multiscales_for_pyramids(monkeypatch):
    image = _FakeImage(
        image_id=21,
        name="pyramid-image",
        size_t=2,
        size_z=3,
        size_y=8,
        size_x=10,
        pyramid=True,
        resolution_descriptions=[
            _FakeResolutionDescription(10, 8),
            _FakeResolutionDescription(5, 4),
        ],
        pixel_sizes={
            "x": _FakeLength(0.2, "um"),
            "y": _FakeLength(0.2, "um"),
            "z": _FakeLength(1.5, "um"),
        },
    )
    monkeypatch.setattr(views, "_store_backed_json_response", lambda *_args: None)
    monkeypatch.setattr(
        views, "channelMarshal", lambda channel: {"label": channel.label}
    )

    response = views.image_zattrs.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/21.zarr/.zattrs"),
        21,
        "0.4",
        conn=_FakeConn(image),
    )

    payload = json.loads(response.content)
    datasets = payload["multiscales"][0]["datasets"]
    axes = payload["multiscales"][0]["axes"]
    assert [dataset["path"] for dataset in datasets] == ["0", "1"]
    assert datasets[1]["coordinateTransformations"] == [
        {"type": "scale", "scale": [1.0, 1.0, 2.0, 2.0]}
    ]
    assert [axis["name"] for axis in axes] == ["t", "z", "y", "x"]
    assert payload["omero"]["channels"] == [{"label": "DNA"}]
    assert payload["omero"]["rdefs"] == {
        "defaultT": 1,
        "defaultZ": 2,
        "model": "greyscale",
    }


def test_image_zattrs_v03_omits_transformations_and_rejects_unknown_version(
    monkeypatch,
):
    image = _FakeImage(image_id=22, size_z=2, size_y=6, size_x=8)
    monkeypatch.setattr(views, "_store_backed_json_response", lambda *_args: None)
    monkeypatch.setattr(
        views, "channelMarshal", lambda channel: {"label": channel.label}
    )
    conn = _FakeConn(image)

    response = views.image_zattrs.__wrapped__(
        RequestFactory().get("/zarr/v0.3/image/22.zarr/.zattrs"),
        22,
        "0.3",
        conn=conn,
    )

    payload = json.loads(response.content)
    assert payload["multiscales"][0]["datasets"] == [{"path": "0"}]
    assert payload["multiscales"][0]["axes"] == ["z", "y", "x"]
    with pytest.raises(Http404):
        views.image_zattrs.__wrapped__(
            RequestFactory().get("/zarr/v0.5/image/22.zarr/.zattrs"),
            22,
            "0.5",
            conn=conn,
        )


def test_get_image_shape_and_chunk_shape_cover_pyramid_levels(monkeypatch):
    image = _FakeImage(
        pyramid=True,
        size_y=9,
        size_x=12,
        resolution_descriptions=[
            _FakeResolutionDescription(12, 9),
            _FakeResolutionDescription(6, 5),
        ],
    )
    monkeypatch.setattr(views, "get_safe_image_tile_size", lambda image: (4, 3))

    assert views.get_image_shape(image, 1) == [5, 6]
    assert views.get_chunk_shape(image) == [3, 4]
    with pytest.raises(Exception, match="higher than 2 levels"):
        views.get_image_shape(image, 2)


def test_image_zarray_returns_dimension_separator_for_runtime_generated_metadata(
    monkeypatch,
):
    image = _FakeImage(image_id=31, size_y=5, size_x=7)
    monkeypatch.setattr(views, "_store_backed_json_response", lambda *_args: None)

    response = views.image_zarray.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/31.zarr/0/.zarray"),
        31,
        0,
        conn=_FakeConn(image),
    )

    payload = json.loads(response.content)
    assert payload["shape"] == [5, 7]
    assert payload["chunks"] == [5, 7]
    assert payload["dimension_separator"] == "/"


def test_image_chunk_pads_edge_tiles_for_non_store_pyramids(monkeypatch):
    image = _FakeImage(
        image_id=41,
        size_y=3,
        size_x=3,
        pyramid=True,
        resolution_descriptions=[_FakeResolutionDescription(3, 3)],
        primary_pixels=_FakePrimaryPixels(next(iter(views.PIXEL_TYPES)), tile_value=9),
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(views, "get_safe_image_tile_size", lambda image: (2, 2))
    monkeypatch.setattr(
        views,
        "open_compat_array",
        lambda path, **_kwargs: _FakeChunkWriter(path),
    )

    response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/41.zarr/0/1/1"),
        41,
        0,
        "1/1",
        conn=_FakeConn(image),
    )

    assert response.status_code == 200
    assert response["Content-Disposition"] == "attachment; filename=0.0.0.1.1"
    assert len(response.content) == 4


def test_image_chunk_uses_raw_pixels_store_for_lower_pyramid_levels(monkeypatch):
    raw_tile = np.array([[1, 2], [3, 4]], dtype=np.uint8).tobytes()
    raw_store = _FakeRawPixelsStore(raw_tile)
    runtime_conn = SimpleNamespace(
        c=SimpleNamespace(sf=SimpleNamespace(createRawPixelsStore=lambda: raw_store))
    )
    image = _FakeImage(
        image_id=42,
        size_y=4,
        size_x=4,
        pyramid=True,
        resolution_descriptions=[
            _FakeResolutionDescription(4, 4),
            _FakeResolutionDescription(2, 2),
        ],
        conn=runtime_conn,
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(views, "get_safe_image_tile_size", lambda image: (2, 2))
    monkeypatch.setattr(
        views,
        "open_compat_array",
        lambda path, **_kwargs: _FakeChunkWriter(path),
    )

    response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/42.zarr/1/0/0"),
        42,
        1,
        "0/0",
        conn=_FakeConn(image),
    )

    assert response.status_code == 200
    assert ("setPixelsId", 17) in raw_store.calls
    assert ("setResolutionLevel", 0) in raw_store.calls
    assert raw_store.closed is True


def test_image_chunk_rejects_wrong_dimension_count(monkeypatch):
    image = _FakeImage(image_id=43, size_y=4, size_x=4)
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)

    with pytest.raises(Http404, match="incorrect number of dimensions"):
        views.image_chunk.__wrapped__(
            RequestFactory().get("/zarr/v0.4/image/43.zarr/0/0/0/0"),
            43,
            0,
            "0/0/0",
            conn=_FakeConn(image),
        )


def test_image_store_path_and_preview_cover_store_and_non_store_paths(
    monkeypatch, tmp_path
):
    image = _FakeImage(image_id=51, name="preview.zarr", lsid=str(tmp_path))
    conn = _FakeConn(image)

    def fake_reverse(name, args=None, kwargs=None):
        if name == "load_metadata_preview":
            return f"/preview/{kwargs['c_type']}/{kwargs['c_id']}/"
        if name == "omero_web_zarr_index":
            return "/zarr/"
        if name == "render_thumbnail":
            return f"/thumb/{args[0]}/"
        if name == "zarr_app":
            return f"/zarr/{kwargs['app']}/"
        raise AssertionError(name)

    monkeypatch.setattr(views, "reverse", fake_reverse)
    monkeypatch.setattr(
        views,
        "resolve_image_backing_zarr_store",
        lambda image: tmp_path if image.id == 51 else None,
    )
    monkeypatch.setattr(
        views,
        "render",
        lambda request, template, context: {
            "template": template,
            "context": context,
        },
    )
    monkeypatch.setattr(views, "_store_backed_response", lambda *_args: None)

    with pytest.raises(Http404):
        views.image_store_path.__wrapped__(
            RequestFactory().get("/zarr/v0.4/image/51.zarr/missing"),
            51,
            "0.4",
            "missing",
            conn=conn,
        )

    regular_image = _FakeImage(image_id=52, name="regular")
    redirect_response = views.image_preview.__wrapped__(
        RequestFactory().get("/zarr/preview/52/"),
        52,
        conn=_FakeConn(regular_image),
    )
    rendered = views.image_preview.__wrapped__(
        RequestFactory().get("/zarr/preview/51/"),
        51,
        conn=conn,
    )

    assert redirect_response.status_code == 302
    assert redirect_response["Location"] == "/preview/image/52/"
    assert rendered["template"] == "omero_web_zarr/image_preview.html"
    assert rendered["context"]["image_name"] == "preview.zarr"
    assert (
        "source=/zarr/v0.4/preview/image/51.zarr" in rendered["context"]["vizarr_url"]
    )


def test_store_backed_ome_tiff_helpers_cover_reordering_planes_and_metadata(
    monkeypatch,
):
    node = SimpleNamespace(
        data=[np.arange(6, dtype=np.uint16).reshape(2, 3, 1)],
        metadata={"channel_names": ["DNA"]},
    )
    monkeypatch.setattr(
        views,
        "get_store_backed_axis_names",
        lambda node, level=0: ["y", "x", "c"],
    )

    image = _FakeImage(
        image_id=61,
        name="axes-test.zarr",
        pixel_sizes={
            "x": _FakeLength(0.2, "um"),
            "y": _FakeLength(0.3, "um"),
            "z": _FakeLength(1.0, "um"),
        },
    )

    array, axes = views._store_backed_ome_axes_and_array(node)
    planes = list(views._iter_store_backed_ome_tiff_planes(array))
    metadata = views._store_backed_ome_tiff_metadata(image, node, axes)

    assert array.shape == (1, 2, 3)
    assert axes == "CYX"
    assert len(planes) == 1
    assert planes[0].shape == (2, 3)
    assert metadata["PhysicalSizeX"] == 0.2
    assert metadata["PhysicalSizeYUnit"] == "um"
    assert metadata["Channel"] == {"Name": ["DNA"]}

    monkeypatch.setattr(
        views,
        "get_store_backed_axis_names",
        lambda node, level=0: ["x", "u"],
    )
    with pytest.raises(Http404, match="image axes only"):
        views._store_backed_ome_axes_and_array(node)


def test_app_helpers_reject_invalid_asset_paths_and_surface_fetch_failures(
    monkeypatch,
):
    with pytest.raises(Http404):
        views._sanitize_app_asset_path("https://example.com/app.js")
    with pytest.raises(Http404):
        views._sanitize_app_asset_path("../escape.js")

    monkeypatch.setattr(
        views,
        "_fetch_remote_app_shell",
        lambda *_args: (_ for _ in ()).throw(requests.RequestException("boom")),
    )

    response = views.apps(RequestFactory().get("/zarr/vizarr/"), "vizarr", "")
    redirect = views.apps(
        RequestFactory().get("/zarr/validator/assets/app.js"),
        "validator",
        "assets/app.js",
    )

    assert response.status_code == 502
    assert isinstance(redirect, HttpResponseRedirect)
    assert (
        redirect["Location"] == "https://ome.github.io/ome-ngff-validator/assets/app.js"
    )
