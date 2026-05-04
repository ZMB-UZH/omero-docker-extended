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
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.test import RequestFactory

from iter_test_helpers import next_or_fail

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


def _response_text(response) -> str:
    """Response text.

    Inputs: `response`. Output: `str`.
    """
    return b"".join(response.streaming_content).decode("utf-8")


class _FakeLength:
    """Test double for fake length."""

    def __init__(self, value, symbol):
        """Initialize the instance.

        Inputs: `value`, `symbol`. Output: None.
        """
        self._value = value
        self._symbol = symbol

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value

    def getSymbol(self):
        """Return Symbol.

        Inputs: none. Output: `self._symbol`.
        """
        return self._symbol

    def getUnit(self):
        """Return Unit.

        Inputs: none. Output: `self._symbol`.
        """
        return self._symbol


class _FakePixelsType:
    """Test double for fake pixels type."""

    def __init__(self, value):
        """Initialize the instance.

        Inputs: `value`. Output: None.
        """
        self._value = value

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value


class _FakePrimaryPixels:
    """Test double for fake primary pixels."""

    def __init__(self, pixel_type, tile_value=7):
        """Initialize the instance.

        Inputs: `pixel_type`, `tile_value`. Output: None.
        """
        self._pixel_type = pixel_type
        self._tile_value = tile_value

    def getPixelsType(self):
        """Return Pixels Type.

        Inputs: none. Output: `_FakePixelsType` result.
        """
        return _FakePixelsType(self._pixel_type)

    def getTile(self, _z, _c, _t, tile):
        """Return Tile.

        Inputs: `_z`, `_c`, `_t`, `tile`. Output: `np.full` result.
        """
        _x, _y, width, height = tile
        dtype = views.PIXEL_TYPES[self._pixel_type]
        return np.full((height, width), self._tile_value, dtype=dtype)


class _FakeChannel:
    """Test double for fake channel."""

    def __init__(self, label="Channel-1"):
        """Initialize the instance.

        Inputs: `label`. Output: None.
        """
        self.label = label


class _FakeResolutionDescription:
    """Test double for fake resolution description."""

    def __init__(self, size_x, size_y):
        """Initialize the instance.

        Inputs: `size_x`, `size_y`. Output: None.
        """
        self.sizeX = size_x
        self.sizeY = size_y


class _FakeResolutionEngine:
    """Test double for fake resolution engine."""

    def __init__(self, descriptions, default_z=0, default_t=0):
        """Initialize the instance.

        Inputs: `descriptions`, `default_z`, `default_t`. Output: None.
        """
        self._descriptions = descriptions
        self._default_z = default_z
        self._default_t = default_t

    def getResolutionDescriptions(self):
        """Return Resolution Descriptions.

        Inputs: none. Output: `self._descriptions`.
        """
        return self._descriptions

    def getDefaultZ(self):
        """Return Default Z.

        Inputs: none. Output: `self._default_z`.
        """
        return self._default_z

    def getDefaultT(self):
        """Return Default T.

        Inputs: none. Output: `self._default_t`.
        """
        return self._default_t


class _FakeRawPixelsStore:
    """Test double for fake raw pixels store."""

    def __init__(self, payload):
        """Initialize the instance.

        Inputs: `payload`. Output: None.
        """
        self.payload = payload
        self.calls = []
        self.closed = False

    def setPixelsId(self, pixels_id, _bypass):
        """Set Pixels ID.

        Inputs: `pixels_id`, `_bypass`. Output: None.
        """
        self.calls.append(("setPixelsId", pixels_id))

    def setResolutionLevel(self, level):
        """Set Resolution Level.

        Inputs: `level`. Output: None.
        """
        self.calls.append(("setResolutionLevel", level))

    def getTile(self, z, c, t, x, y, width, height):
        """Return Tile.

        Inputs: `z`, `c`, `t`, `x`, `y`, `width`, `height`. Output: computed value.
        """
        self.calls.append(("getTile", z, c, t, x, y, width, height))
        return self.payload[: width * height]

    def close(self):
        """Close the resource.

        Inputs: none. Output: None.
        """
        self.closed = True


class _FakeConn:
    """Test double for fake conn."""

    def __init__(self, image):
        """Initialize the instance.

        Inputs: `image`. Output: None.
        """
        self._image = image

    def getObject(self, object_type, iid):
        """Return Object.

        Inputs: `object_type`, `iid`. Output: `self._image`.
        """
        assert object_type == "Image"
        assert iid == self._image.id
        return self._image


