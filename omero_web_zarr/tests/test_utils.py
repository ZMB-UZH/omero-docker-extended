import json
import sys
import tempfile
from django.http import Http404
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from omero_web_zarr.utils import _load_store_backed_image_node_cached
from omero_web_zarr.utils import _read_store_attrs
from omero_web_zarr.utils import _resolve_image_external_lsid
from omero_web_zarr.utils import _resolve_ome_zarr_format
from omero_web_zarr.utils import collect_store_metadata_documents
from omero_web_zarr.utils import encode_store_backed_pil_image
from omero_web_zarr.utils import generate_coordinate_transformations
from omero_web_zarr.utils import get_store_backed_datasets
from omero_web_zarr.utils import get_safe_image_tile_size
from omero_web_zarr.utils import open_compat_array
from omero_web_zarr.utils import is_store_metadata_path
from omero_web_zarr.utils import get_store_backed_channel_overrides
from omero_web_zarr.utils import get_store_backed_level_sizes
from omero_web_zarr.utils import get_store_backed_tile_size
from omero_web_zarr.utils import get_store_backed_zoom_level_scaling
from omero_web_zarr.utils import load_store_backed_image_node
from omero_web_zarr.utils import read_store_backed_plane
from omero_web_zarr.utils import render_store_backed_pil_image
from omero_web_zarr.utils import render_store_backed_plane
from omero_web_zarr.utils import render_store_backed_region_pil_image
from omero_web_zarr.utils import render_store_backed_thumbnail_bytes
from omero_web_zarr.utils import marshal_axes
from omero_web_zarr.utils import marshal_pixel_sizes
from omero_web_zarr.utils import resolve_image_backing_zarr_store
from omero_web_zarr.utils import resolve_local_zarr_file
from omero_web_zarr.utils import resolve_local_zarr_store
from omero_web_zarr.utils import sanitize_download_basename
from omero_web_zarr.utils import select_store_backed_level
from omero_web_zarr.utils import select_store_backed_viewer_level


