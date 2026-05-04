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
    """Write the minimal Zarr group.

    Inputs: `root`. Output: None.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (root / ".zattrs").write_text('{"multiscales": []}', encoding="utf-8")


class _FakeNode:
    """Test double for fake node."""

    def __init__(self, data, metadata):
        """Create `_FakeNode` with `data` and `metadata`.

        Inputs: `data`, `metadata`. Output: None.
        """
        self.data = data
        self.metadata = metadata


class _FakeValue:
    """Test double for fake value."""

    def __init__(self, value):
        """Create `_FakeValue` with `value`.

        Inputs: `value`. Output: None.
        """
        self.val = value


class _FakeExternalInfo:
    """Test double for fake external info."""

    def __init__(self, lsid):
        """Create `_FakeExternalInfo` with `lsid`.

        Inputs: `lsid`. Output: None.
        """
        self.lsid = _FakeValue(lsid)


class _FakeDetails:
    """Test double for fake details."""

    def __init__(self, lsid):
        """Create `_FakeDetails` with `lsid`.

        Inputs: `lsid`. Output: None.
        """
        self.externalInfo = _FakeExternalInfo(lsid)


class _FakeImage:
    """Test double for fake image."""

    def __init__(self, lsid, name="store.zarr", *, query_lsid=None):
        """Create `_FakeImage` with `lsid` and `name`.

        Inputs: `lsid`, `name`, `query_lsid`. Output: None.
        """
        self._details = _FakeDetails(lsid)
        self._name = name
        self._size_c = 1
        self.id = 1
        self._conn = None
        if query_lsid is not None:
            self._details = _FakeDetails(None)
            self._conn = _FakeConnForExternalInfo(query_lsid)

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

    def getSizeC(self):
        """Return `_FakeImage`'s fake channel count.

        Inputs: none. Output: `self._size_c`.
        """
        return self._size_c


class _FakeProjectionValue:
    """Test double for fake projection value."""

    def __init__(self, value):
        """Create `_FakeProjectionValue` with `value`.

        Inputs: `value`. Output: None.
        """
        self.val = value


class _FakeQueryService:
    """Test double for fake query service."""

    def __init__(self, lsid):
        """Create `_FakeQueryService` with `lsid`.

        Inputs: `lsid`. Output: None.
        """
        self._lsid = lsid

    def projection(self, query, params, service_opts):
        """Return the projection for `_FakeQueryService`.

        Inputs: `query`, `params` SQL parameters, `service_opts`. Output: `list`.
        """
        assert "externalInfo.lsid" in query
        return [[_FakeProjectionValue(self._lsid)]]


class _FakeConnForExternalInfo:
    """Test double for fake conn for external info."""

    def __init__(self, lsid):
        """Create `_FakeConnForExternalInfo` with `lsid`.

        Inputs: `lsid`. Output: None.
        """
        self.SERVICE_OPTS = object()
        self._query_service = _FakeQueryService(lsid)

    def getQueryService(self):
        """Return the fake query service value used by this test double.

        Inputs: none. Output: `self._query_service`.
        """
        return self._query_service


class _FakeConfigService:
    """Test double for fake config service."""

    def __init__(self, value):
        """Create `_FakeConfigService` with `value`.

        Inputs: `value`. Output: None.
        """
        self._value = value

    def getConfigValue(self, key):
        """Return `_FakeConfigService`'s fake config value.

        Inputs: `key`. Output: `str` result.
        """
        assert key == "omero.pixeldata.max_tile_length"
        return str(self._value)


class _FakeConnForTileSize:
    """Test double for fake conn for tile size."""

    def __init__(self, value):
        """Create `_FakeConnForTileSize` with `value`.

        Inputs: `value`. Output: None.
        """
        self._config = _FakeConfigService(value)

    def getConfigService(self):
        """Return `_FakeConnForTileSize`'s fake config service.

        Inputs: none. Output: `self._config`.
        """
        return self._config


class _BrokenQueryService:
    """Test double for broken query service behavior in this module."""

    @staticmethod
    def projection(*args, **kwargs):
        """Record the projection call on `_BrokenQueryService` for later assertions.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        None. Raises: RuntimeError when validation or the called operation fails.
        """
        raise RuntimeError("boom")


class _EmptyQueryService:
    """Test double for empty query service behavior in this module."""

    @staticmethod
    def projection(*args, **kwargs):
        """Return the projection for `_EmptyQueryService`.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `list`.
        """
        return []


class _FakeChannel:
    """Test double for fake channel."""

    def __init__(
        self, *, window_start=None, window_end=None, window_min=0.0, window_max=1.0
    ):
        """Create `_FakeChannel` with its default state.

        Inputs: `window_start`, `window_end`, `window_min`, `window_max`. Output: None.
        """
        self._window_start = window_start
        self._window_end = window_end
        self._window_min = window_min
        self._window_max = window_max

    def getWindowStart(self):
        """Return the fake window start value used by this test double.

        Inputs: none. Output: `self._window_start`.
        """
        return self._window_start

    def getWindowEnd(self):
        """Return the fake window end value used by this test double.

        Inputs: none. Output: `self._window_end`.
        """
        return self._window_end

    def getWindowMin(self):
        """Return the fake window min value used by this test double.

        Inputs: none. Output: `self._window_min`.
        """
        return self._window_min

    def getWindowMax(self):
        """Return the fake window max value used by this test double.

        Inputs: none. Output: `self._window_max`.
        """
        return self._window_max


class _TileFailureRenderingEngine:
    """Test double for tile failure rendering engine behavior in this module."""

    @staticmethod
    def getTileSize():
        """Return the fake tile size value used by this test double.

        Inputs: caller provides no extra arguments. Output: returns the fake value described above.
        """
        raise RuntimeError("ZarrReader.getOptimalTileWidth failed during getTileSize")


class _TileFailureImage:
    """Test double for tile failure image behavior in this module."""

    def __init__(self, *, size_x, size_y, max_tile_length):
        """Create `_TileFailureImage` with its default state.

        Inputs: `size_x`, `size_y`, `max_tile_length`. Output: None.
        """
        self.id = 99
        self._size_x = size_x
        self._size_y = size_y
        self._conn = _FakeConnForTileSize(max_tile_length)
        self._re = _TileFailureRenderingEngine()

    def getSizeX(self):
        """Return `_TileFailureImage`'s fake SizeX value.

        Inputs: none. Output: `self._size_x`.
        """
        return self._size_x

    def getSizeY(self):
        """Return `_TileFailureImage`'s fake SizeY value.

        Inputs: none. Output: `self._size_y`.
        """
        return self._size_y


def _write_multiscale_store(root, *, attrs=None):
    """Write the multiscale store.

    Inputs: `root`, `attrs`. Output: None.
    """
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
    """Verify open compat array requests v2 layout by default.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in open compat array requests v2 layout by default.
    """
    calls = []
    sentinel = object()

    def fake_open_array(path, **kwargs):
        """Simulate open array so the surrounding test controls that dependency.

        Inputs: `path` path, `**kwargs` keyword arguments. Output: `sentinel`.
        """
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
    """Verify open compat array retries without Zarr format when unsupported.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `object` result. Raises: TypeError when validation or external operations
    fail.
    """
    calls = []

    def fake_open_array(path, **kwargs):
        """Simulate open array so the surrounding test controls that dependency.

        Inputs: `path` path, `**kwargs` keyword arguments. Output: `object` result.
        Raises: TypeError when validation or the called operation fails.
        """
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
    """Verify open compat array retries without Zarr format when runtime warns.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `object` result. Raises: UserWarning when validation or external operations
    fail.
    """
    calls = []

    def fake_open_array(path, **kwargs):
        """Simulate open array so the surrounding test controls that dependency.

        Inputs: `path` path, `**kwargs` keyword arguments. Output: `object` result.
        Raises: UserWarning when validation or the called operation fails.
        """
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
    """Verify open compat array does not hide other type errors.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: None after assertions pass. Raises: TypeError for the exercised failure path.
    """

    def fake_open_array(path, **kwargs):
        """Simulate open array so the surrounding test controls that dependency.

        Inputs: `path` path, `**kwargs` keyword arguments. Output: None. Raises:
        TypeError when validation or the called operation fails.
        """
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
    """Verify the resolve local Zarr store accepts absolute path safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when resolve local Zarr store accepts absolute path accepts unsafe input.
    """
    _write_minimal_zarr_group(tmp_path)

    assert resolve_local_zarr_store(str(tmp_path)) == tmp_path.resolve()


def test_resolve_local_zarr_store_accepts_file_uri(tmp_path):
    """Verify resolve local Zarr store accepts file uri.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in resolve local Zarr store accepts file uri.
    """
    _write_minimal_zarr_group(tmp_path)

    assert resolve_local_zarr_store(tmp_path.resolve().as_uri()) == tmp_path.resolve()


def test_resolve_local_zarr_store_rejects_non_group_path(tmp_path):
    """Confirm resolve local Zarr store rejects non group path is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when resolve local Zarr store rejects non group path accepts unsafe input.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)

    assert resolve_local_zarr_store(str(tmp_path)) is None


