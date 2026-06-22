import os
import json
import re
import warnings
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import django
import numpy as np
import pytest
from django.http import Http404, HttpResponse
from django.test import RequestFactory
import tifffile

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

from omero_web_zarr import utils as zarr_utils
from omero_web_zarr import views

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _default_test_zarr_roots(monkeypatch):
    """Keep store-backed tests isolated from deployment-specific root allowlists.

    Inputs: pytest `monkeypatch`. Output: clears root allowlist environment.
    """
    monkeypatch.delenv("CONFIG_omero_managed_dir", raising=False)
    monkeypatch.delenv("OMERO_DATA_DIR", raising=False)
    monkeypatch.delenv("OMERO_WEB_ZARR_ALLOWED_STORE_ROOTS", raising=False)


def _response_text(response) -> str:
    """Return the response text.

    Inputs: `response` response object. Output: `str`.
    """
    return b"".join(response.streaming_content).decode("utf-8")


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self.val = value


class _ExternalInfo:
    """Test double for external info behavior in this module."""

    def __init__(self, lsid):
        """Create `_ExternalInfo` with `lsid`.

        Inputs: `lsid`. Output: None.
        """
        self.lsid = _Value(lsid)


class _Details:
    """Test double for details behavior in this module."""

    def __init__(self, lsid):
        """Create `_Details` with `lsid`.

        Inputs: `lsid`. Output: None.
        """
        self.externalInfo = _ExternalInfo(lsid)


class _FakeImage:
    """Test double for fake image."""

    def __init__(self, lsid, image_id=1, name="store-backed"):
        """Create `_FakeImage` with `lsid`, `image_id`, and `name`.

        Inputs: `lsid`, `image_id`, `name`. Output: None.
        """
        self._details = _Details(lsid)
        self.id = image_id
        self._name = name

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

    @staticmethod
    def getPixelSizeX(units=True):
        """Return `_FakeImage`'s fake physical X size.

        Inputs: `units`. Output: None.
        """
        return None

    @staticmethod
    def getPixelSizeY(units=True):
        """Return `_FakeImage`'s fake physical Y size.

        Inputs: `units`. Output: None.
        """
        return None

    @staticmethod
    def getPixelSizeZ(units=True):
        """Return `_FakeImage`'s fake physical Z size.

        Inputs: `units`. Output: None.
        """
        return None


class _FakeChunkImage:
    """Test double for fake chunk image."""

    @staticmethod
    def requiresPixelsPyramid():
        """Return whether the fake store-backed image requires a pyramid.

        Inputs: none. Output: bool.
        """
        return False

    @staticmethod
    def getSizeT():
        """Return `_FakeChunkImage`'s fake timepoint count.

        Inputs: none. Output: 1.
        """
        return 1

    @staticmethod
    def getSizeC():
        """Return `_FakeChunkImage`'s fake channel count.

        Inputs: none. Output: 1.
        """
        return 1

    @staticmethod
    def getSizeZ():
        """Return `_FakeChunkImage`'s fake SizeZ value.

        Inputs: none. Output: 1.
        """
        return 1

    @staticmethod
    def getSizeY():
        """Return `_FakeChunkImage`'s fake SizeY value.

        Inputs: none. Output: 512.
        """
        return 512

    @staticmethod
    def getSizeX():
        """Return `_FakeChunkImage`'s fake SizeX value.

        Inputs: none. Output: 1024.
        """
        return 1024


def _write_store(root):
    """Write the store.

    Inputs: `root`. Output: None.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (root / ".zattrs").write_text(
        json.dumps({"multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}]}),
        encoding="utf-8",
    )
    (root / "0").mkdir()
    (root / "0" / ".zarray").write_text(
        json.dumps({"shape": [1, 1, 2, 2], "chunks": [1, 1, 2, 2], "zarr_format": 2}),
        encoding="utf-8",
    )
    chunk_path = root / "0" / "0" / "0" / "0" / "0"
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_bytes(b"chunk-bytes")


def _write_multiscale_store(root):
    """Write a synthetic two-level OME-Zarr store.

    Inputs: `root`. Output: None.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    attrs = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [
                    {"name": "t", "type": "time"},
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space"},
                    {"name": "y", "type": "space"},
                    {"name": "x", "type": "space"},
                ],
                "datasets": [
                    {
                        "path": "native",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [1, 1, 1, 1, 1]}
                        ],
                    },
                    {
                        "path": "overview",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [1, 1, 1, 2, 2]}
                        ],
                    },
                ],
            }
        ],
        "omero": {"channels": []},
    }
    (root / ".zattrs").write_text(json.dumps(attrs), encoding="utf-8")

    for name, shape, payload in (
        ("native", [1, 1, 1, 4, 4], b"native-chunk"),
        ("overview", [1, 1, 1, 2, 2], b"overview-chunk"),
    ):
        level = root / name
        level.mkdir()
        (level / ".zarray").write_text(
            json.dumps(
                {
                    "shape": shape,
                    "chunks": shape,
                    "dtype": "|u1",
                    "compressor": None,
                    "filters": None,
                    "order": "C",
                    "dimension_separator": "/",
                    "zarr_format": 2,
                }
            ),
            encoding="utf-8",
        )
        chunk_path = level / "0" / "0" / "0" / "0" / "0"
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_path.write_bytes(payload)