def _write_minimal_zarr_group(root):
    """Handle write minimal Zarr group."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (root / ".zattrs").write_text('{"multiscales": []}', encoding="utf-8")


class _FakeNode:
    """Test double for fake node."""

    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata


class _FakeValue:
    """Test double for fake value."""

    def __init__(self, value):
        self.val = value


class _FakeExternalInfo:
    """Test double for fake external info."""

    def __init__(self, lsid):
        self.lsid = _FakeValue(lsid)


class _FakeDetails:
    """Test double for fake details."""

    def __init__(self, lsid):
        self.externalInfo = _FakeExternalInfo(lsid)


class _FakeImage:
    """Test double for fake image."""

    def __init__(self, lsid, name="store.zarr", *, query_lsid=None):
        self._details = _FakeDetails(lsid)
        self._name = name
        self._size_c = 1
        self.id = 1
        self._conn = None
        if query_lsid is not None:
            self._details = _FakeDetails(None)
            self._conn = _FakeConnForExternalInfo(query_lsid)

    def getDetails(self):
        """Return get details."""
        return self._details

    def getName(self):
        """Return get name."""
        return self._name

    def getSizeC(self):
        """Return get size c."""
        return self._size_c


class _FakeProjectionValue:
    """Test double for fake projection value."""

    def __init__(self, value):
        self.val = value


class _FakeQueryService:
    """Test double for fake query service."""

    def __init__(self, lsid):
        self._lsid = lsid

    def projection(self, query, params, service_opts):
        """Handle projection."""
        assert "externalInfo.lsid" in query
        return [[_FakeProjectionValue(self._lsid)]]


class _FakeConnForExternalInfo:
    """Test double for fake conn for external info."""

    def __init__(self, lsid):
        self.SERVICE_OPTS = object()
        self._query_service = _FakeQueryService(lsid)

    def getQueryService(self):
        """Return get query service."""
        return self._query_service


class _FakeConfigService:
    """Test double for fake config service."""

    def __init__(self, value):
        self._value = value

    def getConfigValue(self, key):
        """Return get config value."""
        assert key == "omero.pixeldata.max_tile_length"
        return str(self._value)


class _FakeConnForTileSize:
    """Test double for fake conn for tile size."""

    def __init__(self, value):
        self._config = _FakeConfigService(value)

    def getConfigService(self):
        """Return get config service."""
        return self._config


class _BrokenQueryService:
    """Represent broken query service."""

    @staticmethod
    def projection(*args, **kwargs):
        """Handle projection."""
        raise RuntimeError("boom")


class _EmptyQueryService:
    """Represent empty query service."""

    @staticmethod
    def projection(*args, **kwargs):
        """Handle projection."""
        return []


class _FakeChannel:
    """Test double for fake channel."""

    def __init__(
        self, *, window_start=None, window_end=None, window_min=0.0, window_max=1.0
    ):
        self._window_start = window_start
        self._window_end = window_end
        self._window_min = window_min
        self._window_max = window_max

    def getWindowStart(self):
        """Return get window start."""
        return self._window_start

    def getWindowEnd(self):
        """Return get window end."""
        return self._window_end

    def getWindowMin(self):
        """Return get window min."""
        return self._window_min

    def getWindowMax(self):
        """Return get window max."""
        return self._window_max


class _TileFailureRenderingEngine:
    """Represent tile failure rendering engine."""

    @staticmethod
    def getTileSize():
        """Return get tile size."""
        raise RuntimeError("ZarrReader.getOptimalTileWidth failed during getTileSize")


class _TileFailureImage:
    """Represent tile failure image."""

    def __init__(self, *, size_x, size_y, max_tile_length):
        self.id = 99
        self._size_x = size_x
        self._size_y = size_y
        self._conn = _FakeConnForTileSize(max_tile_length)
        self._re = _TileFailureRenderingEngine()

    def getSizeX(self):
        """Return get size x."""
        return self._size_x

    def getSizeY(self):
        """Return get size y."""
        return self._size_y


def _write_multiscale_store(root, *, attrs=None):
    """Handle write multiscale store."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    payload = {
        "multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}],
    }
    if attrs:
        payload.update(attrs)
    (root / ".zattrs").write_text(json.dumps(payload), encoding="utf-8")
    (root / "0").mkdir(parents=True, exist_ok=True)


def test_open_compat_array_requests_v2_layout_by_default(tmp_path, monkeypatch):
    """Verify test open compat array requests v2 layout by behavior."""
    calls = []
    sentinel = object()

    def fake_open_array(path, **kwargs):
        """Handle fake open array."""
        calls.append((Path(path), kwargs.copy()))
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / ".zarray").write_text("{}", encoding="utf-8")
        return sentinel

    monkeypatch.setattr("omero_web_zarr.utils.zarr.open_array", fake_open_array)

    result = open_compat_array(
        tmp_path / "0",
        mode="w",
        shape=(2, 3, 4),
        chunks=(1, 3, 4),
        dtype=np.uint16,
    )

    assert result is sentinel
    assert calls == [
        (
            tmp_path / "0",
            {
                "mode": "w",
                "shape": (2, 3, 4),
                "chunks": (1, 3, 4),
                "dtype": np.uint16,
                "zarr_format": 2,
            },
        )
    ]
    assert (tmp_path / "0" / ".zarray").exists()
    assert not (tmp_path / "0" / "zarr.json").exists()


def test_open_compat_array_retries_without_zarr_format_when_unsupported(
    tmp_path, monkeypatch
):
    """Verify test open compat array retries without Zarr f behavior."""
    calls = []

    def fake_open_array(path, **kwargs):
        """Handle fake open array."""
        calls.append(kwargs.copy())
        if "zarr_format" in kwargs:
            raise TypeError(
                "open_array() got an unexpected keyword argument 'zarr_format'"
            )
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / ".zarray").write_text("{}", encoding="utf-8")
        return object()

    monkeypatch.setattr("omero_web_zarr.utils.zarr.open_array", fake_open_array)

    open_compat_array(
        tmp_path,
        mode="w",
        shape=(1,),
        chunks=(1,),
        dtype=np.uint8,
    )

    assert calls[0]["zarr_format"] == 2
    assert "zarr_format" not in calls[1]


