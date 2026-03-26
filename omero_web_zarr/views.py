import json
import logging
import os
import re
import tempfile
import time
import zipfile
from functools import lru_cache
from itertools import product
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import numpy as np
import requests
import tifffile
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse

from omero.model.enums import PixelsTypedouble
from omero.model.enums import PixelsTypefloat
from omero.model.enums import PixelsTypeint8
from omero.model.enums import PixelsTypeint16
from omero.model.enums import PixelsTypeint32
from omero.model.enums import PixelsTypeuint8
from omero.model.enums import PixelsTypeuint16
from omero.model.enums import PixelsTypeuint32
from omeroweb.webclient.decorators import login_required
from omeroweb.webgateway.marshal import channelMarshal

from .utils import generate_coordinate_transformations
from .utils import collect_store_metadata_documents
from .utils import get_store_backed_axis_names
from .utils import get_safe_image_tile_size
from .utils import load_store_backed_image_node
from .utils import sanitize_download_basename
from .utils import marshal_axes
from .utils import marshal_axes_v3
from .utils import is_store_metadata_path
from .utils import open_compat_array
from .utils import resolve_image_backing_zarr_store
from .utils import resolve_local_zarr_file

LOGGER = logging.getLogger(__name__)
_APP_BASE_URLS = {
    "vizarr": "https://hms-dbmi.github.io/vizarr/",
    "validator": "https://ome.github.io/ome-ngff-validator/",
}
_APP_SHELL_CACHE_SECONDS = 300

PIXEL_TYPES = {
    PixelsTypeint8: np.int8,
    PixelsTypeuint8: np.uint8,
    PixelsTypeint16: np.int16,
    PixelsTypeuint16: np.uint16,
    PixelsTypeint32: np.int32,
    PixelsTypeuint32: np.uint32,
    PixelsTypefloat: np.float32,
    PixelsTypedouble: np.float64,
}


def _store_backed_response(image, version, *parts):
    if version != "0.4":
        return None

    store_root = resolve_image_backing_zarr_store(image)
    if store_root is None:
        return None

    source = resolve_local_zarr_file(store_root, *parts)
    if is_store_metadata_path(source):
        with open(source, "r", encoding="utf-8") as reader:
            payload = json.load(reader)
        return JsonResponse(payload)

    data = source.read_bytes()
    rsp = HttpResponse(data, content_type="application/octet-stream")
    rsp["Content-Length"] = len(data)
    filename = ".".join(source.relative_to(store_root).parts)
    rsp["Content-Disposition"] = "attachment; filename=%s" % filename
    return rsp


def _store_backed_json_response(image, version, *parts):
    response = _store_backed_response(image, version, *parts)
    if response is None:
        return None
    if response.get("Content-Type") != "application/json":
        raise Http404("zarr path not found")
    return response


def _store_backed_chunk_response(image, version, level, chunk):
    response = _store_backed_response(image, version, str(level), *chunk.split("/"))
    if response is None:
        return None
    response["Content-Disposition"] = "attachment; filename=%s" % chunk.replace(
        "/", "."
    )
    return response


def _build_store_backed_preview_context(request, image):
    zarr_root = f"{reverse('omero_web_zarr_index')}v0.4/preview/image/{image.id}.zarr"
    validator_root = f"{reverse('omero_web_zarr_index')}v0.4/image/{image.id}.zarr"
    return {
        "image": image,
        "image_name": image.getName(),
        "thumbnail_url": reverse("render_thumbnail", args=(image.id,)),
        "vizarr_url": _build_app_launch_url("vizarr", zarr_root),
        "validator_url": _build_app_launch_url("validator", validator_root),
    }


@login_required()
def index(request, conn=None, **kwargs):
    home = reverse("omero_web_zarr_index")
    vizarr = reverse("zarr_app", kwargs={"app": "vizarr", "url": ""})
    return HttpResponse(
        "To open an Image in Vizarr go to "
        "%s?source=%sv0.4/image/[IMAGE_ID].zarr" % (vizarr, home)
    )