def test_store_backed_json_response_returns_canonical_metadata(tmp_path):
    """Verify store backed JSON response returns canonical metadata result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in store backed JSON response returns canonical metadata.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))

    response = views._store_backed_json_response(image, "0.4", ".zattrs")

    assert response is not None
    assert json.loads(response.content) == {
        "multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}]
    }


def test_resolve_local_zarr_store_requires_allowed_root(tmp_path, monkeypatch):
    """Check externalInfo.lsid paths are constrained to configured roots.

    Inputs: pytest `tmp_path` and `monkeypatch`. Output: asserts deny/allow behavior.
    """
    allowed = tmp_path / "allowed.zarr"
    denied = tmp_path / "denied.zarr"
    _write_store(allowed)
    _write_store(denied)
    monkeypatch.setenv(
        "OMERO_WEB_ZARR_ALLOWED_STORE_ROOTS",
        str(allowed.resolve()),
    )

    assert zarr_utils.resolve_local_zarr_store(str(allowed.resolve())) == (
        allowed.resolve()
    )
    assert zarr_utils.resolve_local_zarr_store(str(denied.resolve())) is None


def test_store_backed_json_response_skips_non_v04_requests(tmp_path):
    """Verify store backed JSON response skips non v04 requests result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in store backed JSON response skips non v04 requests.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))

    assert views._store_backed_json_response(image, "0.3", ".zattrs") is None


def test_store_backed_chunk_response_returns_exact_chunk_bytes(tmp_path):
    """Verify store backed chunk response returns exact chunk bytes result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in store backed chunk response returns exact chunk bytes.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))

    response = views._store_backed_chunk_response(image, "0.4", 0, "0/0/0/0")

    assert response is not None
    assert response.content == b"chunk-bytes"
    assert response["Content-Disposition"] == "attachment; filename=0.0.0.0"


def test_store_backed_response_supports_non_numeric_dataset_paths(tmp_path):
    """Verify store backed response supports non numeric dataset paths result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in store backed response supports non numeric dataset paths.
    """
    _write_store(tmp_path)
    (tmp_path / "s0").mkdir()
    (tmp_path / "s0" / ".zarray").write_text(
        json.dumps({"shape": [1, 1, 2, 2], "chunks": [1, 1, 2, 2], "zarr_format": 2}),
        encoding="utf-8",
    )
    image = _FakeImage(str(tmp_path.resolve()))

    response = views._store_backed_response(image, "0.4", "s0", ".zarray")

    assert response is not None
    assert json.loads(response.content)["zarr_format"] == 2


def test_build_store_backed_preview_context_points_to_omero_zarr_endpoints(
    tmp_path, monkeypatch
):
    """Verify build store backed preview context points to OMERO Zarr endpoints.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `str`. Raises: AssertionError when validation or the called operation fails.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=502, name="10150")

    def fake_reverse(name, args=None, kwargs=None):
        """Simulate reverse so the surrounding test controls that dependency.

        Inputs: `name` name, `args` positional arguments, `kwargs` keyword arguments.
        Output: `str`. Raises: AssertionError when validation or external operations
        fail.
        """
        if name == "omero_web_zarr_index":
            return "/zarr/"
        if name == "render_thumbnail":
            return f"/webclient/render_thumbnail/{args[0]}/"
        if name == "zarr_app":
            return f"/zarr/{kwargs['app']}/"
        raise AssertionError(f"Unexpected reverse() call: {name}")

    monkeypatch.setattr(
        views,
        "reverse",
        fake_reverse,
    )

    context = views._build_store_backed_preview_context(None, image)

    assert context["image"] is image
    assert context["thumbnail_url"].endswith("/webclient/render_thumbnail/502/")
    assert "source=/zarr/v0.4/preview/image/502.zarr" in context["vizarr_url"]
    assert "source=/zarr/v0.4/image/502.zarr" in context["validator_url"]