def test_open_compat_array_retries_without_zarr_format_when_runtime_warns(
    tmp_path, monkeypatch
):
    """Verify test open compat array retries without Zarr f behavior."""
    calls = []

    def fake_open_array(path, **kwargs):
        """Handle fake open array."""
        calls.append(kwargs.copy())
        if "zarr_format" in kwargs:
            raise UserWarning("ignoring keyword argument 'zarr_format'")
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / ".zarray").write_text("{}", encoding="utf-8")
        return object()

    monkeypatch.setattr("omero_web_zarr.utils.zarr.open_array", fake_open_array)

    open_compat_array(
        tmp_path,
        mode="w",
        shape=(1,),
        chunks=(1,),
        dtype=np.uint8,
    )

    assert calls[0]["zarr_format"] == 2
    assert "zarr_format" not in calls[1]


def test_open_compat_array_does_not_hide_other_type_errors(tmp_path, monkeypatch):
    """Verify test open compat array does not hide other ty behavior."""

    def fake_open_array(path, **kwargs):
        """Handle fake open array."""
        raise TypeError("different failure")

    monkeypatch.setattr("omero_web_zarr.utils.zarr.open_array", fake_open_array)

    with pytest.raises(TypeError, match="different failure"):
        open_compat_array(
            tmp_path,
            mode="w",
            shape=(1,),
            chunks=(1,),
            dtype=np.uint8,
        )


def test_resolve_local_zarr_store_accepts_absolute_path(tmp_path):
    """Verify test resolve local Zarr store accepts absolut behavior."""
    _write_minimal_zarr_group(tmp_path)

    assert resolve_local_zarr_store(str(tmp_path)) == tmp_path.resolve()


def test_resolve_local_zarr_store_accepts_file_uri(tmp_path):
    """Verify test resolve local Zarr store accepts file uri."""
    _write_minimal_zarr_group(tmp_path)

    assert resolve_local_zarr_store(tmp_path.resolve().as_uri()) == tmp_path.resolve()


def test_resolve_local_zarr_store_rejects_non_group_path(tmp_path):
    """Verify test resolve local Zarr store rejects non gro behavior."""
    tmp_path.mkdir(parents=True, exist_ok=True)

    assert resolve_local_zarr_store(str(tmp_path)) is None


def test_resolve_image_backing_zarr_store_queries_lsid_when_wrapper_details_are_incomplete(
    tmp_path, monkeypatch
):
    """Verify test resolve image backing Zarr store queries behavior."""

    class _FakeParametersI:
        """Test double for fake parameters i."""

        def addId(self, image_id):
            """Handle add identifier."""
            self.image_id = image_id
            return self

    fake_omero = type(
        "FakeOmeroModule",
        (),
        {"sys": type("FakeSys", (), {"ParametersI": _FakeParametersI})},
    )()
    monkeypatch.setitem(sys.modules, "omero", fake_omero)
    _write_minimal_zarr_group(tmp_path)
    image = _FakeImage(None, query_lsid=str(tmp_path.resolve()))

    assert resolve_image_backing_zarr_store(image) == tmp_path.resolve()


def test_resolve_local_zarr_file_rejects_parent_traversal(tmp_path):
    """Verify test resolve local Zarr file rejects parent t behavior."""
    _write_minimal_zarr_group(tmp_path)

    with pytest.raises(Http404, match="zarr path not found"):
        resolve_local_zarr_file(tmp_path.resolve(), "..", "outside")


