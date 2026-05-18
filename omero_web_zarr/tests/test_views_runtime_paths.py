import json
import os
import warnings
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
    """Return the response text.

    Inputs: `response` response object. Output: `str`.
    """
    return b"".join(response.streaming_content).decode("utf-8")


def _response_bytes(response) -> bytes:
    """Return the streaming response bytes.

    Inputs: `response` response object. Output: bytes.
    """
    return b"".join(response.streaming_content)


def test_lower_pyramid_plane_requires_image_connection(monkeypatch) -> None:
    """Verify lower pyramid plane requires image connection.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in lower pyramid plane requires image connection.
    """
    monkeypatch.setattr(views, "get_image_connection", lambda image: None)

    with pytest.raises(Http404, match="image connection unavailable"):
        views._read_lower_pyramid_plane(
            SimpleNamespace(),
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            np.uint8,
        )


class _FakeLength:
    """Test double for fake length."""

    def __init__(self, value, symbol):
        """Create `_FakeLength` with `value` and `symbol`.

        Inputs: `value`, `symbol`. Output: None.
        """
        self._value = value
        self._symbol = symbol

    def getValue(self):
        """Return `_FakeLength`'s fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value

    def getSymbol(self):
        """Return the symbol for `_FakeLength`.

        Inputs: none. Output: `_symbol`.
        """
        return self._symbol

    def getUnit(self):
        """Return the unit for `_FakeLength`.

        Inputs: none. Output: `_symbol`.
        """
        return self._symbol


class _FakePixelsType:
    """Test double for fake pixels type."""

    def __init__(self, value):
        """Create `_FakePixelsType` with `value`.

        Inputs: `value`. Output: None.
        """
        self._value = value

    def getValue(self):
        """Return `_FakePixelsType`'s fake OMERO value.

        Inputs: none. Output: `self._value`.
        """
        return self._value


class _FakePrimaryPixels:
    """Test double for fake primary pixels."""

    def __init__(self, pixel_type, tile_value=7):
        """Create `_FakePrimaryPixels` with `pixel_type` and `tile_value`.

        Inputs: `pixel_type`, `tile_value`. Output: None.
        """
        self._pixel_type = pixel_type
        self._tile_value = tile_value

    def getPixelsType(self):
        """Return the fake pixels type value used by this test double.

        Inputs: none. Output: `_FakePixelsType` result.
        """
        return _FakePixelsType(self._pixel_type)

    def getTile(self, _z, _c, _t, tile):
        """Return the tile for `_FakePrimaryPixels`.

        Inputs: `_z`, `_c`, `_t`, `tile`. Output: `full` result.
        """
        _x, _y, width, height = tile
        dtype = views.PIXEL_TYPES[self._pixel_type]
        return np.full((height, width), self._tile_value, dtype=dtype)


class _PatternPrimaryPixels(_FakePrimaryPixels):
    """Test double for deterministic tile payloads."""

    def __init__(self, pixel_type, array):
        """Create `_PatternPrimaryPixels` with `pixel_type` and `array`.

        Inputs: `pixel_type`, `array`. Output: None.
        """
        super().__init__(pixel_type)
        self._array = np.asarray(array, dtype=views.PIXEL_TYPES[pixel_type])
        self.calls = []

    def getTile(self, _z, _c, _t, tile):
        """Return a deterministic crop for `_PatternPrimaryPixels`.

        Inputs: `_z`, `_c`, `_t`, `tile`. Output: array crop.
        """
        x, y, width, height = tile
        self.calls.append((x, y, width, height))
        return self._array[y : y + height, x : x + width]


class _BytePrimaryPixels(_PatternPrimaryPixels):
    """Test double for byte-returning primary pixels."""

    def getTile(self, _z, _c, _t, tile):
        """Return deterministic raw bytes for `_BytePrimaryPixels`.

        Inputs: `_z`, `_c`, `_t`, `tile`. Output: bytes.
        """
        return super().getTile(_z, _c, _t, tile).tobytes(order="C")


class _FakeChannel:
    """Test double for fake channel."""

    def __init__(self, label="Channel-1"):
        """Create `_FakeChannel` with `label`.

        Inputs: `label`. Output: None.
        """
        self.label = label


class _FakeResolutionDescription:
    """Test double for fake resolution description."""

    def __init__(self, size_x, size_y):
        """Create `_FakeResolutionDescription` with `size_x` and `size_y`.

        Inputs: `size_x`, `size_y`. Output: None.
        """
        self.sizeX = size_x
        self.sizeY = size_y


class _FakeResolutionEngine:
    """Test double for fake resolution engine."""

    def __init__(self, descriptions, default_z=0, default_t=0):
        """Create `_FakeResolutionEngine` with `descriptions`, `default_z`, and `default_t`.

        Inputs: `descriptions`, `default_z`, `default_t`. Output: None.
        """
        self._descriptions = descriptions
        self._default_z = default_z
        self._default_t = default_t

    def getResolutionDescriptions(self):
        """Return the fake resolution descriptions value used by this test double.

        Inputs: none. Output: `self._descriptions`.
        """
        return self._descriptions

    def getDefaultZ(self):
        """Return the fake default z value used by this test double.

        Inputs: none. Output: `self._default_z`.
        """
        return self._default_z

    def getDefaultT(self):
        """Return the fake default t value used by this test double.

        Inputs: none. Output: `self._default_t`.
        """
        return self._default_t


class _FakeRawPixelsStore:
    """Test double for fake raw pixels store."""

    def __init__(self, payload):
        """Create `_FakeRawPixelsStore` with `payload`.

        Inputs: `payload`. Output: None.
        """
        self.payload = payload
        self.calls = []
        self.closed = False

    def setPixelsId(self, pixels_id, _bypass):
        """Set the pixels ID for `_FakeRawPixelsStore`.

        Inputs: `pixels_id`, `_bypass`. Output: None.
        """
        self.calls.append(("setPixelsId", pixels_id))

    def setResolutionLevel(self, level):
        """Set the resolution Level for `_FakeRawPixelsStore`.

        Inputs: `level`. Output: None.
        """
        self.calls.append(("setResolutionLevel", level))

    def getTile(self, z, c, t, x, y, width, height):
        """Return the tile for `_FakeRawPixelsStore`.

        Inputs: `z`, `c`, `t`, `x`, `y`, `width`, `height`. Output: get tile result.
        """
        self.calls.append(("getTile", z, c, t, x, y, width, height))
        return self.payload[: width * height]

    def close(self):
        """Close `_FakeRawPixelsStore`'s fake resource handle.

        Inputs: caller provides no extra arguments. Output: records the fake side effect.
        """
        self.closed = True


class _FakeConn:
    """Test double for fake conn."""

    def __init__(self, image):
        """Create `_FakeConn` with `image`.

        Inputs: `image`. Output: None.
        """
        self._image = image

    def getObject(self, object_type, iid):
        """Return the object for `_FakeConn`.

        Inputs: `object_type`, `iid`. Output: `_image`.
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
        """Create `_FakeImage` with its default state.

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
        """Return the details for `_FakeImage`.

        Inputs: none. Output: `_details`.
        """
        return self._details

    def getName(self):
        """Return `_FakeImage`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def getSizeT(self):
        """Return `_FakeImage`'s fake timepoint count.

        Inputs: none. Output: `self._sizes['T']`.
        """
        return self._sizes["T"]

    def getSizeC(self):
        """Return `_FakeImage`'s fake channel count.

        Inputs: none. Output: `self._sizes['C']`.
        """
        return self._sizes["C"]

    def getSizeZ(self):
        """Return `_FakeImage`'s fake SizeZ value.

        Inputs: none. Output: `self._sizes['Z']`.
        """
        return self._sizes["Z"]

    def getSizeY(self):
        """Return `_FakeImage`'s fake SizeY value.

        Inputs: none. Output: `self._sizes['Y']`.
        """
        return self._sizes["Y"]

    def getSizeX(self):
        """Return `_FakeImage`'s fake SizeX value.

        Inputs: none. Output: `self._sizes['X']`.
        """
        return self._sizes["X"]

    def requiresPixelsPyramid(self):
        """Return whether the fake image requires a pixels pyramid.

        Inputs: none. Output: `self._pyramid`.
        """
        return self._pyramid

    def getZoomLevelScaling(self):
        """Return the fake zoom level scaling value used by this test double.

        Inputs: none. Output: get zoom level scaling result.
        """
        return [1.0] * len(self._re.getResolutionDescriptions())

    def getChannels(self):
        """Return the channels for `_FakeImage`.

        Inputs: none. Output: `_channels`.
        """
        return self._channels

    def isGreyscaleRenderingModel(self):
        """Report the greyscale rendering model boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: bool.
        """
        return not self._color

    def getPrimaryPixels(self):
        """Return the fake primary pixels value used by this test double.

        Inputs: none. Output: `self._primary_pixels`.
        """
        return self._primary_pixels

    @staticmethod
    def getPixelsId():
        """Return the fake pixels ID value used by this test double.

        Inputs: none. Output: 17.
        """
        return 17

    def getPixelSizeX(self, units=True):
        """Return `_FakeImage`'s fake physical X size.

        Inputs: `units`. Output: `self._pixel_sizes.get` result.
        """
        return self._pixel_sizes.get("x")

    def getPixelSizeY(self, units=True):
        """Return `_FakeImage`'s fake physical Y size.

        Inputs: `units`. Output: `self._pixel_sizes.get` result.
        """
        return self._pixel_sizes.get("y")

    def getPixelSizeZ(self, units=True):
        """Return `_FakeImage`'s fake physical Z size.

        Inputs: `units`. Output: `self._pixel_sizes.get` result.
        """
        return self._pixel_sizes.get("z")