def test_preview_image_zattrs_preserves_store_backed_raw_multiscales(
    tmp_path, monkeypatch
):
    """Check that preview image zattrs preserves store backed raw multiscales remains stable.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in preview image zattrs preserves store backed raw multiscales.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=12, name="pyramid.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/12.zarr/.zattrs")
    root_payload = {
        "multiscales": [
            {
                "version": "0.4",
                "datasets": [
                    {
                        "path": "s0",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [1, 1, 1]}
                        ],
                    },
                    {
                        "path": "s1",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [2, 2, 2]}
                        ],
                    },
                ],
            }
        ],
        "omero": {"channels": []},
    }
    monkeypatch.setattr(
        views,
        "_store_backed_json_response",
        lambda image, version, *parts: HttpResponse(
            json.dumps(root_payload),
            content_type="application/json",
        ),
    )

    response = views.preview_image_zattrs.__wrapped__(
        request, 12, conn=_FakeConn(image)
    )

    assert response.status_code == 200
    assert json.loads(response.content) == root_payload


def test_preview_routes_serve_store_backed_multiscale_levels_without_remapping(
    tmp_path,
):
    """Verify preview routes expose every store-backed multiscale level.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in preview
    route handling for non-numeric native multiscale dataset paths.
    """
    _write_multiscale_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=46, name="synthetic.ome.zarr")
    conn = _FakeConn(image)

    zattrs_response = views.preview_image_zattrs.__wrapped__(
        RequestFactory().get("/zarr/v0.4/preview/image/46.zarr/.zattrs"),
        46,
        conn=conn,
    )
    zattrs = json.loads(zattrs_response.content)

    assert [item["path"] for item in zattrs["multiscales"][0]["datasets"]] == [
        "native",
        "overview",
    ]
    assert zattrs["multiscales"][0]["datasets"][1]["coordinateTransformations"] == [
        {"type": "scale", "scale": [1, 1, 1, 2, 2]}
    ]

    native_zarray = views.preview_image_store_path.__wrapped__(
        RequestFactory().get("/zarr/v0.4/preview/image/46.zarr/native/.zarray"),
        46,
        store_path="native/.zarray",
        conn=conn,
    )
    overview_zarray = views.preview_image_store_path.__wrapped__(
        RequestFactory().get("/zarr/v0.4/preview/image/46.zarr/overview/.zarray"),
        46,
        store_path="overview/.zarray",
        conn=conn,
    )

    assert json.loads(native_zarray.content)["shape"] == [1, 1, 1, 4, 4]
    assert json.loads(overview_zarray.content)["shape"] == [1, 1, 1, 2, 2]

    native_chunk = views.preview_image_store_path.__wrapped__(
        RequestFactory().get("/zarr/v0.4/preview/image/46.zarr/native/0/0/0/0/0"),
        46,
        store_path="native/0/0/0/0/0",
        conn=conn,
    )
    overview_chunk = views.preview_image_store_path.__wrapped__(
        RequestFactory().get("/zarr/v0.4/preview/image/46.zarr/overview/0/0/0/0/0"),
        46,
        store_path="overview/0/0/0/0/0",
        conn=conn,
    )

    assert native_chunk.content == b"native-chunk"
    assert overview_chunk.content == b"overview-chunk"


def test_get_chunk_shape_preserves_yx_order_for_non_pyramid_images():
    """Check that get chunk shape preserves yx order for non pyramid images remains stable.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in get chunk shape preserves yx order for non pyramid images.
    """
    assert views.get_chunk_shape(_FakeChunkImage()) == [512, 1024]


class _FakeConn:
    """Test double for fake conn."""

    def __init__(self, image):
        """Create `_FakeConn` with `image`.

        Inputs: `image`. Output: None.
        """
        self._image = image
        self.c = None

    def getObject(self, object_type, iid):
        """Return the object for `_FakeConn`.

        Inputs: `object_type`, `iid`. Output: `_image`.
        """
        assert object_type == "Image"
        assert iid == self._image.id
        return self._image


def test_preview_image_zarray_delegates_to_raw_endpoint(monkeypatch):
    """Verify preview image zarray delegates to raw endpoint.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in preview image zarray delegates to raw endpoint.
    """
    image = _FakeImage("/managed/demo.ome.zarr", image_id=43, name="managed.ome.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/43.zarr/0/.zarray")
    sentinel = HttpResponse('{"zarr_format": 2}', content_type="application/json")
    captured = {}
    conn = _FakeConn(image)

    def fake_image_zarray(request, iid, level, conn=None, **kwargs):
        """Simulate image zarray so the surrounding test controls that dependency.

        Inputs: `request` Django request, `iid`, `level`, `conn` OMERO gateway
        connection, `**kwargs` keyword arguments. Output: `sentinel`.
        """
        captured["call"] = (request, iid, level, conn, kwargs)
        return sentinel

    monkeypatch.setattr(views, "image_zarray", fake_image_zarray)

    response = views.preview_image_zarray.__wrapped__(request, 43, 0, conn=conn)

    assert response is sentinel
    assert captured["call"][1:4] == (43, 0, conn)


def test_preview_image_chunk_delegates_to_raw_endpoint(monkeypatch):
    """Verify preview image chunk delegates to raw endpoint.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in preview image chunk delegates to raw endpoint.
    """
    image = _FakeImage("/managed/demo.ome.zarr", image_id=44, name="managed.ome.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/44.zarr/0/0/0/0/0")
    sentinel = HttpResponse(b"store-chunk", content_type="application/octet-stream")
    captured = {}
    conn = _FakeConn(image)

    def fake_image_chunk(request, iid, level, chunk, conn=None, **kwargs):
        """Simulate image chunk so the surrounding test controls that dependency.

        Inputs: `request` Django request, `iid`, `level`, `chunk`, `conn` OMERO gateway
        connection, `**kwargs` keyword arguments. Output: `sentinel`.
        """
        captured["call"] = (request, iid, level, chunk, conn, kwargs)
        return sentinel

    monkeypatch.setattr(views, "image_chunk", fake_image_chunk)

    response = views.preview_image_chunk.__wrapped__(
        request, 44, 0, "0/0/0/0", conn=conn
    )

    assert response is sentinel
    assert captured["call"][1:5] == (44, 0, "0/0/0/0", conn)


def test_preview_image_store_path_delegates_to_raw_endpoint(monkeypatch):
    """Verify the preview image store path delegates to raw endpoint safety boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions when preview image store path delegates to raw endpoint accepts unsafe input.
    """
    image = _FakeImage("/managed/demo.ome.zarr", image_id=45, name="managed.ome.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/45.zarr/s1/.zarray")
    sentinel = HttpResponse('{"zarr_format": 2}', content_type="application/json")
    captured = {}
    conn = _FakeConn(image)

    def fake_image_store_path(request, iid, version, store_path, conn=None, **kwargs):
        """Simulate image store path so the surrounding test controls that dependency.

        Inputs: `request` Django request, `iid`, `version`, `store_path`, `conn` OMERO
        gateway connection, `**kwargs` keyword arguments. Output: `sentinel`.
        """
        captured["call"] = (request, iid, version, store_path, conn, kwargs)
        return sentinel

    monkeypatch.setattr(views, "image_store_path", fake_image_store_path)

    response = views.preview_image_store_path.__wrapped__(
        request,
        45,
        store_path="s1/.zarray",
        conn=conn,
    )

    assert response is sentinel
    assert captured["call"][1:5] == (45, "0.4", "s1/.zarray", conn)


def test_download_store_metadata_returns_json_manifest(tmp_path):
    """Verify download store metadata returns JSON manifest result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in download store metadata returns JSON manifest.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=7, name="demo.zarr")
    request = RequestFactory().get("/zarr/download/image/7/metadata/")

    response = views.download_store_metadata(request, 7, conn=_FakeConn(image))

    payload = json.loads(response.content)
    assert (
        response["Content-Disposition"]
        == "attachment; filename=demo.zarr-metadata.json"
    )
    assert payload["store"] == tmp_path.name
    assert payload["documents"][".zattrs"]["multiscales"][0]["datasets"] == [
        {"path": "0"}
    ]