def test_resolve_local_zarr_file_accepts_nested_dataset_paths(tmp_path):
    """Verify test resolve local Zarr file accepts nested d behavior."""
    _write_minimal_zarr_group(tmp_path)
    nested = tmp_path / "s0" / ".zarray"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("{}", encoding="utf-8")

    assert (
        resolve_local_zarr_file(tmp_path.resolve(), "s0", ".zarray") == nested.resolve()
    )


def test_is_store_metadata_path_identifies_supported_metadata_files(tmp_path):
    """Verify test is store metadata path identifies suppor behavior."""
    assert is_store_metadata_path(tmp_path / ".zattrs")
    assert is_store_metadata_path(tmp_path / ".zgroup")
    assert is_store_metadata_path(tmp_path / ".zarray")
    assert is_store_metadata_path(tmp_path / "zarr.json")
    assert not is_store_metadata_path(tmp_path / "0")


def test_collect_store_metadata_documents_includes_nested_metadata(tmp_path):
    """Verify test collect store metadata documents include behavior."""
    _write_minimal_zarr_group(tmp_path)
    nested = tmp_path / "tables" / "features" / ".zattrs"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text('{"table": true}', encoding="utf-8")

    image = _FakeImage(str(tmp_path.resolve()))
    documents = collect_store_metadata_documents(image)

    assert documents[".zattrs"] == {"multiscales": []}
    assert documents[".zgroup"] == {"zarr_format": 2}
    assert documents["tables/features/.zattrs"] == {"table": True}


def test_get_store_backed_channel_overrides_prefers_zarr_display_metadata(monkeypatch):
    """Verify test get store backed channel overrides prefe behavior."""
    image = _FakeImage(str(Path(tempfile.gettempdir()) / "fake.zarr"))
    image._size_c = 2
    node = _FakeNode(
        [np.zeros((2, 4, 4), dtype=np.uint16)],
        {
            "channel_names": ["DNA", "Actin"],
            "visible": [True, False],
            "contrast_limits": [[10, 20], [30, 40]],
            "colormap": [
                [[0, 0, 0], [1.0, 0.0, 0.0]],
                [[0, 0, 0], [0.0, 1.0, 0.0]],
            ],
        },
    )
    monkeypatch.setattr(
        "omero_web_zarr.utils.load_store_backed_image_node", lambda image: node
    )

    overrides = get_store_backed_channel_overrides(
        image, channels=[_FakeChannel(), _FakeChannel()]
    )

    assert overrides == [
        {
            "label": "DNA",
            "active": True,
            "color": (255, 0, 0),
            "window": (10.0, 20.0),
            "inverted": False,
        },
        {
            "label": "Actin",
            "active": False,
            "color": (0, 255, 0),
            "window": (30.0, 40.0),
            "inverted": False,
        },
    ]


def test_get_store_backed_channel_overrides_falls_back_to_channel_windows(monkeypatch):
    """Verify test get store backed channel overrides falls behavior."""
    image = _FakeImage(str(Path(tempfile.gettempdir()) / "fake.zarr"))
    image._size_c = 1
    monkeypatch.setattr(
        "omero_web_zarr.utils.load_store_backed_image_node", lambda image: None
    )

    overrides = get_store_backed_channel_overrides(
        image,
        channels=[
            _FakeChannel(
                window_start=None, window_end=None, window_min=2.0, window_max=7.0
            )
        ],
    )

    assert overrides == [
        {
            "active": True,
            "color": (255, 255, 255),
            "window": (2.0, 7.0),
            "inverted": False,
        }
    ]