@login_required()
def image_zattrs(request, iid, version, conn=None, **kwargs):
    if version not in ("0.3", "0.4"):
        raise Http404("version not supported")

    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_json_response(image, version, ".zattrs")
    if store_rsp is not None:
        return store_rsp

    levels = [0]
    if image.requiresPixelsPyramid():
        image.getZoomLevelScaling()
        res_descs = image._re.getResolutionDescriptions()
        levels = range(len(res_descs))

    datasets = [{"path": str(level)} for level in levels]

    if version != "0.3":
        shapes = get_image_shapes(image)
        transformations = generate_coordinate_transformations(shapes)
        for dataset, transform in zip(datasets, transformations):
            dataset["coordinateTransformations"] = transform

    rv = {
        "multiscales": [
            {
                "datasets": datasets,
                "version": version,
                "axes": marshal_axes(image, version),
            }
        ],
        "omero": {
            "channels": [channelMarshal(x) for x in image.getChannels()],
            "id": image.id,
            "rdefs": {
                "defaultT": image._re.getDefaultT(),
                "defaultZ": image._re.getDefaultZ(),
                "model": image.isGreyscaleRenderingModel() and "greyscale" or "color",
            },
        },
    }
    return JsonResponse(rv)


def image_zgroup(request, **kwargs):
    image = kwargs.get("conn") and kwargs["conn"].getObject("Image", kwargs["iid"])
    if image is not None:
        store_rsp = _store_backed_json_response(image, kwargs["version"], ".zgroup")
        if store_rsp is not None:
            return store_rsp
    return JsonResponse({"zarr_format": 2})


def get_image_shape(image, level):
    shapes = get_image_shapes(image)
    if level >= len(shapes):
        raise Exception(
            "Level %s higher than %s levels for this image" % (level, len(shapes))
        )
    return shapes[level]


def get_image_shapes(image):
    shape = [getattr(image, "getSize" + dim)() for dim in ("TCZYX")]
    base_shape = [size for size in shape if size > 1]
    shapes = [base_shape]
    if image.requiresPixelsPyramid():
        image.getZoomLevelScaling()
        levels = image._re.getResolutionDescriptions()
        for level in levels[1:]:
            shape = base_shape[:]
            shape[-1] = level.sizeX
            shape[-2] = level.sizeY
            shapes.append(shape)
    return shapes


def get_chunk_shape(image):
    chunks = []
    for dim in "TCZ":
        if getattr(image, "getSize" + dim)() > 1:
            chunks.append(1)
    if image.requiresPixelsPyramid():
        image.getZoomLevelScaling()
        width, height = get_safe_image_tile_size(image)
    else:
        width = image.getSizeX()
        height = image.getSizeY()
    chunks.extend([height, width])
    return chunks


@login_required()
def image_zarray(request, iid, level, conn=None, **kwargs):
    level = int(level)
    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_json_response(image, "0.4", str(level), ".zarray")
    if store_rsp is not None:
        return store_rsp

    shape = get_image_shape(image, level)
    chunks = get_chunk_shape(image)

    ptype = image.getPrimaryPixels().getPixelsType().getValue()
    np_type = PIXEL_TYPES[ptype]

    rsp = {"data": "fail"}
    with tempfile.TemporaryDirectory() as tmpdirname:
        open_compat_array(
            tmpdirname,
            mode="w",
            shape=shape,
            chunks=chunks,
            dtype=np_type,
        )

        zarray_path = os.path.join(tmpdirname, ".zarray")
        with open(zarray_path, "r", encoding="utf-8") as reader:
            rsp = json.load(reader)

    rsp["dimension_separator"] = "/"
    return JsonResponse(rsp)


