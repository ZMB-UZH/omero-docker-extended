import io
import json
import logging
import re
import tempfile
import time
import zipfile
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import numpy as np
import requests
import tifffile
from omero_plugin_common.logging_utils import sanitize_log_value
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.templatetags.static import static
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
from .utils import get_image_connection
from .utils import require_image_rendering_engine
from .utils import get_safe_image_tile_size
from .utils import load_store_backed_image_node
from .utils import sanitize_download_basename
from .utils import marshal_axes
from .utils import marshal_axes_v3
from .utils import is_store_metadata_path
from .utils import resolve_image_backing_zarr_store
from .utils import resolve_local_zarr_file

LOGGER = logging.getLogger(__name__)


class _UnlinkOnCloseFile:
    """Helper type for unlink on close file behavior."""

    def __init__(self, stream: Any, path: Path) -> None:
        """Create `_UnlinkOnCloseFile` with `stream` and `path`.

        Inputs: `stream`, `path`. Output: None.
        """
        self._stream = stream
        self._path = path

    def __getattr__(self, name: str) -> Any:
        """Return a dynamic attribute value by name.

        Inputs: `name`. Output: `Any`.
        """
        return getattr(self._stream, name)

    def read(self, *args: Any, **kwargs: Any) -> Any:
        """Read data from the resource.

        Inputs: `*args`, `**kwargs`. Output: `Any`.
        """
        return self._stream.read(*args, **kwargs)

    def close(self) -> None:
        """Close `_UnlinkOnCloseFile`'s fake resource handle.

        Inputs: no caller arguments. Output: closes the described state and returns None.
        """
        try:
            self._stream.close()
        finally:
            self._path.unlink(missing_ok=True)


def _local_static_url(static_path):
    """Return a stable app base URL for package static assets.

    Inputs: `static_path`. Output: URL string.
    """
    static_url = static(static_path)
    parsed = urlsplit(static_url)
    if parsed.scheme or parsed.netloc or static_url.startswith("/"):
        return static_url
    return f"/{static_url}"


def _source_tree_vizarr_dist_dir():
    """Return the single source-tree Vizarr dist directory when present.

    Inputs: no caller arguments. Output: `Path` or `None`.
    """
    third_party_root = Path(__file__).resolve().parents[1] / "third_party"
    candidates = sorted(
        path
        for path in third_party_root.glob("vizarr-*")
        if path.is_dir()
        and re.fullmatch(r"vizarr-[0-9a-f]{40}", path.name)
        and (path / "dist" / "index.html").is_file()
    )
    if len(candidates) == 1:
        return candidates[0] / "dist"
    return None


