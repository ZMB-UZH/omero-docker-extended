from django.http import Http404
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from omero_web_zarr.utils import collect_store_metadata_documents
from omero_web_zarr.utils import encode_store_backed_pil_image
from omero_web_zarr.utils import open_compat_array
from omero_web_zarr.utils import is_store_metadata_path
from omero_web_zarr.utils import get_store_backed_channel_overrides
from omero_web_zarr.utils import get_store_backed_level_sizes
from omero_web_zarr.utils import get_store_backed_tile_size
from omero_web_zarr.utils import get_store_backed_zoom_level_scaling
from omero_web_zarr.utils import read_store_backed_plane
from omero_web_zarr.utils import render_store_backed_pil_image
from omero_web_zarr.utils import render_store_backed_plane
from omero_web_zarr.utils import render_store_backed_region_pil_image
from omero_web_zarr.utils import render_store_backed_thumbnail_bytes
from omero_web_zarr.utils import resolve_image_backing_zarr_store
from omero_web_zarr.utils import resolve_local_zarr_file
from omero_web_zarr.utils import resolve_local_zarr_store
from omero_web_zarr.utils import sanitize_download_basename
from omero_web_zarr.utils import select_store_backed_level
from omero_web_zarr.utils import select_store_backed_viewer_level


def _write_minimal_zarr_group(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (root / ".zattrs").write_text('{"multiscales": []}', encoding="utf-8")


class _FakeNode:
    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata


class _FakeValue:
    def __init__(self, value):
        self.val = value


class _FakeExternalInfo:
    def __init__(self, lsid):
        self.lsid = _FakeValue(lsid)


class _FakeDetails:
    def __init__(self, lsid):
        self.externalInfo = _FakeExternalInfo(lsid)


class _FakeImage:
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
        return self._details

    def getName(self):
        return self._name

    def getSizeC(self):
        return self._size_c


class _FakeProjectionValue:
    def __init__(self, value):
        self.val = value


class _FakeQueryService:
    def __init__(self, lsid):
        self._lsid = lsid

    def projection(self, query, params, service_opts):
        assert "externalInfo.lsid" in query
        return [[_FakeProjectionValue(self._lsid)]]


class _FakeConnForExternalInfo:
    def __init__(self, lsid):
        self.SERVICE_OPTS = object()
        self._query_service = _FakeQueryService(lsid)

    def getQueryService(self):
        return self._query_service


class _FakeChannel:
    def __init__(self, *, window_start=None, window_end=None, window_min=0.0, window_max=1.0):
        self._window_start = window_start
        self._window_end = window_end
        self._window_min = window_min
        self._window_max = window_max

    def getWindowStart(self):
        return self._window_start

    def getWindowEnd(self):
        return self._window_end

    def getWindowMin(self):
        return self._window_min

    def getWindowMax(self):
        return self._window_max


def test_open_compat_array_writes_v2_array_metadata_under_zarr3(tmp_path):
    open_compat_array(
        tmp_path,
        mode="w",
        shape=(2, 3, 4),
        chunks=(1, 3, 4),
        dtype=np.uint16,
    )

    assert (tmp_path / ".zarray").exists()
    assert not (tmp_path / "zarr.json").exists()


def test_open_compat_array_retries_without_zarr_format_when_unsupported(tmp_path, monkeypatch):
    calls = []

    def fake_open_array(path, **kwargs):
        calls.append(kwargs.copy())
        if "zarr_format" in kwargs:
            raise TypeError("open_array() got an unexpected keyword argument 'zarr_format'")
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


def test_open_compat_array_retries_without_zarr_format_when_runtime_warns(tmp_path, monkeypatch):
    calls = []

    def fake_open_array(path, **kwargs):
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
    def fake_open_array(path, **kwargs):
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
    _write_minimal_zarr_group(tmp_path)

    assert resolve_local_zarr_store(str(tmp_path)) == tmp_path.resolve()


def test_resolve_local_zarr_store_accepts_file_uri(tmp_path):
    _write_minimal_zarr_group(tmp_path)

    assert resolve_local_zarr_store(tmp_path.resolve().as_uri()) == tmp_path.resolve()


def test_resolve_local_zarr_store_rejects_non_group_path(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)

    assert resolve_local_zarr_store(str(tmp_path)) is None


def test_resolve_image_backing_zarr_store_queries_lsid_when_wrapper_details_are_incomplete(tmp_path):
    _write_minimal_zarr_group(tmp_path)
    image = _FakeImage(None, query_lsid=str(tmp_path.resolve()))

    assert resolve_image_backing_zarr_store(image) == tmp_path.resolve()


def test_resolve_local_zarr_file_rejects_parent_traversal(tmp_path):
    _write_minimal_zarr_group(tmp_path)

    with pytest.raises(Http404, match="zarr path not found"):
        resolve_local_zarr_file(tmp_path.resolve(), "..", "outside")


def test_resolve_local_zarr_file_accepts_nested_dataset_paths(tmp_path):
    _write_minimal_zarr_group(tmp_path)
    nested = tmp_path / "s0" / ".zarray"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("{}", encoding="utf-8")

    assert resolve_local_zarr_file(tmp_path.resolve(), "s0", ".zarray") == nested.resolve()


def test_is_store_metadata_path_identifies_supported_metadata_files(tmp_path):
    assert is_store_metadata_path(tmp_path / ".zattrs")
    assert is_store_metadata_path(tmp_path / ".zgroup")
    assert is_store_metadata_path(tmp_path / ".zarray")
    assert is_store_metadata_path(tmp_path / "zarr.json")
    assert not is_store_metadata_path(tmp_path / "0")


def test_collect_store_metadata_documents_includes_nested_metadata(tmp_path):
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
    image = _FakeImage("/tmp/fake.zarr")
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
    monkeypatch.setattr("omero_web_zarr.utils.load_store_backed_image_node", lambda image: node)

    overrides = get_store_backed_channel_overrides(image, channels=[_FakeChannel(), _FakeChannel()])

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
    image = _FakeImage("/tmp/fake.zarr")
    image._size_c = 1
    monkeypatch.setattr("omero_web_zarr.utils.load_store_backed_image_node", lambda image: None)

    overrides = get_store_backed_channel_overrides(
        image,
        channels=[_FakeChannel(window_start=None, window_end=None, window_min=2.0, window_max=7.0)],
    )

    assert overrides == [
        {
            "active": True,
            "color": (255, 255, 255),
            "window": (2.0, 7.0),
            "inverted": False,
        }
    ]


def test_sanitize_download_basename_normalizes_empty_and_path_like_names():
    assert sanitize_download_basename("", default="fallback") == "fallback"
    assert sanitize_download_basename("dir/name, with spaces.zarr") == "name._with_spaces.zarr"


def test_select_store_backed_level_prefers_smallest_sufficient_level():
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