def test_index_and_image_zgroup_return_non_store_defaults(monkeypatch):
    """Verify index and image zgroup return non store defaults.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in index and image zgroup return non store defaults.
    AssertionError when validation or the called operation fails.
    """

    def fake_reverse(name, kwargs=None):
        """Simulate reverse so the surrounding test controls that dependency.

        Inputs: `name` name, `kwargs` keyword arguments. Output: `str`. Raises:
        AssertionError when validation or the called operation fails.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image zattrs builds non store multiscales for pyramids.
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


def test_image_zattrs_generates_runtime_overviews_for_non_pyramid_images(
    monkeypatch,
):
    """Verify image zattrs generates runtime overviews for non pyramid images.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in runtime
    overview metadata for ordinary OMERO-backed images.
    """
    image = _FakeImage(image_id=23, size_y=8, size_x=8)
    monkeypatch.setattr(views, "_store_backed_json_response", lambda *_args: None)
    monkeypatch.setattr(
        views, "channelMarshal", lambda channel: {"label": channel.label}
    )

    response = views.image_zattrs.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/23.zarr/.zattrs"),
        23,
        "0.4",
        conn=_FakeConn(image),
    )

    payload = json.loads(response.content)
    datasets = payload["multiscales"][0]["datasets"]
    assert [dataset["path"] for dataset in datasets] == ["0", "1", "2", "3"]
    assert views.get_image_shapes(image) == [[8, 8], [4, 4], [2, 2], [1, 1]]
    assert datasets[3]["coordinateTransformations"] == [
        {"type": "scale", "scale": [8.0, 8.0]}
    ]
    assert views.get_image_shapes(_FakeImage(image_id=24, size_y=1, size_x=2)) == [
        [1, 2],
        [1, 1],
    ]


def test_image_zattrs_v03_omits_transformations_and_rejects_unknown_version(
    monkeypatch,
):
    """Confirm image zattrs v03 omits transformations and rejects unknown version is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image zattrs v03 omits transformations and rejects unknown version.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get image shape and chunk shape cover pyramid levels.
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
    """Verify image zarray returns dimension separator for runtime generated metadata result shape.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image zarray returns dimension separator for runtime generated metadata.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image chunk pads edge tiles for non store pyramids.
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

    response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/41.zarr/0/1/1"),
        41,
        0,
        "1/1",
        conn=_FakeConn(image),
    )

    assert response.status_code == 200
    assert response["Content-Disposition"] == "attachment; filename=0.0.0.1.1"
    assert _response_bytes(response) == b"\x09\x00\x00\x00"


def test_image_chunk_uses_raw_pixels_store_for_lower_pyramid_levels(monkeypatch):
    """Verify image chunk uses raw pixels store for lower pyramid levels.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image chunk uses raw pixels store for lower pyramid levels.
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

    response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/42.zarr/1/0/0"),
        42,
        1,
        "0/0",
        conn=_FakeConn(image),
    )

    assert response.status_code == 200
    assert _response_bytes(response) == raw_tile
    assert ("setPixelsId", 17) in raw_store.calls
    assert ("setResolutionLevel", 0) in raw_store.calls
    assert raw_store.closed is True