def test_download_store_original_returns_zip_file(tmp_path):
    """Verify download store original returns zip file result shape.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in download store original returns zip file.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=8, name="demo.zarr")
    request = RequestFactory().get("/zarr/download/image/8/original/")

    response = views.download_store_original(request, 8, conn=_FakeConn(image))
    try:
        payload = b"".join(response.streaming_content)

        assert response["Content-Disposition"] == 'attachment; filename="demo.zarr.zip"'
        with zipfile.ZipFile(BytesIO(payload), "r") as zf:
            assert sorted(zf.namelist()) == [
                f"{tmp_path.name}/.zattrs",
                f"{tmp_path.name}/.zgroup",
                f"{tmp_path.name}/0/.zarray",
                f"{tmp_path.name}/0/0/0/0/0",
            ]
    finally:
        response.close()


def test_download_store_original_skips_symlink_escape(tmp_path):
    """Check store ZIP creation does not follow symlinks outside the store root.

    Inputs: pytest `tmp_path`. Output: asserts escaped file content is absent.
    """
    _write_store(tmp_path)
    outside_file = tmp_path.parent / "outside-secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    link_path = tmp_path / "escaped.txt"
    try:
        link_path.symlink_to(outside_file)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    image = _FakeImage(str(tmp_path.resolve()), image_id=18, name="demo.zarr")
    request = RequestFactory().get("/zarr/download/image/18/original/")

    response = views.download_store_original(request, 18, conn=_FakeConn(image))
    try:
        payload = b"".join(response.streaming_content)
        with zipfile.ZipFile(BytesIO(payload), "r") as zf:
            assert f"{tmp_path.name}/escaped.txt" not in zf.namelist()
            assert b"secret" not in payload
    finally:
        response.close()


def test_download_store_original_enforces_file_count_limit(tmp_path, monkeypatch):
    """Check store ZIP creation stops before unbounded materialization.

    Inputs: pytest `tmp_path` and `monkeypatch`. Output: asserts limit rejection.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=19, name="demo.zarr")
    request = RequestFactory().get("/zarr/download/image/19/original/")
    monkeypatch.setenv("OMERO_WEB_ZARR_DOWNLOAD_MAX_FILES", "1")

    with pytest.raises(Http404, match="size limits"):
        views.download_store_original(request, 19, conn=_FakeConn(image))