def test_resolve_image_backing_zarr_store_queries_lsid_when_wrapper_details_are_incomplete(
    tmp_path, monkeypatch
):
    """Verify resolve image backing Zarr store queries lsid when wrapper details are incomplete.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in resolve image backing Zarr store queries lsid when wrapper details are incomplete.
    """

    class _FakeParametersI:
        """Test double for fake parameters i."""

        def addId(self, image_id):
            """Add the ID for `_FakeParametersI`.

            Inputs: `image_id` OMERO image ID. Output: `self`.
            """
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
    """Confirm resolve local Zarr file rejects parent traversal is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in resolve local Zarr file rejects parent traversal.
    """
    _write_minimal_zarr_group(tmp_path)

    with pytest.raises(Http404, match="zarr path not found"):
        resolve_local_zarr_file(tmp_path.resolve(), "..", "outside")


def test_resolve_local_zarr_file_accepts_nested_dataset_paths(tmp_path):
    """Verify resolve local Zarr file accepts nested dataset paths.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in resolve local Zarr file accepts nested dataset paths.
    """
    _write_minimal_zarr_group(tmp_path)
    nested = tmp_path / "s0" / ".zarray"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("{}", encoding="utf-8")

    assert (
        resolve_local_zarr_file(tmp_path.resolve(), "s0", ".zarray") == nested.resolve()
    )


