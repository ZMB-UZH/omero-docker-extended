from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from django.http import Http404
from PIL import Image

from omero_web_zarr import utils


def _write_minimal_store(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")


def test_path_and_external_lsid_helpers_cover_additional_invalid_inputs(
    tmp_path, monkeypatch
):
    assert utils.resolve_local_zarr_store(None) is None
    assert utils.resolve_local_zarr_store("https://example.invalid/demo.zarr") is None
    assert utils.resolve_local_zarr_store("file://") is None
    assert utils.resolve_local_zarr_store("relative/demo.zarr") is None
    assert utils.resolve_local_zarr_store(str(tmp_path / "missing.zarr")) is None

    not_a_store = tmp_path / "not-a-store"
    not_a_store.write_text("plain file", encoding="utf-8")
    assert utils.resolve_local_zarr_store(str(not_a_store)) is None

    store_root = tmp_path / "store.zarr"
    _write_minimal_store(store_root)
    nested_dir = store_root / "nested"
    nested_dir.mkdir()
    with pytest.raises(Http404):
        utils.resolve_local_zarr_file(store_root.resolve(), "missing.txt")
    with pytest.raises(Http404):
        utils.resolve_local_zarr_file(store_root.resolve(), "nested")

    class _Params:
        def addId(self, image_id):
            self.image_id = image_id
            return self

    omero_module = types.ModuleType("omero")
    omero_module.sys = SimpleNamespace(ParametersI=_Params)
    monkeypatch.setitem(sys.modules, "omero", omero_module)

    query_service = SimpleNamespace(
        projection=lambda query, params, service_opts: [
            [SimpleNamespace(val="file:///demo.zarr")]
        ]
    )
    image = SimpleNamespace(
        id=None,
        getId=lambda: 12,
        getDetails=lambda: SimpleNamespace(
            externalInfo=SimpleNamespace(lsid=SimpleNamespace(val=None))
        ),
        _conn=SimpleNamespace(
            getQueryService=lambda: query_service, SERVICE_OPTS=object()
        ),
    )
    assert utils._resolve_image_external_lsid(image) == "file:///demo.zarr"

    assert (
        utils._resolve_image_external_lsid(
            SimpleNamespace(
                id=None,
                getDetails=lambda: SimpleNamespace(
                    externalInfo=SimpleNamespace(lsid=SimpleNamespace(val=None))
                ),
                _conn=object(),
            )
        )
        is None
    )


def test_node_and_channel_helpers_cover_cache_mismatch_and_error_paths(
    monkeypatch, tmp_path
):
    image = SimpleNamespace(id=7)
    monkeypatch.setattr(
        utils,
        "resolve_image_backing_zarr_store",
        lambda current_image: (_ for _ in ()).throw(OSError("store failed")),
    )
    assert utils.load_store_backed_image_node(image) is None
    assert image._omero_web_zarr_node is None

    image = SimpleNamespace(id=8)
    monkeypatch.setattr(
        utils,
        "resolve_image_backing_zarr_store",
        lambda current_image: None,
    )
    assert utils.load_store_backed_image_node(image) is None
    assert image._omero_web_zarr_node is None

    image = SimpleNamespace(id=9)
    monkeypatch.setattr(
        utils,
        "resolve_image_backing_zarr_store",
        lambda current_image: tmp_path / "demo.zarr",
    )
    monkeypatch.setattr(
        utils,
        "_load_store_backed_image_node_cached",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("node failed")),
    )
    assert utils.load_store_backed_image_node(image) is None
    assert image._omero_web_zarr_node is None

    cached_image = SimpleNamespace(_omero_web_zarr_channel_overrides=[{"label": "A"}])
    assert utils.get_store_backed_channel_overrides(cached_image, [object()]) == [
        {"label": "A"}
    ]

    monkeypatch.setattr(
        utils, "load_store_backed_image_node", lambda current_image: None
    )
    size_error_image = SimpleNamespace(
        getSizeC=lambda: (_ for _ in ()).throw(RuntimeError("size failed"))
    )
    overrides = utils.get_store_backed_channel_overrides(size_error_image, [])
    assert overrides == [
        {"active": True, "color": utils.DEFAULT_CHANNEL_COLORS[0], "inverted": False}
    ]

    matching_node = SimpleNamespace(
        metadata={"multiscales": [{"datasets": [{"path": "0"}, {"path": "1"}]}]},
        data=[object(), object()],
    )
    assert utils.get_store_backed_datasets(matching_node) == [
        {"path": "0"},
        {"path": "1"},
    ]

    fallback_node = SimpleNamespace(
        metadata={"multiscales": [{}]},
        data=[object(), object()],
    )
    assert utils.get_store_backed_datasets(fallback_node) == [
        {"path": "0"},
        {"path": "1"},
    ]

    assert utils._chunk_shape(SimpleNamespace(chunks=None)) is None
    assert utils._chunk_shape(SimpleNamespace(chunks=[()])) is None
    assert utils._chunk_shape(SimpleNamespace(chunks=[4, (2, 2)])) == (4, 2)
    assert utils._clamp_index(5, 0) == 0

    single_level_node = SimpleNamespace(data=[np.zeros((4, 4), dtype=np.uint8)])
    assert utils.select_store_backed_viewer_level(single_level_node, 3) == 0
    assert utils.select_store_backed_level(SimpleNamespace(data=[]), max_width=32) == 0
    assert utils.select_store_backed_level(single_level_node) == 0
    assert utils._select_axis_index("t", None, 5, 3) == 0