def test_download_store_ome_tiff_returns_ome_tiff_file(tmp_path, monkeypatch):
    """Verify download store ome tiff returns ome tiff file result shape.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in download store ome tiff returns ome tiff file.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=9, name="demo.zarr")
    request = RequestFactory().get("/zarr/download/image/9/ome-tiff/")
    fake_node = type(
        "FakeNode",
        (),
        {
            "data": [np.arange(4, dtype=np.uint16).reshape(1, 1, 2, 2)],
            "metadata": {
                "axes": [
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space"},
                    {"name": "y", "type": "space"},
                    {"name": "x", "type": "space"},
                ],
                "channel_names": ["C00"],
            },
        },
    )()
    monkeypatch.setattr(views, "load_store_backed_image_node", lambda image: fake_node)

    response = views.download_store_ome_tiff(request, 9, conn=_FakeConn(image))
    try:
        payload = b"".join(response.streaming_content)

        assert (
            response["Content-Disposition"]
            == 'attachment; filename="demo.zarr.ome.tif"'
        )
        with tifffile.TiffFile(BytesIO(payload)) as tif:
            assert tif.is_ome
            assert tif.series[0].shape == (2, 2)
            assert 'SizeC="1"' in tif.ome_metadata
            assert 'SizeZ="1"' in tif.ome_metadata
    finally:
        response.close()


def test_download_store_ome_tiff_enforces_source_size_limit(tmp_path, monkeypatch):
    """Check OME-TIFF export rejects oversized source arrays before writing.

    Inputs: pytest `tmp_path` and `monkeypatch`. Output: asserts limit rejection.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=20, name="demo.zarr")
    request = RequestFactory().get("/zarr/download/image/20/ome-tiff/")
    fake_node = type(
        "FakeNode",
        (),
        {
            "data": [np.arange(4, dtype=np.uint16).reshape(1, 1, 2, 2)],
            "metadata": {
                "axes": [
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space"},
                    {"name": "y", "type": "space"},
                    {"name": "x", "type": "space"},
                ],
            },
        },
    )()
    monkeypatch.setattr(views, "load_store_backed_image_node", lambda image: fake_node)
    monkeypatch.setenv("OMERO_WEB_ZARR_OME_TIFF_MAX_SOURCE_BYTES", "1")

    with pytest.raises(Http404, match="size limits"):
        views.download_store_ome_tiff(request, 20, conn=_FakeConn(image))


def test_download_store_ome_tiff_cleans_up_temp_file_when_writer_fails(
    tmp_path,
    monkeypatch,
):
    """Confirm download store ome tiff cleans up temp file when writer fails exposes the expected failure.

    Inputs: `tmp_path` temporary path fixture, `monkeypatch` pytest monkeypatch fixture.
    Output: `self`. Raises: RuntimeError when validation or the called operation fails.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=10, name="broken.zarr")
    request = RequestFactory().get("/zarr/download/image/10/ome-tiff/")
    fake_node = type(
        "FakeNode",
        (),
        {
            "data": [np.arange(4, dtype=np.uint16).reshape(1, 1, 2, 2)],
            "metadata": {
                "axes": [
                    {"name": "c", "type": "channel"},
                    {"name": "z", "type": "space"},
                    {"name": "y", "type": "space"},
                    {"name": "x", "type": "space"},
                ],
            },
        },
    )()
    target_path = tmp_path / "broken-output.ome.tif"

    class _NamedTempFile:
        """Test double for named temp file behavior in this module."""

        def __init__(self, path):
            """Create `_NamedTempFile` with `path`.

            Inputs: `path`. Output: None.
            """
            self.name = str(path)
            path.write_bytes(b"temp")

        @staticmethod
        def close():
            """Close `_NamedTempFile`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            return None

    class _FailingWriter:
        """Test double for failing writer behavior in this module."""

        def __init__(self, *_args, **_kwargs):
            """Create `_FailingWriter` with its default state.

            Inputs: `*_args`, `**_kwargs`. Output: None.
            """
            return None

        def __enter__(self):
            """Enter `_FailingWriter`'s context-managed fake resource.

            Inputs: none. Output: `self`.
            """
            return self

        def __exit__(self, exc_type, exc, tb):
            """Exit `_FailingWriter`'s context-managed fake resource.

            Inputs: `exc_type`, `exc`, `tb`. Output: bool.
            """
            return False

        @staticmethod
        def write(*_args, **_kwargs):
            """Write data to the resource.

            Inputs: `*_args`, `**_kwargs`. Output: None. Raises: RuntimeError when validation or the called operation fails.
            """
            raise RuntimeError("writer failed")

    monkeypatch.setattr(
        views, "load_store_backed_image_node", lambda current: fake_node
    )
    monkeypatch.setattr(
        views.tempfile,
        "NamedTemporaryFile",
        lambda *args, **kwargs: _NamedTempFile(target_path),
    )
    monkeypatch.setattr(views.tifffile, "TiffWriter", _FailingWriter)

    with pytest.raises(RuntimeError, match="writer failed"):
        views.download_store_ome_tiff(request, 10, conn=_FakeConn(image))
    assert target_path.exists() is False