def test_image_chunk_returns_declared_uncompressed_runtime_bytes(monkeypatch):
    """Verify image chunk returns declared uncompressed runtime bytes.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image chunk returns declared uncompressed runtime bytes.
    """
    pixel_type = next(
        key for key, dtype in views.PIXEL_TYPES.items() if dtype == np.uint16
    )
    pattern = np.array([[1, 257, 513], [1025, 2049, 4097]], dtype=np.uint16)
    image = _FakeImage(
        image_id=45,
        size_y=2,
        size_x=3,
        primary_pixels=_PatternPrimaryPixels(pixel_type, pattern),
    )
    monkeypatch.setattr(views, "_store_backed_json_response", lambda *_args: None)
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)

    zarray_response = views.image_zarray.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/45.zarr/0/.zarray"),
        45,
        0,
        conn=_FakeConn(image),
    )
    chunk_response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/45.zarr/0/0/0"),
        45,
        0,
        "0/0",
        conn=_FakeConn(image),
    )

    zarray = json.loads(zarray_response.content)
    assert zarray["dtype"] == np.dtype(np.uint16).str
    assert zarray["compressor"] is None
    assert zarray["dimension_separator"] == "/"
    assert chunk_response["Content-Length"] == str(pattern.nbytes)
    assert _response_bytes(chunk_response) == pattern.tobytes(order="C")