def test_plane_render_and_encoding_helpers_cover_remaining_utils_paths(monkeypatch):
    original_render_store_backed_plane = utils.render_store_backed_plane

    with pytest.raises(ValueError, match="no image data"):
        utils.read_store_backed_plane(SimpleNamespace(data=[]))

    node = SimpleNamespace(data=[np.zeros((3, 4, 2), dtype=np.uint8)])
    monkeypatch.setattr(
        utils,
        "get_store_backed_axis_names",
        lambda current_node, level=0: ["y", "x", "c"],
    )
    plane, axis_names = utils.read_store_backed_plane(node, level=0)
    assert plane.shape == (2, 3, 4)
    assert axis_names == ["c", "y", "x"]

    assert utils._channel_color("#invalid", 0) == utils.DEFAULT_CHANNEL_COLORS[0]

    monkeypatch.setattr(utils, "load_store_backed_image_node", lambda image: None)
    with pytest.raises(Http404):
        utils.render_store_backed_region_pil_image(
            object(), x=0, y=0, width=5, height=5
        )

    monkeypatch.setattr(utils, "load_store_backed_image_node", lambda image: object())
    monkeypatch.setattr(
        utils,
        "render_store_backed_plane",
        lambda *args, **kwargs: np.zeros((4, 5, 3), dtype=np.uint8),
    )
    cropped = utils.render_store_backed_region_pil_image(
        object(),
        x=1,
        y=1,
        width=2,
        height=2,
    )
    assert cropped.mode == "RGB"
    assert cropped.size == (2, 2)

    jpeg_bytes, jpeg_content_type, jpeg_suffix = utils.encode_store_backed_pil_image(
        Image.new("RGBA", (2, 2), (10, 20, 30, 255)),
        "jpeg",
    )
    assert jpeg_bytes
    assert (jpeg_content_type, jpeg_suffix) == ("image/jpeg", "jpeg")

    with pytest.raises(Http404):
        utils.encode_store_backed_pil_image(Image.new("RGB", (2, 2)), "bmp")

    assert utils._configured_max_tile_length(None, default=512) == 512
    assert (
        utils._configured_max_tile_length(
            SimpleNamespace(
                getConfigService=lambda: (_ for _ in ()).throw(
                    RuntimeError("config failed")
                )
            ),
            default=256,
        )
        == 256
    )
    assert np.array_equal(
        utils._normalize_to_uint8(
            np.array([[1.0]], dtype=np.float32), (float("nan"), 1.0)
        ),
        np.zeros((1, 1), dtype=np.uint8),
    )

    monkeypatch.setattr(
        utils,
        "render_store_backed_plane",
        original_render_store_backed_plane,
    )
    monkeypatch.setattr(
        utils,
        "read_store_backed_plane",
        lambda node, level=0, z=None, t=None: (
            np.ones((1, 2, 2), dtype=np.uint8),
            ["c", "y", "x"],
        ),
    )
    single_plane = utils.render_store_backed_plane(
        SimpleNamespace(metadata={"colormap": ["#ffffff"], "contrast_limits": [None]})
    )
    assert single_plane.shape == (2, 2)

    monkeypatch.setattr(utils, "load_store_backed_image_node", lambda image: None)
    with pytest.raises(Http404, match="store-backed image data not found"):
        utils.render_store_backed_pil_image(object())