def test_apps_serves_pinned_local_vizarr_shell_and_redirects_assets(monkeypatch):
    """Verify apps serves pinned local Vizarr shell and redirects assets.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in apps serves pinned local vizarr shell and redirects assets.
    """
    views._read_local_app_shell.cache_clear()
    views._fetch_remote_app_shell.cache_clear()
    monkeypatch.setattr(
        views.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("Vizarr shell must be local"),
    )

    shell_request = RequestFactory().get(
        "/zarr/vizarr/", {"source": "/zarr/v0.4/image/9.zarr"}
    )
    shell_response = views.apps(shell_request, "vizarr", "")
    shell_html = _response_text(shell_response)
    base_url = views._APP_BASE_URLS["vizarr"]

    assert shell_response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{40}", views.VIZARR_UPSTREAM_COMMIT)
    assert base_url.endswith(
        f"omero_web_zarr/vendor/vizarr/{views.VIZARR_UPSTREAM_COMMIT}/"
    )
    assert f'<base href="{base_url}">' in shell_html
    assert "https://hms-dbmi.github.io/vizarr/" not in shell_html
    assert "window.location.origin" in shell_html
    assert "history.replaceState" in shell_html
    assert shell_response["Cache-Control"] == "private, max-age=300"

    script_match = re.search(r'<script[^>]+src="\./([^"]+\.js)"', shell_html)
    assert script_match is not None
    script_name = script_match.group(1)

    asset_request = RequestFactory().get(f"/zarr/vizarr/{script_name}")
    asset_response = views.apps(asset_request, "vizarr", script_name)

    assert asset_response.status_code == 302
    assert asset_response["Location"] == f"{base_url}{script_name}"


def test_vizarr_static_pin_has_single_current_build():
    """Verify Vizarr static pin has single current build.

    Inputs: repository files. Output: fails on stale or duplicate Vizarr bundles.
    """
    vendor_root = REPO_ROOT / "third_party"
    commit_dirs = sorted(
        path.name.removeprefix("vizarr-")
        for path in vendor_root.glob("vizarr-*")
        if path.is_dir()
    )

    assert len(commit_dirs) == 1
    assert re.fullmatch(r"[0-9a-f]{40}", commit_dirs[0])
    assert commit_dirs == [views.VIZARR_UPSTREAM_COMMIT]

    package_static_root = REPO_ROOT / "omero_web_zarr/static/omero_web_zarr/vendor"
    assert not package_static_root.exists()

    build_root = vendor_root / f"vizarr-{views.VIZARR_UPSTREAM_COMMIT}" / "dist"
    filenames = {path.name for path in build_root.iterdir() if path.is_file()}
    assert "index.html" in filenames
    assert any(name.startswith("index-") and name.endswith(".js") for name in filenames)
    assert any(
        name.startswith("vizarr-") and name.endswith(".js") for name in filenames
    )
    assert not any(name.endswith(".map") for name in filenames)
    assert not any(
        "sourceMappingURL" in path.read_text(encoding="utf-8")
        for path in build_root.glob("*.js")
    )

    index_html = (build_root / "index.html").read_text(encoding="utf-8")
    assert "https://hms-dbmi.github.io/vizarr/" not in index_html
    assert "v0.3" not in index_html

    patch_root = vendor_root / f"vizarr-{views.VIZARR_UPSTREAM_COMMIT}" / "patches"
    patch_text = (patch_root / "omero-linear-intensity-interpolation.patch").read_text(
        encoding="utf-8"
    )
    assert "labels.includes(RGBA_CHANNEL_AXIS_NAME)" in patch_text
    assert 'interpolation: "linear"' in patch_text

    bundle_text = "\n".join(
        path.read_text(encoding="utf-8") for path in build_root.glob("vizarr-*.js")
    )
    assert "renderSubLayers:" in bundle_text
    assert "interpolation:`linear`" in bundle_text


def test_local_app_static_helpers_cover_runtime_packaging_edges(monkeypatch):
    """Verify local app static helpers cover runtime packaging edges.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in local Vizarr static helper path resolution.
    """
    monkeypatch.setattr(views, "static", lambda static_path: "https://cdn.invalid/app/")
    assert views._local_static_url("unused") == "https://cdn.invalid/app/"

    monkeypatch.setattr(views, "static", lambda static_path: "static/app/")
    assert views._local_static_url("unused") == "/static/app/"

    package_asset = views._local_app_shell_path("omero_web_zarr/openwith.js")
    assert package_asset.is_file()

    invalid_asset = views._local_app_shell_path(
        f"{views._VIZARR_STATIC_PREFIX}../index.html"
    )
    assert invalid_asset == (
        Path(views.__file__).resolve().parent
        / "static"
        / f"{views._VIZARR_STATIC_PREFIX}../index.html"
    )

    missing_asset = views._local_app_shell_path(
        f"{views._VIZARR_STATIC_PREFIX}missing.html"
    )
    assert missing_asset == (
        Path(views.__file__).resolve().parent
        / "static"
        / f"{views._VIZARR_STATIC_PREFIX}missing.html"
    )