def test_image_chunk_generates_bounded_non_pyramid_overview_tiles(monkeypatch):
    """Verify image chunk generates bounded non pyramid overview tiles.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in generated
    overview chunk generation for ordinary OMERO-backed images.
    """
    pixel_type = next(
        key for key, dtype in views.PIXEL_TYPES.items() if dtype == np.uint8
    )
    pattern = np.array(
        [
            [0, 2, 10, 12],
            [4, 6, 14, 16],
            [20, 22, 30, 32],
            [24, 26, 34, 36],
        ],
        dtype=np.uint8,
    )
    primary_pixels = _PatternPrimaryPixels(pixel_type, pattern)
    image = _FakeImage(
        image_id=47,
        size_y=4,
        size_x=4,
        primary_pixels=primary_pixels,
    )
    monkeypatch.setattr(views, "_store_backed_json_response", lambda *_args: None)
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(views, "get_safe_image_tile_size", lambda image: (2, 2))

    zarray_response = views.image_zarray.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/47.zarr/1/.zarray"),
        47,
        1,
        conn=_FakeConn(image),
    )
    chunk_response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/47.zarr/1/0/0"),
        47,
        1,
        "0/0",
        conn=_FakeConn(image),
    )

    zarray = json.loads(zarray_response.content)
    assert zarray["shape"] == [2, 2]
    assert zarray["chunks"] == [1, 1]
    assert _response_bytes(chunk_response) == np.array([[3]], dtype=np.uint8).tobytes(
        order="C"
    )
    assert primary_pixels.calls == [(0, 0, 2, 2)]


def test_image_chunk_pads_generated_overview_edges(monkeypatch):
    """Verify image chunk pads generated overview edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in generated overview edge padding.
    """
    pixel_type = next(
        key for key, dtype in views.PIXEL_TYPES.items() if dtype == np.uint8
    )
    pattern = np.arange(9, dtype=np.uint8).reshape(3, 3)
    image = _FakeImage(
        image_id=49,
        size_y=3,
        size_x=3,
        primary_pixels=_PatternPrimaryPixels(pixel_type, pattern),
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(views, "get_safe_image_tile_size", lambda image: (2, 2))

    chunk_response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/49.zarr/1/1/1"),
        49,
        1,
        "1/1",
        conn=_FakeConn(image),
    )

    assert _response_bytes(chunk_response) == np.array([[8]], dtype=np.uint8).tobytes(
        order="C"
    )


def test_image_chunk_accepts_byte_returning_primary_pixels(monkeypatch):
    """Verify image chunk accepts byte-returning primary pixels.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image chunk accepts byte-returning primary pixels.
    """
    pixel_type = next(
        key for key, dtype in views.PIXEL_TYPES.items() if dtype == np.uint8
    )
    pattern = np.array([[3, 4], [5, 6]], dtype=np.uint8)
    image = _FakeImage(
        image_id=46,
        size_y=2,
        size_x=2,
        primary_pixels=_BytePrimaryPixels(pixel_type, pattern),
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)

    response = views.image_chunk.__wrapped__(
        RequestFactory().get("/zarr/v0.4/image/46.zarr/0/0/0"),
        46,
        0,
        "0/0",
        conn=_FakeConn(image),
    )

    assert _response_bytes(response) == pattern.tobytes(order="C")