@login_required()
def image_chunk(request, iid, level, chunk, conn=None, **kwargs):
    dims = [int(dim) for dim in chunk.split("/")]

    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_chunk_response(image, "0.4", level, chunk)
    if store_rsp is not None:
        return store_rsp

    axes = marshal_axes_v3(image)

    if len(dims) != len(axes):
        raise Http404(
            "chunk %s has incorrect number of dimensions for axes: %s" % (chunk, axes)
        )

    level = int(level)
    shape = get_image_shape(image, level)
    chunks = get_chunk_shape(image)
    ptype = image.getPrimaryPixels().getPixelsType().getValue()
    np_type = PIXEL_TYPES[ptype]

    x = dims[-1]
    y = dims[-2]
    z = dims[axes.index("z")] if "z" in axes else 0
    c = dims[axes.index("c")] if "c" in axes else 0
    t = dims[axes.index("t")] if "t" in axes else 0

    tile_w = chunks[-1]
    tile_h = chunks[-2]
    tile_x = x * tile_w
    tile_y = y * tile_h
    tile_w = min(shape[-1] - tile_x, tile_w)
    tile_h = min(shape[-2] - tile_y, tile_h)
    tile = [tile_x, tile_y, tile_w, tile_h]

    if image.requiresPixelsPyramid() and level > 0:
        pix = image._conn.c.sf.createRawPixelsStore()
        pid = image.getPixelsId()
        try:
            max_level = len(image.getZoomLevelScaling()) - 1
            level = max_level - level
            pix.setPixelsId(pid, False)
            pix.setResolutionLevel(level)
            tile = pix.getTile(z, c, t, tile_x, tile_y, tile_w, tile_h)
        finally:
            pix.close()

        tile = np.frombuffer(tile, dtype=np_type)
        plane = tile.reshape((tile_h, tile_w))
    else:
        plane = image.getPrimaryPixels().getTile(z, c, t, tile)
    if chunks[-1] != tile_w or chunks[-2] != tile_h:
        plane2 = np.zeros((chunks[-2], chunks[-1]), dtype=plane.dtype)
        plane2[0:tile_h, 0:tile_w] = plane
        plane = plane2

    indices = []
    for dim in "tcz":
        if dim in axes:
            indices.append(0)

    data = b""
    with tempfile.TemporaryDirectory() as tmpdirname:
        zarr_array = open_compat_array(
            tmpdirname,
            mode="w",
            shape=chunks,
            chunks=chunks,
            dtype=plane.dtype,
        )
        zarr_array[tuple(indices)] = plane

        indices.extend([0, 0])
        chunk_path = os.path.join(tmpdirname, ".".join(str(size) for size in indices))
        with open(chunk_path, "rb") as reader:
            data = reader.read()

    chunk_name = ".".join(str(dim) for dim in [t, c, z, y, x])
    rsp = HttpResponse(data)
    rsp["Content-Length"] = len(data)
    rsp["Content-Disposition"] = "attachment; filename=%s" % chunk_name
    return rsp


@login_required()
def image_store_path(request, iid, version, store_path, conn=None, **kwargs):
    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_response(image, version, *store_path.split("/"))
    if store_rsp is None:
        raise Http404("zarr path not found")
    return store_rsp


@login_required()
def preview_image_zattrs(request, iid, version="0.4", conn=None, **kwargs):
    return image_zattrs(request, iid, version, conn=conn, **kwargs)


@login_required()
def preview_image_zgroup(request, iid, version="0.4", conn=None, **kwargs):
    return image_zgroup(request, iid=iid, version=version, conn=conn, **kwargs)


@login_required()
def preview_image_zarray(request, iid, level, conn=None, **kwargs):
    return image_zarray(request, iid, level, conn=conn, **kwargs)


@login_required()
def preview_image_chunk(request, iid, level, chunk, conn=None, **kwargs):
    return image_chunk(request, iid, level, chunk, conn=conn, **kwargs)


@login_required()
def preview_image_store_path(
    request, iid, version="0.4", store_path=None, conn=None, **kwargs
):
    return image_store_path(
        request,
        iid,
        version,
        store_path or "",
        conn=conn,
        **kwargs,
    )