def test_load_store_backed_image_node_preserves_partial_channel_metadata_alignment(
    tmp_path, monkeypatch
):
    """Verify test load store backed image node preserves p behavior."""
    _write_multiscale_store(
        tmp_path,
        attrs={
            "omero": {
                "channels": [
                    {"active": True},
                    {
                        "label": "DNA",
                        "active": False,
                        "window": {"start": 5, "end": 15},
                        "color": "00FF00",
                    },
                ]
            }
        },
    )
    image = _FakeImage(str(tmp_path.resolve()))
    fake_array = np.arange(4, dtype=np.uint16).reshape(1, 2, 2)

    monkeypatch.setattr(
        "omero_web_zarr.utils.zarr.open_array",
        lambda path, mode="r": fake_array,
    )

    node = load_store_backed_image_node(image)

    assert node.metadata["channel_names"] == [None, "DNA"]
    assert node.metadata["visible"] == [True, False]
    assert node.metadata["contrast_limits"] == [None, (5.0, 15.0)]
    assert node.metadata["colormap"] == [None, "00FF00"]
    assert np.array_equal(node.data[0], fake_array)


def test_get_safe_image_tile_size_falls_back_to_configured_maximum():
    """Verify test get safe image tile size falls back to c behavior."""
    image = _TileFailureImage(size_x=2048, size_y=512, max_tile_length=1024)

    assert get_safe_image_tile_size(image) == (1024, 512)


def test_sanitize_download_basename_normalizes_empty_and_path_like_names():
    """Verify test sanitize download basename normalizes em behavior."""
    assert sanitize_download_basename("", default="fallback") == "fallback"
    assert (
        sanitize_download_basename("dir/name, with spaces.zarr")
        == "name._with_spaces.zarr"
    )