def _package_vizarr_static_dir():
    """Return the single packaged Vizarr static directory when present.

    Inputs: no caller arguments. Output: `Path` or `None`.
    """
    static_root = (
        Path(__file__).resolve().parent
        / "static"
        / "omero_web_zarr"
        / "vendor"
        / "vizarr"
    )
    candidates = sorted(
        path
        for path in static_root.glob("*")
        if path.is_dir()
        and re.fullmatch(r"[0-9a-f]{40}", path.name)
        and (path / "index.html").is_file()
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


def _vizarr_vendor_commit():
    """Return the pinned vendored Vizarr commit from package or source files.

    Inputs: no caller arguments. Output: commit hash string. Raises: RuntimeError
    when the vendored build is missing or ambiguous.
    """
    package_static_dir = _package_vizarr_static_dir()
    if package_static_dir is not None:
        return package_static_dir.name

    source_dist_dir = _source_tree_vizarr_dist_dir()
    if source_dist_dir is not None:
        return source_dist_dir.parent.name.removeprefix("vizarr-")

    raise RuntimeError("Exactly one pinned vendored Vizarr build is required")


VIZARR_UPSTREAM_COMMIT = _vizarr_vendor_commit()
_VIZARR_STATIC_PREFIX = f"omero_web_zarr/vendor/vizarr/{VIZARR_UPSTREAM_COMMIT}/"
_APP_BASE_URLS = {
    "vizarr": _local_static_url(_VIZARR_STATIC_PREFIX),
    "validator": "https://ome.github.io/ome-ngff-validator/",
}
_LOCAL_APP_SHELLS = {
    "vizarr": _VIZARR_STATIC_PREFIX + "index.html",
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


def _runtime_generated_zarray_metadata(shape, chunks, dtype) -> dict[str, object]:
    """Runtime-generated zarray metadata from shape, chunks, and dtype.

    Inputs: `shape`, `chunks`, `dtype`. Output: `dict[str, object]`.
    """
    return {
        "zarr_format": 2,
        "shape": list(shape),
        "chunks": list(chunks),
        "dtype": np.dtype(dtype).str,
        "compressor": None,
        "fill_value": 0,
        "filters": None,
        "order": "C",
        "dimension_separator": "/",
    }


def _store_backed_response(image, version, *parts):
    """Return the store backed response.

    Inputs: `image`, `version`, `*parts`. Output: `rsp`.
    """
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
    rsp["Content-Disposition"] = f"attachment; filename={filename}"
    return rsp


def _store_backed_json_response(image, version, *parts):
    """Backed JSON response.

    Inputs: `image`, `version`, `*parts`. Output: JSON-compatible value. Raises: Http404
    when validation or the called operation fails.
    """
    response = _store_backed_response(image, version, *parts)
    if response is None:
        return None
    if response.get("Content-Type") != "application/json":
        raise Http404("zarr path not found")
    return response


def _store_backed_chunk_response(image, version, level, chunk):
    """Backed chunk response.

    Inputs: `image`, `version`, `level`, `chunk`. Output: `response` or None.
    """
    response = _store_backed_response(image, version, str(level), *chunk.split("/"))
    if response is None:
        return None
    filename = chunk.replace("/", ".")
    response["Content-Disposition"] = f"attachment; filename={filename}"
    return response


def _build_store_backed_preview_context(request, image):
    """Backed preview context.

    Inputs: `request`, `image`. Output: dict.
    """
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
def index(request, _conn=None, **kwargs):
    """Return the index.

    Inputs: `request` Django request, `_conn`, `**kwargs` keyword arguments. Output:
    streaming HTTP response.
    """
    home = reverse("omero_web_zarr_index")
    vizarr = reverse("zarr_app", kwargs={"app": "vizarr", "url": ""})
    instruction = (
        "To open an Image in Vizarr go to "
        f"{vizarr}?source={home}v0.4/image/[IMAGE_ID].zarr"
    )
    return StreamingHttpResponse(
        (instruction,),
        content_type="text/plain; charset=utf-8",
    )


@login_required()
def image_zattrs(request, iid, version, conn=None, **kwargs):
    """Return the image zattrs.

    Inputs: `request` Django request, `iid`, `version`, `conn` OMERO gateway connection,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`. Raises: Http404 when validation
    or the called operation fails.
    """
    if version not in ("0.3", "0.4"):
        raise Http404("version not supported")

    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_json_response(image, version, ".zattrs")
    if store_rsp is not None:
        return store_rsp

    levels = [0]
    if image.requiresPixelsPyramid():
        rendering_engine = require_image_rendering_engine(image, initialize=True)
        res_descs = rendering_engine.getResolutionDescriptions()
        levels = list(range(len(res_descs)))
    else:
        rendering_engine = require_image_rendering_engine(image, initialize=True)

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
                "defaultT": rendering_engine.getDefaultT(),
                "defaultZ": rendering_engine.getDefaultZ(),
                "model": image.isGreyscaleRenderingModel() and "greyscale" or "color",
            },
        },
    }
    return JsonResponse(rv)


def image_zgroup(request, **kwargs):
    """Return the image zgroup.

    Inputs: `request` Django request, `**kwargs` keyword arguments. Output: Django
    `JsonResponse`.
    """
    image = kwargs.get("conn") and kwargs["conn"].getObject("Image", kwargs["iid"])
    if image is not None:
        store_rsp = _store_backed_json_response(image, kwargs["version"], ".zgroup")
        if store_rsp is not None:
            return store_rsp
    return JsonResponse({"zarr_format": 2})


def get_image_shape(image, level):
    """Return the image shape.

    Inputs: `image`, `level`. Output: get image shape result.
    """
    shapes = get_image_shapes(image)
    if level >= len(shapes):
        raise Exception(
            f"Level {level} higher than {len(shapes)} levels for this image"
        )
    return shapes[level]


def get_image_shapes(image):
    """Return image shapes.

    Inputs: `image`. Output: `shapes`.
    """
    shape = [getattr(image, "getSize" + dim)() for dim in ("TCZYX")]
    base_shape = [size for size in shape if size > 1]
    shapes = [base_shape]
    if image.requiresPixelsPyramid():
        rendering_engine = require_image_rendering_engine(image, initialize=True)
        levels = rendering_engine.getResolutionDescriptions()
        for level in levels[1:]:
            shape = base_shape[:]
            shape[-1] = level.sizeX
            shape[-2] = level.sizeY
            shapes.append(shape)
    return shapes