@login_required()
def image_preview(request, iid, conn=None, **kwargs):
    image = conn.getObject("Image", iid)
    if image is None:
        raise Http404("image not found")

    if resolve_image_backing_zarr_store(image) is None:
        return redirect(
            reverse("load_metadata_preview", kwargs={"c_type": "image", "c_id": iid})
        )

    context = _build_store_backed_preview_context(request, image)
    return render(request, "omero_web_zarr/image_preview.html", context)


def _store_backed_download_name(image, suffix):
    base_name = sanitize_download_basename(image.getName(), default=f"Image-{image.id}")
    return f"{base_name}{suffix}"


def _store_backed_ome_axes_and_array(node):
    array = node.data[0]
    axis_names = get_store_backed_axis_names(node, level=0)
    supported_axes = {"t", "c", "z", "y", "x"}
    unknown_axes = [axis for axis in axis_names if axis not in supported_axes]
    if unknown_axes:
        raise Http404("store-backed OME-TIFF export supports image axes only")

    ordered_axes = [axis for axis in ("t", "c", "z", "y", "x") if axis in axis_names]
    if axis_names != ordered_axes:
        transpose = [axis_names.index(axis) for axis in ordered_axes]
        array = np.transpose(array, axes=transpose)
    return array, "".join(axis.upper() for axis in ordered_axes)


def _iter_store_backed_ome_tiff_planes(array):
    plane_shape = array.shape[-2:]
    leading_shape = array.shape[:-2]
    if not leading_shape:
        yield np.asarray(array).reshape(plane_shape)
        return

    for index in product(*(range(size) for size in leading_shape)):
        yield np.asarray(array[index]).reshape(plane_shape)


def _store_backed_ome_tiff_metadata(image, node, axes):
    metadata = {
        "axes": axes,
        "Name": image.getName(),
    }

    for dim, getter in (
        ("X", image.getPixelSizeX),
        ("Y", image.getPixelSizeY),
        ("Z", image.getPixelSizeZ),
    ):
        length = getter(units=True)
        if length is None:
            continue
        metadata[f"PhysicalSize{dim}"] = length.getValue()
        metadata[f"PhysicalSize{dim}Unit"] = length.getSymbol()

    channel_names = (getattr(node, "metadata", {}) or {}).get("channel_names") or []
    if channel_names and "C" in axes:
        metadata["Channel"] = {"Name": [str(name) for name in channel_names]}
    return metadata


@login_required()
def download_store_original(request, iid, conn=None, **kwargs):
    image = conn.getObject("Image", iid)
    store_root = image is not None and resolve_image_backing_zarr_store(image)
    if image is None or store_root is None:
        raise Http404("store-backed image not found")

    archive = tempfile.TemporaryFile()
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=1,
    ) as zf:
        for path in sorted(store_root.rglob("*")):
            if not path.is_file():
                continue
            zf.write(
                path, arcname=str(Path(store_root.name) / path.relative_to(store_root))
            )

    archive.seek(0)
    return FileResponse(
        archive,
        as_attachment=True,
        filename=_store_backed_download_name(image, ".zip"),
    )


@login_required()
def download_store_metadata(request, iid, conn=None, **kwargs):
    image = conn.getObject("Image", iid)
    store_root = image is not None and resolve_image_backing_zarr_store(image)
    if image is None or store_root is None:
        raise Http404("store-backed image not found")

    payload = {
        "store": store_root.name,
        "documents": collect_store_metadata_documents(image),
    }
    response = HttpResponse(
        json.dumps(payload, indent=2, sort_keys=True),
        content_type="application/json",
    )
    response["Content-Disposition"] = (
        "attachment; filename=%s"
        % _store_backed_download_name(
            image,
            "-metadata.json",
        )
    )
    return response


