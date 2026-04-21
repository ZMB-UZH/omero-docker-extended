import os
import json
import warnings
import zipfile
from io import BytesIO
from types import SimpleNamespace

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

from omero_web_zarr import views


def _response_text(response) -> str:
    return b"".join(response.streaming_content).decode("utf-8")


class _Value:
    def __init__(self, value):
        self.val = value


class _ExternalInfo:
    def __init__(self, lsid):
        self.lsid = _Value(lsid)


class _Details:
    def __init__(self, lsid):
        self.externalInfo = _ExternalInfo(lsid)


class _FakeImage:
    def __init__(self, lsid, image_id=1, name="store-backed"):
        self._details = _Details(lsid)
        self.id = image_id
        self._name = name

    def getDetails(self):
        return self._details

    def getName(self):
        return self._name

    @staticmethod
    def getPixelSizeX(units=True):
        return None

    @staticmethod
    def getPixelSizeY(units=True):
        return None

    @staticmethod
    def getPixelSizeZ(units=True):
        return None


class _FakeChunkImage:
    @staticmethod
    def requiresPixelsPyramid():
        return False

    @staticmethod
    def getSizeT():
        return 1

    @staticmethod
    def getSizeC():
        return 1

    @staticmethod
    def getSizeZ():
        return 1

    @staticmethod
    def getSizeY():
        return 512

    @staticmethod
    def getSizeX():
        return 1024


def _write_store(root):
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


def test_store_backed_json_response_returns_canonical_metadata(tmp_path):
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))

    response = views._store_backed_json_response(image, "0.4", ".zattrs")

    assert response is not None
    assert json.loads(response.content) == {
        "multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}]
    }


def test_store_backed_json_response_skips_non_v04_requests(tmp_path):
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))

    assert views._store_backed_json_response(image, "0.3", ".zattrs") is None


def test_store_backed_chunk_response_returns_exact_chunk_bytes(tmp_path):
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()))

    response = views._store_backed_chunk_response(image, "0.4", 0, "0/0/0/0")

    assert response is not None
    assert response.content == b"chunk-bytes"
    assert response["Content-Disposition"] == "attachment; filename=0.0.0.0"


def test_store_backed_response_supports_non_numeric_dataset_paths(tmp_path):
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
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=502, name="10150")

    def fake_reverse(name, args=None, kwargs=None):
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


def test_get_chunk_shape_preserves_yx_order_for_non_pyramid_images():
    assert views.get_chunk_shape(_FakeChunkImage()) == [512, 1024]


class _FakeConn:
    def __init__(self, image):
        self._image = image
        self.c = None

    def getObject(self, object_type, iid):
        assert object_type == "Image"
        assert iid == self._image.id
        return self._image


def test_preview_image_zarray_delegates_to_raw_endpoint(monkeypatch):
    image = _FakeImage("/managed/demo.ome.zarr", image_id=43, name="managed.ome.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/43.zarr/0/.zarray")
    sentinel = HttpResponse('{"zarr_format": 2}', content_type="application/json")
    captured = {}
    conn = _FakeConn(image)

    def fake_image_zarray(request, iid, level, conn=None, **kwargs):
        captured["call"] = (request, iid, level, conn, kwargs)
        return sentinel

    monkeypatch.setattr(views, "image_zarray", fake_image_zarray)

    response = views.preview_image_zarray.__wrapped__(request, 43, 0, conn=conn)

    assert response is sentinel
    assert captured["call"][1:4] == (43, 0, conn)


def test_preview_image_chunk_delegates_to_raw_endpoint(monkeypatch):
    image = _FakeImage("/managed/demo.ome.zarr", image_id=44, name="managed.ome.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/44.zarr/0/0/0/0/0")
    sentinel = HttpResponse(b"store-chunk", content_type="application/octet-stream")
    captured = {}
    conn = _FakeConn(image)

    def fake_image_chunk(request, iid, level, chunk, conn=None, **kwargs):
        captured["call"] = (request, iid, level, chunk, conn, kwargs)
        return sentinel

    monkeypatch.setattr(views, "image_chunk", fake_image_chunk)

    response = views.preview_image_chunk.__wrapped__(
        request, 44, 0, "0/0/0/0", conn=conn
    )

    assert response is sentinel
    assert captured["call"][1:5] == (44, 0, "0/0/0/0", conn)