def get_chunk_shape(image):
    """Return chunk shape.

    Inputs: `image`. Output: `chunks`.
    """
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


def _read_lower_pyramid_plane(
    image,
    level,
    z,
    c,
    t,
    tile_x,
    tile_y,
    tile_w,
    tile_h,
    np_type,
):
    """Read the lower pyramid plane.

    Inputs: `image`, `level`, `z`, `c`, `t`, `tile_x`, `tile_y`, `tile_w`, `tile_h`,
    `np_type`. Output: `reshape` result. Raises: Http404 for the exercised failure path.
    """
    image_connection = get_image_connection(image)
    if image_connection is None:
        raise Http404("image connection unavailable")

    pix = image_connection.c.sf.createRawPixelsStore()
    try:
        max_level = len(image.getZoomLevelScaling()) - 1
        pix.setPixelsId(image.getPixelsId(), False)
        pix.setResolutionLevel(max_level - level)
        tile_bytes = pix.getTile(z, c, t, tile_x, tile_y, tile_w, tile_h)
    finally:
        pix.close()

    tile_array = np.frombuffer(tile_bytes, dtype=np_type)
    return tile_array.reshape((tile_h, tile_w))


def _read_runtime_chunk_plane(image, level, z, c, t, tile, np_type):
    """Read the runtime chunk plane.

    Inputs: `image`, `level`, `z`, `c`, `t`, `tile`, `np_type`. Output: `getTile`
    """
    tile_x, tile_y, tile_w, tile_h = tile
    if image.requiresPixelsPyramid() and level > 0:
        return _read_lower_pyramid_plane(
            image,
            level,
            z,
            c,
            t,
            tile_x,
            tile_y,
            tile_w,
            tile_h,
            np_type,
        )
    return image.getPrimaryPixels().getTile(z, c, t, tile)


def _runtime_chunk_plane_array(plane, dtype, height, width):
    """Return a 2D chunk plane array with the declared Zarr dtype.

    Inputs: `plane`, `dtype`, `height`, `width`. Output: `numpy.ndarray`.
    """
    np_dtype = np.dtype(dtype)
    if isinstance(plane, bytes | bytearray | memoryview):
        plane_array = np.frombuffer(plane, dtype=np_dtype)
    else:
        plane_array = np.asarray(plane, dtype=np_dtype)
    return plane_array.reshape((height, width))


def _runtime_chunk_bytes(plane, dtype) -> bytes:
    """Return uncompressed C-order chunk bytes for runtime-generated Zarr metadata.

    Inputs: `plane`, `dtype`. Output: bytes.
    """
    return np.ascontiguousarray(plane, dtype=np.dtype(dtype)).tobytes(order="C")