def test_select_store_backed_level_prefers_smallest_sufficient_level():
    """Verify test select store backed level prefers smalle behavior."""
    node = _FakeNode(
        [
            np.zeros((1, 1024, 1024), dtype=np.uint8),
            np.zeros((1, 256, 256), dtype=np.uint8),
            np.zeros((1, 64, 64), dtype=np.uint8),
        ],
        {"axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]},
    )

    assert select_store_backed_level(node, max_width=96, max_height=96) == 2
    assert select_store_backed_level(node, max_width=500, max_height=500) == 1


def test_read_store_backed_plane_maps_full_resolution_z_to_subresolution():
    """Verify test read store backed plane maps full resolu behavior."""
    node = _FakeNode(
        [
            np.arange(12, dtype=np.uint16).reshape(4, 1, 3),
            np.array([[[10, 11, 12]], [[20, 21, 22]]], dtype=np.uint16),
        ],
        {"axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]},
    )

    plane, axes = read_store_backed_plane(node, level=1, z=3)

    assert axes == ["y", "x"]
    assert plane.tolist() == [[20, 21, 22]]


def test_render_store_backed_plane_composites_visible_channels():
    """Verify test render store backed plane composites vis behavior."""
    node = _FakeNode(
        [
            np.array(
                [
                    [[0, 10], [10, 0]],
                    [[10, 0], [0, 10]],
                ],
                dtype=np.uint16,
            )
        ],
        {
            "axes": [{"name": "c"}, {"name": "y"}, {"name": "x"}],
            "visible": [True, True],
            "contrast_limits": [[0, 10], [0, 10]],
            "colormap": [
                [[0, 0, 0], [1, 0, 0]],
                [[0, 0, 0], [0, 1, 0]],
            ],
        },
    )

    rendered = render_store_backed_plane(node)

    assert rendered.shape == (2, 2, 3)
    assert tuple(rendered[0, 0]) == (0, 255, 0)
    assert tuple(rendered[0, 1]) == (255, 0, 0)


def test_render_store_backed_thumbnail_bytes_uses_helper_node(monkeypatch):
    """Verify test render store backed thumbnail bytes uses behavior."""
    node = _FakeNode(
        [np.arange(256, dtype=np.uint16).reshape(1, 16, 16)],
        {"axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]},
    )

    monkeypatch.setattr(
        "omero_web_zarr.utils.load_store_backed_image_node",
        lambda image: node,
    )

    payload = render_store_backed_thumbnail_bytes(object(), size=8)

    thumbnail = Image.open(BytesIO(payload))
    assert max(thumbnail.size) <= 8


def test_render_store_backed_pil_image_respects_requested_level(monkeypatch):
    """Verify test render store backed pil image respects r behavior."""
    node = _FakeNode(
        [
            np.full((1, 32, 32), 5, dtype=np.uint16),
            np.full((1, 8, 8), 9, dtype=np.uint16),
        ],
        {"axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]},
    )

    monkeypatch.setattr(
        "omero_web_zarr.utils.load_store_backed_image_node",
        lambda image: node,
    )

    pil_image = render_store_backed_pil_image(object(), level=1)

    assert pil_image.size == (8, 8)


def test_store_backed_level_metadata_uses_multiscale_shapes_and_chunks():
    """Verify test store backed level metadata uses multisc behavior."""
    array0 = type(
        "FakeArray",
        (),
        {
            "shape": (1, 1, 512, 1024),
            "chunks": ((1,), (1,), (128, 128, 128, 128), (256, 256, 256, 256)),
        },
    )()
    array1 = type(
        "FakeArray",
        (),
        {
            "shape": (1, 1, 256, 512),
            "chunks": ((1,), (1,), (128, 128), (256, 256)),
        },
    )()
    node = _FakeNode([array0, array1], {"axes": ["t", "c", "y", "x"]})

    assert get_store_backed_level_sizes(node) == [
        {"sizeX": 1024, "sizeY": 512},
        {"sizeX": 512, "sizeY": 256},
    ]
    assert get_store_backed_tile_size(node) == {"width": 256, "height": 128}
    assert get_store_backed_zoom_level_scaling(node) == {0: 1.0, 1: 0.5}
    assert select_store_backed_viewer_level(node, 0) == 1
    assert select_store_backed_viewer_level(node, 1) == 0


def test_render_store_backed_region_pil_image_crops_requested_level(monkeypatch):
    """Verify test render store backed region pil image cro behavior."""
    node = _FakeNode(
        [
            np.arange(16, dtype=np.uint8).reshape(1, 4, 4),
            np.full((1, 2, 2), 200, dtype=np.uint8),
        ],
        {"axes": ["z", "y", "x"]},
    )

    monkeypatch.setattr(
        "omero_web_zarr.utils.load_store_backed_image_node",
        lambda image: node,
    )

    coarse = render_store_backed_region_pil_image(
        object(),
        x=0,
        y=0,
        width=2,
        height=2,
        z=0,
        level=1,
    )
    full = render_store_backed_region_pil_image(
        object(),
        x=2,
        y=2,
        width=2,
        height=2,
        z=0,
        level=0,
    )

    assert np.array(coarse).tolist() == [[255, 255], [255, 255]]
    assert np.array(full).tolist() == [[170, 187], [238, 255]]


def test_encode_store_backed_pil_image_supports_png_and_tiff():
    """Verify test encode store backed pil image supports p behavior."""
    pil_image = Image.fromarray(np.full((4, 4), 255, dtype=np.uint8), mode="L")

    png_payload, png_content_type, png_suffix = encode_store_backed_pil_image(
        pil_image,
        "png",
    )
    tif_payload, tif_content_type, tif_suffix = encode_store_backed_pil_image(
        pil_image,
        "tif",
    )

    assert png_content_type == "image/png"
    assert png_suffix == "png"
    assert tif_content_type == "image/tiff"
    assert tif_suffix == "tif"
    assert png_payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert tif_payload[:4] in (b"II*\x00", b"MM\x00*")


def test_generate_coordinate_transformations_computes_scales():
    """Verify scale factors for a two-level pyramid."""
    shapes = [(1, 1, 100, 200), (1, 1, 50, 100)]
    result = generate_coordinate_transformations(shapes)
    assert len(result) == 2
    assert result[0] == [{"type": "scale", "scale": [1.0, 1.0, 1.0, 1.0]}]
    assert result[1] == [{"type": "scale", "scale": [1.0, 1.0, 2.0, 2.0]}]


def test_generate_coordinate_transformations_rejects_dimension_mismatch():
    """Shapes with differing number of dimensions must raise ValueError."""
    shapes = [(1, 1, 100, 200), (1, 50, 100)]
    with pytest.raises(ValueError, match="Shape dimension mismatch"):
        generate_coordinate_transformations(shapes)


def test_marshal_axes_and_pixel_sizes_cover_supported_and_invalid_versions():
    """Verify test marshal axes and pixel sizes cover suppo behavior."""

    class _PixelSize:
        """Represent pixel size."""

        def __init__(self, value, unit):
            self._value = value
            self._unit = unit

        def getUnit(self):
            """Return get unit."""
            return self._unit

        def getValue(self):
            """Return get value."""
            return self._value

    image = type(
        "Image",
        (),
        {
            "getSizeT": lambda self: 2,
            "getSizeC": lambda self: 3,
            "getSizeZ": lambda self: 4,
            "getSizeY": lambda self: 512,
            "getSizeX": lambda self: 1024,
            "getPixelSizeX": lambda self, units=True: _PixelSize(0.5, "MICROMETER"),
            "getPixelSizeY": lambda self, units=True: _PixelSize(0.75, "MICROMETER"),
            "getPixelSizeZ": lambda self, units=True: _PixelSize(1.5, "MICROMETER"),
        },
    )()

    assert marshal_pixel_sizes(image) == {
        "x": {"unit": "micrometer", "value": 0.5},
        "y": {"unit": "micrometer", "value": 0.75},
        "z": {"unit": "micrometer", "value": 1.5},
    }
    assert marshal_axes(image, "0.3") == ["t", "c", "z", "y", "x"]
    assert marshal_axes(image, "0.4") == [
        {"name": "t", "type": "time"},
        {"name": "c", "type": "channel"},
        {"name": "z", "type": "space", "unit": "micrometer"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]

    with pytest.raises(Http404, match="version not supported"):
        marshal_axes(image, "0.5")


def test_resolve_image_external_lsid_covers_missing_ids_and_query_failures(monkeypatch):
    """Verify test resolve image external lsid covers missi behavior."""
    image_without_conn = _FakeImage(None)
    assert _resolve_image_external_lsid(image_without_conn) is None

    query_fail_image = _FakeImage(None, query_lsid="ignored")
    monkeypatch.setattr(query_fail_image._conn, "getQueryService", _BrokenQueryService)
    assert _resolve_image_external_lsid(query_fail_image) is None

    no_row_image = _FakeImage(None, query_lsid="ignored")
    monkeypatch.setattr(no_row_image._conn, "getQueryService", _EmptyQueryService)
    assert _resolve_image_external_lsid(no_row_image) is None


def test_read_store_attrs_and_format_resolution_support_zarr_json_and_v04(
    tmp_path, monkeypatch
):
    """Verify test read store attrs and format resolution s behavior."""
    payload = {
        "attributes": {
            "multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}],
        }
    }
    (tmp_path / "zarr.json").write_text(json.dumps(payload), encoding="utf-8")

    assert _read_store_attrs(tmp_path) == payload["attributes"]

    fake_format_module = SimpleNamespace(
        CurrentFormat=lambda: "current-format",
        FormatV04=lambda: "format-v04",
    )
    monkeypatch.setitem(sys.modules, "ome_zarr.format", fake_format_module)
    assert _resolve_ome_zarr_format(tmp_path) == "format-v04"

    monkeypatch.setattr(
        "omero_web_zarr.utils._read_store_attrs",
        lambda store_root: (_ for _ in ()).throw(OSError("missing")),
    )
    assert _resolve_ome_zarr_format(tmp_path) == "current-format"


def test_load_store_backed_image_node_reader_and_cache_fallbacks(tmp_path, monkeypatch):
    """Verify test load store backed image node reader and behavior."""
    _write_minimal_zarr_group(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))
    sentinel_node = _FakeNode(
        [np.zeros((1, 2, 2), dtype=np.uint8)], {"axes": ["z", "y", "x"]}
    )

    fake_io = SimpleNamespace(parse_url=lambda store_root, fmt=None: ("location", fmt))
    fake_reader = SimpleNamespace(Reader=lambda location: lambda: [sentinel_node])
    monkeypatch.setitem(sys.modules, "ome_zarr.io", fake_io)
    monkeypatch.setitem(sys.modules, "ome_zarr.reader", fake_reader)
    monkeypatch.setattr(
        "omero_web_zarr.utils._resolve_ome_zarr_format",
        lambda store_root: "fmt",
    )
    monkeypatch.setattr(
        "omero_web_zarr.utils._load_store_backed_image_node_from_metadata",
        lambda store_root: (_ for _ in ()).throw(RuntimeError("metadata failed")),
    )
    _load_store_backed_image_node_cached.cache_clear()

    node = load_store_backed_image_node(image)
    cached = load_store_backed_image_node(image)

    assert node is sentinel_node
    assert cached is sentinel_node

    class _MissingStoreImage:
        """Represent missing store image."""

        pass

    missing_store_image = _MissingStoreImage()
    monkeypatch.setattr(
        "omero_web_zarr.utils.resolve_image_backing_zarr_store",
        lambda image: (_ for _ in ()).throw(OSError("gone")),
    )
    assert load_store_backed_image_node(missing_store_image) is None


def test_store_backed_dataset_and_render_helpers_cover_fallback_paths():
    """Verify test store backed dataset and render helpers behavior."""
    node = _FakeNode(
        [
            np.full((1, 2, 2), 5, dtype=np.uint16),
            np.full((1, 1, 1), 7, dtype=np.uint16),
        ],
        {"axes": ["z", "y", "x"]},
    )

    assert get_store_backed_datasets(node) == [{"path": "0"}, {"path": "1"}]

    colorful_node = _FakeNode(
        [np.array([[[0, 10], [10, 0]]], dtype=np.uint16)],
        {
            "axes": ["c", "y", "x"],
            "contrast_limits": [[0, 10]],
            "colormap": ["FF0000"],
        },
    )
    invisible_node = _FakeNode(
        [
            np.array(
                [
                    [[0, 10], [10, 0]],
                    [[10, 0], [0, 10]],
                ],
                dtype=np.uint16,
            )
        ],
        {
            "axes": ["c", "y", "x"],
            "visible": [False, False],
            "contrast_limits": [[0, 10], [0, 10]],
        },
    )

    colorful = render_store_backed_plane(colorful_node)
    invisible = render_store_backed_plane(invisible_node)

    assert tuple(colorful[0, 1]) == (255, 0, 0)
    assert invisible.shape == (2, 2)


def test_get_safe_image_tile_size_prepares_rendering_engine_and_falls_back():
    """Verify test get safe image tile size prepares render behavior."""

    class _PreparedEngine:
        """Represent prepared engine."""

        @staticmethod
        def getTileSize():
            """Return get tile size."""
            return (64, 32)

    class _PreparedImage:
        """Represent prepared image."""

        def __init__(self):
            self._re = None

        def _prepareRenderingEngine(self):
            """Handle prepare rendering engine."""
            self._re = _PreparedEngine()

        @staticmethod
        def getSizeX():
            """Return get size x."""
            return 512

        @staticmethod
        def getSizeY():
            """Return get size y."""
            return 256

    assert get_safe_image_tile_size(_PreparedImage()) == (64, 32)

    class _BrokenEngine:
        """Represent broken engine."""

        @staticmethod
        def getTileSize():
            """Return get tile size."""
            raise RuntimeError("not a tile-size failure")

    class _BrokenImage:
        """Represent broken image."""

        _re = _BrokenEngine()

        @staticmethod
        def getSizeX():
            """Return get size x."""
            return 512

        @staticmethod
        def getSizeY():
            """Return get size y."""
            return 256

    with pytest.raises(RuntimeError, match="not a tile-size failure"):
        get_safe_image_tile_size(_BrokenImage())