def test_preview_image_store_path_delegates_to_raw_endpoint(monkeypatch):
    image = _FakeImage("/managed/demo.ome.zarr", image_id=45, name="managed.ome.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/45.zarr/s1/.zarray")
    sentinel = HttpResponse('{"zarr_format": 2}', content_type="application/json")
    captured = {}
    conn = _FakeConn(image)

    def fake_image_store_path(request, iid, version, store_path, conn=None, **kwargs):
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


def test_download_store_ome_tiff_returns_ome_tiff_file(tmp_path, monkeypatch):
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


def test_download_store_ome_tiff_cleans_up_temp_file_when_writer_fails(
    tmp_path,
    monkeypatch,
):
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
        def __init__(self, path):
            self.name = str(path)
            path.write_bytes(b"temp")

        @staticmethod
        def close():
            return None

    class _FailingWriter:
        def __init__(self, *_args, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @staticmethod
        def write(*_args, **_kwargs):
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


def test_apps_serves_base_injected_shell_and_redirects_assets(monkeypatch):
    class _FakeResponse:
        text = "<html><head></head><body>vizarr</body></html>"

        @staticmethod
        def raise_for_status():
            return None

    views._fetch_remote_app_shell.cache_clear()
    monkeypatch.setattr(views.requests, "get", lambda url, timeout=20: _FakeResponse())

    shell_request = RequestFactory().get(
        "/zarr/vizarr/", {"source": "/zarr/v0.4/image/9.zarr"}
    )
    shell_response = views.apps(shell_request, "vizarr", "")
    shell_html = _response_text(shell_response)

    assert shell_response.status_code == 200
    assert '<base href="https://hms-dbmi.github.io/vizarr/">' in shell_html
    assert "window.location.origin" in shell_html
    assert "history.replaceState" in shell_html
    assert shell_response["Cache-Control"] == "private, max-age=300"

    asset_request = RequestFactory().get("/zarr/vizarr/static/index.js")
    asset_response = views.apps(asset_request, "vizarr", "static/index.js")

    assert asset_response.status_code == 302
    assert (
        asset_response["Location"]
        == "https://hms-dbmi.github.io/vizarr/static/index.js"
    )


def test_inject_launcher_head_replaces_existing_base_tag():
    html = '<html><head><base href="https://stale.example/"></head><body>validator</body></html>'

    updated = views._inject_launcher_head(
        html, "https://ome.github.io/ome-ngff-validator/"
    )

    assert "https://stale.example/" not in updated
    assert '<base href="https://ome.github.io/ome-ngff-validator/">' in updated
    assert updated.count("<base ") == 1
    assert "window.location.origin" in updated


def test_build_app_launch_url_quotes_root_relative_source(monkeypatch):
    monkeypatch.setattr(
        views,
        "reverse",
        lambda name, kwargs=None: f"/zarr/{kwargs['app']}/",
    )

    url = views._build_app_launch_url("validator", "/zarr/v0.4/image/1101.zarr")

    assert url == "/zarr/validator/?source=/zarr/v0.4/image/1101.zarr"


def test_store_backed_views_cover_missing_paths_and_preview_routes(
    tmp_path, monkeypatch
):
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

    monkeypatch.setattr(views, "load_store_backed_image_node", lambda current: None)
    with pytest.raises(Http404):
        views.download_store_ome_tiff(request, 14, conn=_FakeConn(image))


def test_app_shell_helpers_cover_empty_paths_cache_fetch_and_invalid_apps(monkeypatch):
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
        text = "<html>validator</html>"

        @staticmethod
        def raise_for_status():
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