def test_image_chunk_builds_runtime_chunk_name_for_tcz_axes(monkeypatch):
    """Verify image chunk builds runtime chunk name for tcz axes.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image chunk builds runtime chunk name.
    """
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
        "marshal_axes",
        lambda current_image, version: ["t", "c", "z", "y", "x"],
    )
    monkeypatch.setattr(views, "get_image_shape", lambda image, level: (1, 1, 1, 2, 2))
    monkeypatch.setattr(
        views, "get_chunk_shape", lambda image, level=0: (1, 1, 1, 2, 2)
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
    assert _response_bytes(response) == b"\x05\x05\x05\x05"


def test_image_chunk_rejects_wrong_dimension_count(monkeypatch):
    """Confirm image chunk rejects wrong dimension count is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image chunk rejects wrong dimension count.
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


def test_image_chunk_rejects_out_of_bounds_chunk_without_pixel_read(monkeypatch):
    """Verify image chunk rejects out of bounds chunk without pixel read.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in chunk
    bounds validation before OMERO pixel reads.
    """
    pixel_type = next(
        key for key, dtype in views.PIXEL_TYPES.items() if dtype == np.uint8
    )
    primary_pixels = _PatternPrimaryPixels(pixel_type, np.zeros((4, 4), dtype=np.uint8))
    image = _FakeImage(
        image_id=48,
        size_y=4,
        size_x=4,
        primary_pixels=primary_pixels,
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(views, "get_safe_image_tile_size", lambda image: (2, 2))

    with pytest.raises(Http404, match="chunk outside image bounds"):
        views.image_chunk.__wrapped__(
            RequestFactory().get("/zarr/v0.4/image/48.zarr/0/2/0"),
            48,
            0,
            "2/0",
            conn=_FakeConn(image),
        )

    assert primary_pixels.calls == []


def test_image_chunk_rejects_inconsistent_axis_metadata_before_pixel_read(monkeypatch):
    """Verify image chunk rejects inconsistent axis metadata before pixel read.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in axis and shape validation.
    """
    pixel_type = next(
        key for key, dtype in views.PIXEL_TYPES.items() if dtype == np.uint8
    )
    primary_pixels = _PatternPrimaryPixels(pixel_type, np.zeros((4, 4), dtype=np.uint8))
    image = _FakeImage(
        image_id=50,
        size_y=4,
        size_x=4,
        primary_pixels=primary_pixels,
    )
    monkeypatch.setattr(views, "_store_backed_chunk_response", lambda *_args: None)
    monkeypatch.setattr(views, "marshal_axes", lambda *_args: ["z", "y", "x"])

    with pytest.raises(Http404, match="metadata are inconsistent"):
        views.image_chunk.__wrapped__(
            RequestFactory().get("/zarr/v0.4/image/50.zarr/0/0/0/0"),
            50,
            0,
            "0/0/0",
            conn=_FakeConn(image),
        )

    assert primary_pixels.calls == []


def test_image_store_path_and_preview_cover_store_and_non_store_paths(
    monkeypatch, tmp_path
):
    """Verify the image store path and preview cover store and non store paths safety boundary.

    Inputs: `monkeypatch` pytest monkeypatch fixture, `tmp_path` temporary path fixture.
    Output: None after assertions pass. Raises: AssertionError when validation or
    external operations fail.
    """
    image = _FakeImage(image_id=51, name="preview.zarr", lsid=str(tmp_path))
    conn = _FakeConn(image)

    def fake_reverse(name, args=None, kwargs=None):
        """Simulate reverse so the surrounding test controls that dependency.

        Inputs: `name` name, `args` positional arguments, `kwargs` keyword arguments.
        Output: fake reverse result. Raises: AssertionError for the exercised failure path.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in store backed ome tiff helpers cover reordering planes and metadata.
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
    """Confirm app helpers reject invalid asset paths and surface fetch failures is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when app helpers reject invalid asset paths and surface fetch failures stops reporting the expected error.
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

    response = views.apps(RequestFactory().get("/zarr/validator/"), "validator", "")
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in runtime view helpers cover store shortcuts and single plane iterators.
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
