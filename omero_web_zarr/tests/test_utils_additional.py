from __future__ import annotations

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


def test_node_and_channel_helpers_cover_cache_mismatch_and_error_paths(monkeypatch):
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
        lambda current_image: Path("/tmp/demo.zarr"),
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