@login_required()
def download_store_ome_tiff(request, iid, conn=None, **kwargs):
    image = conn.getObject("Image", iid)
    if image is None or resolve_image_backing_zarr_store(image) is None:
        raise Http404("store-backed image not found")

    node = load_store_backed_image_node(image)
    if node is None:
        raise Http404("store-backed image data not found")

    array, axes = _store_backed_ome_axes_and_array(node)
    metadata = _store_backed_ome_tiff_metadata(image, node, axes)

    target = tempfile.NamedTemporaryFile(suffix=".ome.tif", delete=False)
    target_path = Path(target.name)
    target.close()
    try:
        with tifffile.TiffWriter(target_path, bigtiff=True, ome=True) as writer:
            writer.write(
                _iter_store_backed_ome_tiff_planes(array),
                shape=array.shape,
                dtype=array.dtype,
                metadata=metadata,
                photometric="minisblack",
                compression="adobe_deflate",
                compressionargs={"level": 1},
            )
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    stream = open(target_path, "rb")
    size = target_path.stat().st_size
    original_close = stream.close

    def _close_and_unlink():
        try:
            original_close()
        finally:
            target_path.unlink(missing_ok=True)

    stream.close = _close_and_unlink
    response = FileResponse(
        stream,
        as_attachment=True,
        filename=_store_backed_download_name(image, ".ome.tif"),
    )
    response["Content-Length"] = size
    return response


def _sanitize_app_asset_path(url):
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise Http404("invalid app asset path")

    parts = [part for part in Path(raw.lstrip("/")).parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise Http404("invalid app asset path")
    return "/".join(parts)


def _build_app_launch_url(app, source):
    return "%s?source=%s" % (
        reverse("zarr_app", kwargs={"app": app, "url": ""}),
        quote(source, safe="/:?=&"),
    )


def _inject_launcher_head(html, base_url):
    head_fragment = (
        f'<base href="{base_url}">'
        "<script>"
        "(function(){"
        "try{"
        "var currentUrl=new URL(window.location.href);"
        "var source=currentUrl.searchParams.get('source');"
        "if(!source||/^(?:[a-z][a-z0-9+.-]*:|\\/\\/)/i.test(source)){return;}"
        "var base=source.charAt(0)==='/'?window.location.origin:window.location.href;"
        "var normalized=new URL(source,base).toString();"
        "if(normalized!==source){"
        "currentUrl.searchParams.set('source',normalized);"
        "window.history.replaceState(null,'',currentUrl.toString());"
        "}"
        "}catch(_err){}"
        "})();"
        "</script>"
    )
    if re.search(r"<base\b", html, flags=re.IGNORECASE):
        return re.sub(
            r"<base\b[^>]*>", head_fragment, html, count=1, flags=re.IGNORECASE
        )

    head_match = re.search(r"<head[^>]*>", html, flags=re.IGNORECASE)
    if head_match:
        return f"{html[: head_match.end()]}{head_fragment}{html[head_match.end() :]}"
    return f"{head_fragment}{html}"


@lru_cache(maxsize=16)
def _fetch_remote_app_shell(base_url, cache_bucket):
    response = requests.get(base_url, timeout=20)
    response.raise_for_status()
    return response.text


def apps(request, app, url):
    if app not in _APP_BASE_URLS:
        raise Http404("App: %s not found" % app)

    base_url = _APP_BASE_URLS[app]
    asset_path = _sanitize_app_asset_path(url)
    if asset_path:
        return HttpResponseRedirect(urljoin(base_url, asset_path))

    cache_bucket = int(time.time() // _APP_SHELL_CACHE_SECONDS)
    try:
        html = _fetch_remote_app_shell(base_url, cache_bucket)
    except requests.RequestException:
        LOGGER.warning("Failed to fetch remote app shell for %s", app, exc_info=True)
        return HttpResponse(status=502)

    response = HttpResponse(
        _inject_launcher_head(html, base_url), content_type="text/html; charset=utf-8"
    )
    response["Cache-Control"] = f"private, max-age={_APP_SHELL_CACHE_SECONDS}"
    return response