class _FakeImage:
    """Test double for fake image."""

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
        """Initialize the instance.

        Inputs: `image_id`, `name`, `size_t`, `size_c`, `size_z`, `size_y`, `size_x`,
        `pyramid`, `resolution_descriptions`, `color`, `pixel_sizes`, `primary_pixels`,
        `conn`, `lsid`. Output: None.
        """
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
        pixel_type = next_or_fail(iter(views.PIXEL_TYPES), "pixel type registry")
        self._primary_pixels = primary_pixels or _FakePrimaryPixels(pixel_type)
        self._channels = [_FakeChannel("DNA")]
        self._color = color
        self._pixel_sizes = pixel_sizes or {}
        self._conn = conn
        self._details = SimpleNamespace(
            externalInfo=SimpleNamespace(lsid=SimpleNamespace(val=lsid))
        )

    def getDetails(self):
        """Return Details.

        Inputs: none. Output: `self._details`.
        """
        return self._details

    def getName(self):
        """Return the fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def getSizeT(self):
        """Return Size T.

        Inputs: none. Output: `self._sizes['T']`.
        """
        return self._sizes["T"]

    def getSizeC(self):
        """Return Size C.

        Inputs: none. Output: `self._sizes['C']`.
        """
        return self._sizes["C"]

    def getSizeZ(self):
        """Return Size Z.

        Inputs: none. Output: `self._sizes['Z']`.
        """
        return self._sizes["Z"]

    def getSizeY(self):
        """Return Size Y.

        Inputs: none. Output: `self._sizes['Y']`.
        """
        return self._sizes["Y"]

    def getSizeX(self):
        """Return Size X.

        Inputs: none. Output: `self._sizes['X']`.
        """
        return self._sizes["X"]

    def requiresPixelsPyramid(self):
        """Requires pixels pyramid.

        Inputs: none. Output: `self._pyramid`.
        """
        return self._pyramid

    def getZoomLevelScaling(self):
        """Return Zoom Level Scaling.

        Inputs: none. Output: computed value.
        """
        return [1.0] * len(self._re.getResolutionDescriptions())

    def getChannels(self):
        """Return Channels.

        Inputs: none. Output: `self._channels`.
        """
        return self._channels

    def isGreyscaleRenderingModel(self):
        """Return whether Greyscale Rendering Model.

        Inputs: none. Output: bool.
        """
        return not self._color

    def getPrimaryPixels(self):
        """Return Primary Pixels.

        Inputs: none. Output: `self._primary_pixels`.
        """
        return self._primary_pixels

    @staticmethod
    def getPixelsId():
        """Return Pixels ID.

        Inputs: none. Output: 17.
        """
        return 17

    def getPixelSizeX(self, units=True):
        """Return Pixel Size X.

        Inputs: `units`. Output: `self._pixel_sizes.get` result.
        """
        return self._pixel_sizes.get("x")

    def getPixelSizeY(self, units=True):
        """Return Pixel Size Y.

        Inputs: `units`. Output: `self._pixel_sizes.get` result.
        """
        return self._pixel_sizes.get("y")

    def getPixelSizeZ(self, units=True):
        """Return Pixel Size Z.

        Inputs: `units`. Output: `self._pixel_sizes.get` result.
        """
        return self._pixel_sizes.get("z")


class _FakeChunkWriter:
    """Test double for fake chunk writer."""

    def __init__(self, root):
        """Initialize the instance.

        Inputs: `root`. Output: None.
        """
        self.root = Path(root)

    def __setitem__(self, _key, value):
        """The item for the requested key.

        Inputs: `_key`, `value`. Output: None.
        """
        (self.root / "0.0").write_bytes(value.tobytes())


def test_index_and_image_zgroup_return_non_store_defaults(monkeypatch):
    """Verify index and image zgroup return non store defaults.

    Inputs: `monkeypatch`. Output: computed value. Raises on invalid or unavailable
    state.

    state.
    """

    def fake_reverse(name, kwargs=None):
        """Fake reverse.

        Inputs: `name`, `kwargs`. Output: computed value. Raises on invalid or
        unavailable state.

        unavailable state.
        """
        if name == "omero_web_zarr_index":
            return "/zarr/"
        if name == "zarr_app":
            return f"/zarr/{kwargs['app']}/"
        raise AssertionError(name)

    monkeypatch.setattr(views, "reverse", fake_reverse)

    response = views.index.__wrapped__(RequestFactory().get("/zarr/"))
    zgroup = views.image_zgroup(RequestFactory().get("/zarr/v0.4/image/1.zarr/.zgroup"))

    assert response.status_code == 200
    assert "/zarr/v0.4/image/[IMAGE_ID].zarr" in _response_text(response)
    assert json.loads(zgroup.content) == {"zarr_format": 2}


def test_image_zattrs_builds_non_store_multiscales_for_pyramids(monkeypatch):
    """Verify image zattrs builds non store multiscales for pyramids.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify image zattrs v03 omits transformations and rejects unknown version.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify get image shape and chunk shape cover pyramid levels.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify image zarray returns dimension separator for runtime generated metadata.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify image chunk pads edge tiles for non store pyramids.

    Inputs: `monkeypatch`. Output: None.
    """
    image = _FakeImage(
        image_id=41,
        size_y=3,
        size_x=3,
        pyramid=True,
        resolution_descriptions=[_FakeResolutionDescription(3, 3)],
        primary_pixels=_FakePrimaryPixels(
            next_or_fail(iter(views.PIXEL_TYPES), "pixel type registry"),
            tile_value=9,
        ),
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
    assert len(b"".join(response.streaming_content)) == 4


def test_image_chunk_uses_raw_pixels_store_for_lower_pyramid_levels(monkeypatch):
    """Verify image chunk uses raw pixels store for lower pyramid levels.

    Inputs: `monkeypatch`. Output: None.
    """
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


def test_image_chunk_builds_runtime_chunk_indices_for_tcz_axes(monkeypatch):
    """Verify image chunk builds runtime chunk indices for tcz axes.

    Inputs: `monkeypatch`. Output: None.
    """

    class _RichFakeChunkWriter:
        """Test double for rich fake chunk writer."""

        def __init__(self, root):
            """Initialize the instance.

            Inputs: `root`. Output: None.
            """
            self.root = Path(root)

        def __setitem__(self, _key, value):
            """The item for the requested key.

            Inputs: `_key`, `value`. Output: None.
            """
            (self.root / "0.0.0.0.0").write_bytes(value.tobytes())

    image = _FakeImage(
        image_id=44,
        size_z=1,
        size_c=1,
        size_t=1,
        size_y=2,
        size_x=2,
        primary_pixels=_FakePrimaryPixels(
            next_or_fail(iter(views.PIXEL_TYPES), "pixel type registry"),
            tile_value=5,
        ),
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(
        views,
        "marshal_axes_v3",
        lambda current_image: ["t", "c", "z", "y", "x"],
    )
    monkeypatch.setattr(views, "get_image_shape", lambda image, level: (1, 1, 1, 2, 2))
    monkeypatch.setattr(views, "get_chunk_shape", lambda image: (1, 1, 1, 2, 2))
    monkeypatch.setattr(
        views,
        "open_compat_array",
        lambda path, **_kwargs: _RichFakeChunkWriter(path),
    )

    response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/44.zarr/0/0/0/0/0/0"),
        44,
        0,
        "0/0/0/0/0",
        conn=_FakeConn(image),
    )

    assert response.status_code == 200
    assert response["Content-Disposition"] == "attachment; filename=0.0.0.0.0"


def test_image_chunk_rejects_wrong_dimension_count(monkeypatch):
    """Verify image chunk rejects wrong dimension count.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify image store path and preview cover store and non store paths.

    Inputs: `monkeypatch`, `tmp_path`. Output: computed value. Raises on invalid or
    unavailable state.

    unavailable state.
    """
    image = _FakeImage(image_id=51, name="preview.zarr", lsid=str(tmp_path))
    conn = _FakeConn(image)

    def fake_reverse(name, args=None, kwargs=None):
        """Fake reverse.

        Inputs: `name`, `args`, `kwargs`. Output: computed value. Raises on invalid or
        unavailable state.

        unavailable state.
        """
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
    """Verify store backed ome tiff helpers cover reordering planes and metadata.

    Inputs: `monkeypatch`. Output: None.
    """
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
    """Verify app helpers reject invalid asset paths and surface fetch failures.

    Inputs: `monkeypatch`. Output: None.
    """
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


def test_runtime_view_helpers_cover_store_shortcuts_and_single_plane_iterators(
    monkeypatch,
):
    """Verify runtime view helpers cover store shortcuts and single plane iterators.

    Inputs: `monkeypatch`. Output: None.
    """
    multi_dim_image = _FakeImage(image_id=71, size_t=2, size_z=3, size_y=4, size_x=5)
    assert views.get_chunk_shape(multi_dim_image) == [1, 1, 4, 5]

    image = _FakeImage(image_id=72, size_y=4, size_x=5)
    store_json_response = HttpResponse(
        '{"store": true}', content_type="application/json"
    )
    store_chunk_response = HttpResponse(
        b"store-chunk",
        content_type="application/octet-stream",
    )
    store_path_response = HttpResponse('{"ok": 1}', content_type="application/json")
    monkeypatch.setattr(
        views, "_store_backed_json_response", lambda *_args: store_json_response
    )
    monkeypatch.setattr(
        views, "_store_backed_chunk_response", lambda *_args: store_chunk_response
    )
    monkeypatch.setattr(
        views, "_store_backed_response", lambda *_args: store_path_response
    )

    zarray_response = views.image_zarray.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/72.zarr/0/.zarray"),
        72,
        0,
        conn=_FakeConn(image),
    )
    chunk_response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/72.zarr/0/0/0"),
        72,
        0,
        "0/0",
        conn=_FakeConn(image),
    )
    store_response = views.image_store_path.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/72.zarr/0/.zarray"),
        72,
        "0.4",
        "0/.zarray",
        conn=_FakeConn(image),
    )

    assert zarray_response is store_json_response
    assert chunk_response is store_chunk_response
    assert store_response is store_path_response

    planes = list(views._iter_store_backed_ome_tiff_planes(np.arange(6).reshape(2, 3)))
    assert len(planes) == 1
    assert planes[0].shape == (2, 3)