def test_store_backed_metadata_helpers_cover_symlink_resolution_and_reader_fallbacks(
    tmp_path, monkeypatch
):
    store_root = tmp_path / "store.zarr"
    _write_minimal_store(store_root)

    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    protected = outside_root / "payload.bin"
    protected.write_bytes(b"payload")
    (store_root / "linked.bin").symlink_to(protected)

    with pytest.raises(Http404):
        utils.resolve_local_zarr_file(store_root.resolve(), "linked.bin")

    monkeypatch.setattr(
        utils, "resolve_image_backing_zarr_store", lambda current_image: None
    )
    assert utils.is_store_backed_image(SimpleNamespace()) is False
    assert utils.collect_store_metadata_documents(SimpleNamespace()) is None

    monkeypatch.setattr(
        utils,
        "resolve_image_backing_zarr_store",
        lambda current_image: store_root.resolve(),
    )
    assert utils.is_store_backed_image(SimpleNamespace()) is True

    zarr_json_store = tmp_path / "json-store.zarr"
    zarr_json_store.mkdir()
    (zarr_json_store / "zarr.json").write_text(
        json.dumps(
            {
                "attributes": {
                    "multiscales": [{"datasets": [{"path": "0"}]}],
                }
            }
        ),
        encoding="utf-8",
    )
    (zarr_json_store / "0").mkdir()
    (zarr_json_store / "0" / "zarr.json").write_text(
        json.dumps({"zarr_format": 2}),
        encoding="utf-8",
    )

    assert utils._read_store_attrs(zarr_json_store) == {
        "multiscales": [{"datasets": [{"path": "0"}]}]
    }
    assert utils._store_relative_metadata_path(zarr_json_store, "0") == "0/zarr.json"
    signature = utils._store_node_signature(zarr_json_store)
    assert signature[0][0] == "zarr.json"
    assert signature[1][0] == "0/zarr.json"
    assert (
        utils._channel_limits_from_omero_channel(
            {"window": {"start": "bad", "end": "10"}}
        )
        is None
    )

    (store_root / ".zattrs").write_text(json.dumps({}), encoding="utf-8")
    assert utils._load_store_backed_image_node_from_metadata(store_root) is None
    (store_root / ".zattrs").write_text(
        json.dumps({"multiscales": [{"datasets": []}]}),
        encoding="utf-8",
    )
    assert utils._load_store_backed_image_node_from_metadata(store_root) is None

    fake_io_module = types.ModuleType("ome_zarr.io")
    fake_reader_module = types.ModuleType("ome_zarr.reader")
    monkeypatch.setitem(sys.modules, "ome_zarr.io", fake_io_module)
    monkeypatch.setitem(sys.modules, "ome_zarr.reader", fake_reader_module)
    monkeypatch.setattr(
        utils, "_resolve_ome_zarr_format", lambda current_root: object()
    )

    fake_io_module.parse_url = lambda current_root, fmt=None: None
    fake_reader_module.Reader = lambda location: lambda: []
    assert utils._load_store_backed_image_node_with_reader(store_root) is None

    class _Reader:
        def __call__(self):
            return [SimpleNamespace(data=None), SimpleNamespace(data=[])]

    fake_io_module.parse_url = lambda current_root, fmt=None: object()
    fake_reader_module.Reader = lambda location: _Reader()
    assert utils._load_store_backed_image_node_with_reader(store_root) is None


def test_store_backed_axis_and_size_helpers_cover_fallback_shapes() -> None:
    fallback_node = SimpleNamespace(
        data=[np.zeros((2, 3, 4), dtype=np.uint8)],
        metadata={"axes": [{"name": "y"}]},
    )

    assert utils.get_store_backed_axis_names(fallback_node) == ["z", "y", "x"]
    assert utils.get_store_backed_tile_size(SimpleNamespace(data=[]), default=32) == {
        "width": 32,
        "height": 32,
    }


def test_store_backed_utils_cover_root_attrs_rgb_rendering_and_tile_size_fallback(
    monkeypatch,
    tmp_path,
):
    store_root = tmp_path / "root.zarr"
    store_root.mkdir()
    (store_root / ".zattrs").write_text(
        json.dumps({"multiscales": [{"datasets": [{"path": "0"}]}]}),
        encoding="utf-8",
    )
    (store_root / ".zarray").write_text(
        json.dumps({"zarr_format": 2}),
        encoding="utf-8",
    )

    assert utils._read_store_root_attrs(store_root) == {
        "multiscales": [{"datasets": [{"path": "0"}]}]
    }
    assert utils._store_relative_metadata_path(store_root, "") == ".zarray"
    assert utils._select_axis_index("c", None, 5, 1) == 0

    monkeypatch.setattr(utils, "load_store_backed_image_node", lambda image: object())
    monkeypatch.setattr(
        utils,
        "render_store_backed_plane",
        lambda *args, **kwargs: np.zeros((2, 3, 3), dtype=np.uint8),
    )
    rendered = utils.render_store_backed_pil_image(object())
    assert rendered.mode == "RGB"

    monkeypatch.setattr(utils, "_fallback_tile_size", lambda image, conn=None: (64, 32))

    class _FallbackImage:
        _re = None

        def _prepareRenderingEngine(self):
            self._re = None

    assert utils.get_safe_image_tile_size(_FallbackImage()) == (64, 32)