def test_vizarr_vendor_discovery_requires_one_valid_build(monkeypatch, tmp_path):
    """Verify Vizarr vendor discovery accepts one valid build and rejects none.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in Vizarr vendor discovery.
    """
    source_root = tmp_path / "source"
    package_root = tmp_path / "package"
    source_module = source_root / "omero_web_zarr" / "views.py"
    package_module = package_root / "omero_web_zarr" / "views.py"
    source_module.parent.mkdir(parents=True)
    package_module.parent.mkdir(parents=True)
    source_module.touch()
    package_module.touch()

    monkeypatch.setattr(views, "__file__", str(source_module))
    assert views._source_tree_vizarr_dist_dir() is None

    commit = "a" * 40
    source_dist = source_root / "third_party" / f"vizarr-{commit}" / "dist"
    source_dist.mkdir(parents=True)
    (source_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    assert views._source_tree_vizarr_dist_dir() == source_dist

    package_static_dir = (
        package_module.parent
        / "static"
        / "omero_web_zarr"
        / "vendor"
        / "vizarr"
        / commit
    )
    package_static_dir.mkdir(parents=True)
    (package_static_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(views, "__file__", str(package_module))
    assert views._package_vizarr_static_dir() == package_static_dir


def test_vizarr_vendor_commit_prefers_package_and_fails_when_missing(
    monkeypatch, tmp_path
):
    """Verify Vizarr vendor commit discovery order and failure mode.

    Inputs: pytest provides `monkeypatch`, `tmp_path`. Output: fails on regressions in Vizarr vendor commit discovery.
    """
    commit = "b" * 40
    package_static_dir = tmp_path / commit
    package_static_dir.mkdir()

    monkeypatch.setattr(views, "_package_vizarr_static_dir", lambda: package_static_dir)
    monkeypatch.setattr(
        views,
        "_source_tree_vizarr_dist_dir",
        lambda: pytest.fail("packaged Vizarr build should be preferred"),
    )
    assert views._vizarr_vendor_commit() == commit

    monkeypatch.setattr(views, "_package_vizarr_static_dir", lambda: None)
    monkeypatch.setattr(views, "_source_tree_vizarr_dist_dir", lambda: None)
    with pytest.raises(RuntimeError, match="Exactly one pinned vendored Vizarr build"):
        views._vizarr_vendor_commit()


def test_apps_fetches_remote_validator_shell(monkeypatch):
    """Verify apps fetches remote validator shell.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in apps fetches remote validator shell.
    """

    class _FakeResponse:
        """Test double for fake response."""

        text = "<html><head></head><body>validator</body></html>"

        @staticmethod
        def raise_for_status():
            """Raise the configured HTTP error for this fake response.

            Inputs: caller provides no extra arguments. Output: None.
            """
            return None

    views._fetch_remote_app_shell.cache_clear()
    monkeypatch.setattr(views.requests, "get", lambda url, timeout=20: _FakeResponse())

    response = views.apps(RequestFactory().get("/zarr/validator/"), "validator", "")
    html = _response_text(response)

    assert '<base href="https://ome.github.io/ome-ngff-validator/">' in html


def test_inject_launcher_head_replaces_existing_base_tag():
    """Verify inject launcher head replaces existing base tag.

    Inputs: Zarr and OMERO fakes. Output: fails on regressions in inject launcher head replaces existing base tag.
    """
    html = '<html><head><base href="https://stale.example/"></head><body>validator</body></html>'

    updated = views._inject_launcher_head(
        html, "https://ome.github.io/ome-ngff-validator/"
    )

    assert "https://stale.example/" not in updated
    assert '<base href="https://ome.github.io/ome-ngff-validator/">' in updated
    assert updated.count("<base ") == 1
    assert "window.location.origin" in updated


def test_build_app_launch_url_preserves_vizarr_source_variants(monkeypatch):
    """Verify build app launch URL preserves Vizarr source variants.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in build app launch URL preserves Vizarr source variants.
    """
    monkeypatch.setattr(
        views,
        "reverse",
        lambda name, kwargs=None: f"/zarr/{kwargs['app']}/",
    )

    sources = (
        "/zarr/v0.4/image/1101.zarr",
        "https://example.org/data/sample.ome.zarr",
        "https://example.org/data/sample.ome.zarr?token=a=b&profile=rgb#frag",
        "ome-tiff://https://example.org/data/sample.ome.tif?series=0&channel=1",
        "ref://https://example.org/data/reference.json?key=a+b&space=x y",
    )

    for source in sources:
        launch_url = views._build_app_launch_url("vizarr", source)
        parsed = urlsplit(launch_url)

        assert parsed.path == "/zarr/vizarr/"
        assert parse_qs(parsed.query) == {"source": [source]}

    assert "%26profile%3Drgb%23frag" in views._build_app_launch_url(
        "vizarr", sources[2]
    )


def test_store_backed_views_cover_missing_paths_and_preview_routes(
    tmp_path, monkeypatch
):
    """Verify store backed views cover missing paths and preview routes.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in store backed views cover missing paths and preview routes.
    """
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=13, name="demo.zarr")

    monkeypatch.setattr(views, "resolve_image_backing_zarr_store", lambda current: None)
    assert views._store_backed_response(image, "0.4", ".zattrs") is None
    assert views._store_backed_chunk_response(image, "0.4", 0, "0/0/0/0") is None

    monkeypatch.setattr(
        views,
        "resolve_image_backing_zarr_store",
        lambda current: tmp_path.resolve(),
    )
    with pytest.raises(Http404):
        views._store_backed_json_response(image, "0.4", "0", "0", "0", "0", "0")

    zgroup = views.image_zgroup(
        RequestFactory().get("/zarr/v0.4/image/13.zarr/.zgroup"),
        iid=13,
        version="0.4",
        conn=_FakeConn(image),
    )
    assert json.loads(zgroup.content) == {"zarr_format": 2}

    sentinel = HttpResponse('{"zarr_format": 2}', content_type="application/json")
    monkeypatch.setattr(views, "image_zgroup", lambda *args, **kwargs: sentinel)
    assert (
        views.preview_image_zgroup.__wrapped__(
            RequestFactory().get("/zarr/v0.4/preview/image/13.zarr/.zgroup"),
            13,
            conn=_FakeConn(image),
        )
        is sentinel
    )

    monkeypatch.setattr(views, "_store_backed_response", lambda *args, **kwargs: None)
    with pytest.raises(Http404):
        views.image_store_path.__wrapped__(
            RequestFactory().get("/zarr/v0.4/image/13.zarr/missing"),
            13,
            "0.4",
            "missing",
            conn=_FakeConn(image),
        )


def test_image_preview_and_download_views_cover_missing_store_backed_images(
    tmp_path, monkeypatch
):
    """Verify image preview and download views cover missing store backed images.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in image preview and download views cover missing store backed images.
    """
    request = RequestFactory().get("/zarr/preview/image/14/")
    missing_conn = SimpleNamespace(getObject=lambda object_type, iid: None)
    with pytest.raises(Http404):
        views.image_preview.__wrapped__(request, 14, conn=missing_conn)

    image = _FakeImage(str(tmp_path.resolve()), image_id=14, name="demo.zarr")
    monkeypatch.setattr(views, "resolve_image_backing_zarr_store", lambda current: None)
    monkeypatch.setattr(
        views,
        "reverse",
        lambda name, kwargs=None, args=None: (
            f"/webclient/preview/{kwargs['c_id']}/"
            if name == "load_metadata_preview"
            else "/zarr/"
        ),
    )
    redirect_response = views.image_preview.__wrapped__(
        request, 14, conn=_FakeConn(image)
    )
    assert redirect_response.status_code == 302
    assert redirect_response["Location"] == "/webclient/preview/14/"

    monkeypatch.setattr(
        views,
        "_build_store_backed_preview_context",
        lambda current_request, current_image: {"image_name": current_image.getName()},
    )
    monkeypatch.setattr(
        views,
        "render",
        lambda current_request, template, context: HttpResponse(
            json.dumps(context),
            content_type="application/json",
        ),
    )
    monkeypatch.setattr(
        views,
        "resolve_image_backing_zarr_store",
        lambda current: tmp_path.resolve(),
    )
    rendered = views.image_preview.__wrapped__(request, 14, conn=_FakeConn(image))
    assert json.loads(rendered.content) == {"image_name": "demo.zarr"}

    with pytest.raises(Http404):
        views.download_store_original(request, 14, conn=missing_conn)
    with pytest.raises(Http404):
        views.download_store_metadata(request, 14, conn=missing_conn)
    with pytest.raises(Http404):
        views.download_store_ome_tiff(request, 14, conn=missing_conn)

    monkeypatch.setattr(views, "resolve_image_backing_zarr_store", lambda current: None)
    with pytest.raises(Http404):
        views.download_store_original(request, 14, conn=_FakeConn(image))
    with pytest.raises(Http404):
        views.download_store_metadata(request, 14, conn=_FakeConn(image))

    monkeypatch.setattr(
        views,
        "resolve_image_backing_zarr_store",
        lambda current: tmp_path.resolve(),
    )
    monkeypatch.setattr(views, "load_store_backed_image_node", lambda current: None)
    with pytest.raises(Http404):
        views.download_store_ome_tiff(request, 14, conn=_FakeConn(image))


def test_app_shell_helpers_cover_empty_paths_cache_fetch_and_invalid_apps(monkeypatch):
    """Verify app shell helpers cover empty paths cache fetch and invalid apps.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in app shell helpers cover empty paths cache fetch and invalid apps.
    """
    assert views._sanitize_app_asset_path("") == ""
    injected = views._inject_launcher_head(
        "validator",
        "https://ome.github.io/ome-ngff-validator/",
    )
    assert injected.startswith(
        '<base href="https://ome.github.io/ome-ngff-validator/">'
    )

    events = []

    class _FakeShellResponse:
        """Test double for fake shell response."""

        text = "<html>validator</html>"

        @staticmethod
        def raise_for_status():
            """Raise the configured HTTP error for this fake response.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            events.append("raise_for_status")

    views._fetch_remote_app_shell.cache_clear()
    monkeypatch.setattr(
        views.requests,
        "get",
        lambda url, timeout=20: _FakeShellResponse(),
    )
    assert (
        views._fetch_remote_app_shell("https://ome.github.io/ome-ngff-validator/", 1)
        == "<html>validator</html>"
    )
    assert events == ["raise_for_status"]

    with pytest.raises(Http404):
        views.apps(RequestFactory().get("/zarr/unknown/"), "unknown", "")
