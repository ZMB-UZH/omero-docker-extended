import os
import json
import warnings
import zipfile
from io import BytesIO

import django
import numpy as np
from django.http import HttpResponse
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

    def getPixelSizeX(self, units=True):
        return None

    def getPixelSizeY(self, units=True):
        return None

    def getPixelSizeZ(self, units=True):
        return None


class _FakeChunkImage:
    def requiresPixelsPyramid(self):
        return False

    def getSizeT(self):
        return 1

    def getSizeC(self):
        return 1

    def getSizeZ(self):
        return 1

    def getSizeY(self):
        return 512

    def getSizeX(self):
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


def test_build_store_backed_preview_context_points_to_omero_zarr_endpoints(tmp_path, monkeypatch):
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


def test_preview_image_zattrs_preserves_store_backed_raw_multiscales(tmp_path, monkeypatch):
    _write_store(tmp_path)
    image = _FakeImage(str(tmp_path.resolve()), image_id=12, name="pyramid.zarr")
    request = RequestFactory().get("/zarr/v0.4/preview/image/12.zarr/.zattrs")
    root_payload = {
        "multiscales": [
            {
                "version": "0.4",
                "datasets": [
                    {"path": "s0", "coordinateTransformations": [{"type": "scale", "scale": [1, 1, 1]}]},
                    {"path": "s1", "coordinateTransformations": [{"type": "scale", "scale": [2, 2, 2]}]},
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

    response = views.preview_image_zattrs.__wrapped__(request, 12, conn=_FakeConn(image))

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

    response = views.preview_image_chunk.__wrapped__(request, 44, 0, "0/0/0/0", conn=conn)

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
    assert response["Content-Disposition"] == "attachment; filename=demo.zarr-metadata.json"
    assert payload["store"] == tmp_path.name
    assert payload["documents"][".zattrs"]["multiscales"][0]["datasets"] == [{"path": "0"}]


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

        assert response["Content-Disposition"] == 'attachment; filename="demo.zarr.ome.tif"'
        with tifffile.TiffFile(BytesIO(payload)) as tif:
            assert tif.is_ome
            assert tif.series[0].shape == (2, 2)
            assert 'SizeC="1"' in tif.ome_metadata
            assert 'SizeZ="1"' in tif.ome_metadata
    finally:
        response.close()


def test_apps_serves_base_injected_shell_and_redirects_assets(monkeypatch):
    class _FakeResponse:
        text = "<html><head></head><body>vizarr</body></html>"

        def raise_for_status(self):
            return None

    views._fetch_remote_app_shell.cache_clear()
    monkeypatch.setattr(views.requests, "get", lambda url, timeout=20: _FakeResponse())

    shell_request = RequestFactory().get("/zarr/vizarr/", {"source": "/zarr/v0.4/image/9.zarr"})
    shell_response = views.apps(shell_request, "vizarr", "")
    shell_html = shell_response.content.decode("utf-8")

    assert shell_response.status_code == 200
    assert '<base href="https://hms-dbmi.github.io/vizarr/">' in shell_html
    assert "window.location.origin" in shell_html
    assert "history.replaceState" in shell_html
    assert shell_response["Cache-Control"] == "private, max-age=300"

    asset_request = RequestFactory().get("/zarr/vizarr/static/index.js")
    asset_response = views.apps(asset_request, "vizarr", "static/index.js")

    assert asset_response.status_code == 302
    assert asset_response["Location"] == "https://hms-dbmi.github.io/vizarr/static/index.js"


def test_inject_launcher_head_replaces_existing_base_tag():
    html = '<html><head><base href="https://stale.example/"></head><body>validator</body></html>'

    updated = views._inject_launcher_head(html, "https://ome.github.io/ome-ngff-validator/")

    assert 'https://stale.example/' not in updated
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