def test_is_store_metadata_path_identifies_supported_metadata_files(tmp_path):
    """Verify the is store metadata path identifies supported metadata files safety boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions when is store metadata path identifies supported metadata files accepts unsafe input.
    """
    assert is_store_metadata_path(tmp_path / ".zattrs")
    assert is_store_metadata_path(tmp_path / ".zgroup")
    assert is_store_metadata_path(tmp_path / ".zarray")
    assert is_store_metadata_path(tmp_path / "zarr.json")
    assert not is_store_metadata_path(tmp_path / "0")


def test_collect_store_metadata_documents_includes_nested_metadata(tmp_path):
    """Verify collect store metadata documents includes nested metadata.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in collect store metadata documents includes nested metadata.
    """
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
    """Verify get store backed channel overrides prefers Zarr display metadata.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get store backed channel overrides prefers Zarr display metadata.
    """
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
    """Verify get store backed channel overrides falls back to channel windows.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in get store backed channel overrides falls back to channel windows.
    """
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
    """Check that load store backed image node preserves partial channel metadata alignment remains stable.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in load store backed image node preserves partial channel metadata alignment.
    """
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
    """Verify get safe image tile size falls back to configured maximum.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in get safe image tile size falls back to configured maximum.
    """
    image = _TileFailureImage(size_x=2048, size_y=512, max_tile_length=1024)

    assert get_safe_image_tile_size(image) == (1024, 512)


def test_sanitize_download_basename_normalizes_empty_and_path_like_names():
    """Check that sanitize download basename normalizes empty and path like names keeps sensitive data out of output.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions when sanitize download basename normalizes empty and path like names accepts unsafe input.
    """
    assert sanitize_download_basename("", default="fallback") == "fallback"
    assert (
        sanitize_download_basename("dir/name, with spaces.zarr")
        == "name._with_spaces.zarr"
    )


def test_select_store_backed_level_prefers_smallest_sufficient_level():
    """Verify select store backed level prefers smallest sufficient level.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in select store backed level prefers smallest sufficient level.
    """
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
    """Verify read store backed plane maps full resolution z to subresolution.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in read store backed plane maps full resolution z to subresolution.
    """
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
    """Verify render store backed plane composites visible channels.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in render store backed plane composites visible channels.
    """
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
    """Verify render store backed thumbnail bytes uses helper node.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in render store backed thumbnail bytes uses helper node.
    """
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
    """Verify render store backed pil image respects requested level.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in render store backed pil image respects requested level.
    """
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
    """Verify store backed level metadata uses multiscale shapes and chunks.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in store backed level metadata uses multiscale shapes and chunks.
    """
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
    """Verify render store backed region pil image crops requested level.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in render store backed region pil image crops requested level.
    """
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
    """Verify encode store backed pil image supports png and tiff.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in encode store backed pil image supports png and tiff.
    """
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
    """Verify generate coordinate transformations computes scales.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in generate coordinate transformations computes scales.
    """
    shapes = [(1, 1, 100, 200), (1, 1, 50, 100)]
    result = generate_coordinate_transformations(shapes)
    assert len(result) == 2
    assert result[0] == [{"type": "scale", "scale": [1.0, 1.0, 1.0, 1.0]}]
    assert result[1] == [{"type": "scale", "scale": [1.0, 1.0, 2.0, 2.0]}]