@login_required()
def image_zarray(request, iid, level, conn=None, **kwargs):
    """Return the image zarray.

    Inputs: `request` Django request, `iid`, `level`, `conn` OMERO gateway connection,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    level = int(level)
    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_json_response(image, "0.4", str(level), ".zarray")
    if store_rsp is not None:
        return store_rsp

    shape = get_image_shape(image, level)
    chunks = get_chunk_shape(image)

    ptype = image.getPrimaryPixels().getPixelsType().getValue()
    np_type = PIXEL_TYPES[ptype]
    return JsonResponse(_runtime_generated_zarray_metadata(shape, chunks, np_type))


@login_required()
def image_chunk(request, iid, level, chunk, conn=None, **kwargs):
    """Return the image chunk.

    Inputs: `request` Django request, `iid`, `level`, `chunk`, `conn` OMERO gateway
    connection, `**kwargs` keyword arguments. Output: `rsp`. Raises: Http404 when validation or
    the called operation fails.
    """
    dims = [int(dim) for dim in chunk.split("/")]

    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_chunk_response(image, "0.4", level, chunk)
    if store_rsp is not None:
        return store_rsp

    axes = marshal_axes_v3(image)

    if len(dims) != len(axes):
        raise Http404(
            f"chunk {chunk} has incorrect number of dimensions for axes: {axes}"
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

    plane = _read_runtime_chunk_plane(image, level, z, c, t, tile, np_type)
    plane = _runtime_chunk_plane_array(plane, np_type, tile_h, tile_w)
    if chunks[-1] != tile_w or chunks[-2] != tile_h:
        plane2 = np.zeros((chunks[-2], chunks[-1]), dtype=np.dtype(np_type))
        plane2[0:tile_h, 0:tile_w] = plane
        plane = plane2

    data = _runtime_chunk_bytes(plane, np_type)

    chunk_name = ".".join(str(dim) for dim in [t, c, z, y, x])
    rsp = FileResponse(
        io.BytesIO(data),
        content_type="application/octet-stream",
    )
    rsp["Content-Length"] = len(data)
    rsp["Content-Disposition"] = f"attachment; filename={chunk_name}"
    return rsp


@login_required()
def image_store_path(request, iid, version, store_path, conn=None, **kwargs):
    """Return the image store path.

    Inputs: `request` Django request, `iid`, `version`, `store_path`, `conn` OMERO
    gateway connection, `**kwargs` keyword arguments. Output: `store_rsp`. Raises:
    Raises: Http404 when validation or the called operation fails.
    """
    image = conn.getObject("Image", iid)
    store_rsp = _store_backed_response(image, version, *store_path.split("/"))
    if store_rsp is None:
        raise Http404("zarr path not found")
    return store_rsp


@login_required()
def preview_image_zattrs(request, iid, version="0.4", conn=None, **kwargs):
    """Return the preview image zattrs.

    Inputs: `request` Django request, `iid`, `version`, `conn` OMERO gateway connection,
    `**kwargs` keyword arguments. Output: `image_zattrs` result.
    """
    return image_zattrs(request, iid, version, conn=conn, **kwargs)


@login_required()
def preview_image_zgroup(request, iid, version="0.4", conn=None, **kwargs):
    """Return the preview image zgroup.

    Inputs: `request` Django request, `iid`, `version`, `conn` OMERO gateway connection,
    `**kwargs` keyword arguments. Output: `image_zgroup` result.
    """
    return image_zgroup(request, iid=iid, version=version, conn=conn, **kwargs)


@login_required()
def preview_image_zarray(request, iid, level, conn=None, **kwargs):
    """Return the preview image zarray.

    Inputs: `request` Django request, `iid`, `level`, `conn` OMERO gateway connection,
    `**kwargs` keyword arguments. Output: `image_zarray` result.
    """
    return image_zarray(request, iid, level, conn=conn, **kwargs)


@login_required()
def preview_image_chunk(request, iid, level, chunk, conn=None, **kwargs):
    """Return the preview image chunk.

    Inputs: `request` Django request, `iid`, `level`, `chunk`, `conn` OMERO gateway
    connection, `**kwargs` keyword arguments. Output: `image_chunk` result.
    """
    return image_chunk(request, iid, level, chunk, conn=conn, **kwargs)


@login_required()
def preview_image_store_path(
    request, iid, version="0.4", store_path=None, conn=None, **kwargs
):
    """Return the preview image store path.

    Inputs: `request` Django request, `iid`, `version`, `store_path`, `conn` OMERO
    gateway connection, `**kwargs` keyword arguments. Output: `image_store_path` result.
    """
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
    """Return the image preview.

    Inputs: `request` Django request, `iid`, `conn` OMERO gateway connection, `**kwargs`
    keyword arguments. Output: rendered Django response. Raises: Http404 when validation or the
    called operation fails.
    """
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
    """Backed download name.

    Inputs: `image`, `suffix`. Output: `f'{base_name}{suffix}'`.
    """
    base_name = sanitize_download_basename(image.getName(), default=f"Image-{image.id}")
    return f"{base_name}{suffix}"


def _store_backed_ome_axes_and_array(node):
    """Backed ome axes and array.

    Inputs: `node`. Output: `tuple`. Raises: Http404 for the exercised failure path.
    """
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
    """Backed ome tiff planes.

    Inputs: `array`. Output: yielded values.
    """
    plane_shape = array.shape[-2:]
    leading_shape = array.shape[:-2]
    if not leading_shape:
        yield np.asarray(array).reshape(plane_shape)
        return

    for plane_index in product(*(range(size) for size in leading_shape)):
        yield np.asarray(array[plane_index]).reshape(plane_shape)


def _store_backed_ome_tiff_metadata(image, node, axes):
    """Backed ome tiff metadata.

    Inputs: `image`, `node`, `axes`. Output: `metadata`.
    """
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
    """Download the store original.

    Inputs: `request` Django request, `iid`, `conn` OMERO gateway connection, `**kwargs`
    keyword arguments. Output: Django `FileResponse`. Raises: Http404 when validation or
    external operations fail.
    """
    image = conn.getObject("Image", iid)
    if image is None:
        raise Http404("store-backed image not found")
    store_root = resolve_image_backing_zarr_store(image)
    if store_root is None:
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
    """Download the store metadata.

    Inputs: `request` Django request, `iid`, `conn` OMERO gateway connection, `**kwargs`
    keyword arguments. Output: metadata mapping. Raises: Http404 when validation or
    external operations fail.
    """
    image = conn.getObject("Image", iid)
    if image is None:
        raise Http404("store-backed image not found")
    store_root = resolve_image_backing_zarr_store(image)
    if store_root is None:
        raise Http404("store-backed image not found")

    payload = {
        "store": store_root.name,
        "documents": collect_store_metadata_documents(image),
    }
    response = HttpResponse(
        json.dumps(payload, indent=2, sort_keys=True),
        content_type="application/json",
    )
    filename = _store_backed_download_name(
        image,
        "-metadata.json",
    )
    response["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@login_required()
def download_store_ome_tiff(request, iid, conn=None, **kwargs):
    """Download the store OME tiff.

    Inputs: `request` Django request, `iid`, `conn` OMERO gateway connection, `**kwargs`
    keyword arguments. Output: download store OME tiff result. Raises: Http404 when validation
    or the called operation fails.
    """
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
    response = FileResponse(
        _UnlinkOnCloseFile(stream, target_path),
        as_attachment=True,
        filename=_store_backed_download_name(image, ".ome.tif"),
    )
    response["Content-Length"] = size
    return response


def _sanitize_app_asset_path(url):
    """Sanitize the app asset path.

    Inputs: `url` URL. Output: `join` result. Raises: Http404 when validation or
    external operations fail.
    """
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
    """App launch URL.

    Inputs: `app`, `source`. Output: URL string.
    """
    return (
        f"{reverse('zarr_app', kwargs={'app': app, 'url': ''})}"
        f"?source={quote(source, safe='/:')}"
    )


def _inject_launcher_head(html, base_url):
    """Return the inject launcher head.

    Inputs: `html`, `base_url` base URL. Output: inject launcher head result.
    """
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
def _fetch_remote_app_shell(base_url, _cache_bucket):
    """Fetch the remote app shell.

    Inputs: `base_url` base URL, `_cache_bucket`. Output: `text`.
    """
    response = requests.get(base_url, timeout=20)
    response.raise_for_status()
    return response.text


@lru_cache(maxsize=16)
def _read_local_app_shell(static_path, _cache_bucket):
    """Read a repo-vendored app shell from a static asset path.

    Inputs: `static_path`, `_cache_bucket`. Output: app shell text. Raises: OSError
    when the vendored shell is missing.
    """
    shell_path = _local_app_shell_path(static_path)
    return shell_path.read_text(encoding="utf-8")


def _local_app_shell_path(static_path):
    """Return a local app shell path for package or source-tree execution.

    Inputs: `static_path`. Output: `Path`.
    """
    package_path = Path(__file__).resolve().parent / "static" / static_path
    if package_path.is_file() or not static_path.startswith(_VIZARR_STATIC_PREFIX):
        return package_path

    relative_asset = Path(static_path.removeprefix(_VIZARR_STATIC_PREFIX))
    if relative_asset.is_absolute() or any(
        part in ("", ".", "..") for part in relative_asset.parts
    ):
        return package_path

    source_dist_dir = _source_tree_vizarr_dist_dir()
    if source_dist_dir is not None:
        source_tree_path = source_dist_dir / relative_asset
        if source_tree_path.is_file():
            return source_tree_path
    return package_path


def apps(request, app, url):
    """Return the apps.

    Inputs: `request` Django request, `app`, `url` URL. Output: apps result. Raises:
    Raises: Http404 when validation or the called operation fails.
    """
    if app not in _APP_BASE_URLS:
        raise Http404(f"App: {app} not found")

    base_url = _APP_BASE_URLS[app]
    asset_path = _sanitize_app_asset_path(url)
    if asset_path:
        return HttpResponseRedirect(urljoin(base_url, asset_path))

    cache_bucket = int(time.time() // _APP_SHELL_CACHE_SECONDS)
    try:
        if app in _LOCAL_APP_SHELLS:
            html = _read_local_app_shell(_LOCAL_APP_SHELLS[app], cache_bucket)
        else:
            html = _fetch_remote_app_shell(base_url, cache_bucket)
    except (OSError, requests.RequestException):
        LOGGER.warning(
            "Failed to load app shell for %s",
            sanitize_log_value(app),
            exc_info=True,
        )
        return StreamingHttpResponse((), status=502)

    response = StreamingHttpResponse(
        (_inject_launcher_head(html, base_url),),
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = f"private, max-age={_APP_SHELL_CACHE_SECONDS}"
    return response