def test_generate_coordinate_transformations_rejects_dimension_mismatch():
    """Confirm generate coordinate transformations rejects dimension mismatch is rejected at the boundary.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in generate coordinate transformations rejects dimension mismatch.
    """
    shapes = [(1, 1, 100, 200), (1, 50, 100)]
    with pytest.raises(ValueError, match="Shape dimension mismatch"):
        generate_coordinate_transformations(shapes)


def test_marshal_axes_and_pixel_sizes_cover_supported_and_invalid_versions():
    """Verify marshal axes and pixel sizes cover supported and invalid versions.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in marshal axes and pixel sizes cover supported and invalid versions.
    """

    class _PixelSize:
        """Test double for pixel size behavior in this module."""

        def __init__(self, value, unit):
            """Create `_PixelSize` with `value` and `unit`.

            Inputs: `value`, `unit`. Output: None.
            """
            self._value = value
            self._unit = unit

        def getUnit(self):
            """Return the unit for `_PixelSize`.

            Inputs: none. Output: `_unit`.
            """
            return self._unit

        def getValue(self):
            """Return `_PixelSize`'s fake OMERO value.

            Inputs: none. Output: `self._value`.
            """
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
    """Verify resolve image external lsid covers missing IDs and query failures.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in resolve image external lsid covers missing IDs and query failures.
    """
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
    """Verify read store attrs and format resolution support Zarr JSON and v04.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in read store attrs and format resolution support Zarr JSON and v04.
    """
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
    """Verify load store backed image node reader and cache fallbacks.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in load store backed image node reader and cache fallbacks.
    """
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
        """Test double for missing store image behavior in this module."""

    missing_store_image = _MissingStoreImage()
    monkeypatch.setattr(
        "omero_web_zarr.utils.resolve_image_backing_zarr_store",
        lambda image: (_ for _ in ()).throw(OSError("gone")),
    )
    assert load_store_backed_image_node(missing_store_image) is None


def test_store_backed_dataset_and_render_helpers_cover_fallback_paths():
    """Verify store backed dataset and render helpers cover fallback paths.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in store backed dataset and render helpers cover fallback paths.
    """
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
    """Verify get safe image tile size prepares rendering engine and falls back.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in get safe image tile size prepares rendering engine and falls back.
    """

    class _PreparedEngine:
        """Test double for prepared engine behavior in this module."""

        @staticmethod
        def getTileSize():
            """Return the fake tile size value used by this test double.

            Inputs: none. Output: tuple.
            """
            return (64, 32)

    class _PreparedImage:
        """Test double for prepared image behavior in this module."""

        def __init__(self):
            """Create `_PreparedImage` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self._re = None

        def _prepareRenderingEngine(self):
            """Prepare the rendering Engine for `_PreparedImage`.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self._re = _PreparedEngine()

        @staticmethod
        def getSizeX():
            """Return `_PreparedImage`'s fake SizeX value.

            Inputs: none. Output: 512.
            """
            return 512

        @staticmethod
        def getSizeY():
            """Return `_PreparedImage`'s fake SizeY value.

            Inputs: none. Output: 256.
            """
            return 256

    assert get_safe_image_tile_size(_PreparedImage()) == (64, 32)

    class _BrokenEngine:
        """Test double for broken engine behavior in this module."""

        @staticmethod
        def getTileSize():
            """Return the fake tile size value used by this test double.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("not a tile-size failure")

    class _BrokenImage:
        """Test double for broken image behavior in this module."""

        _re = _BrokenEngine()

        @staticmethod
        def getSizeX():
            """Return `_BrokenImage`'s fake SizeX value.

            Inputs: none. Output: 512.
            """
            return 512

        @staticmethod
        def getSizeY():
            """Return `_BrokenImage`'s fake SizeY value.

            Inputs: none. Output: 256.
            """
            return 256

    with pytest.raises(RuntimeError, match="not a tile-size failure"):
        get_safe_image_tile_size(_BrokenImage())
