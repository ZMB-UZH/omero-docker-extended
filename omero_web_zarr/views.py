from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
import json
import numpy as np
import os
import requests
import tempfile

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
from .utils import marshal_axes
from .utils import marshal_axes_v3
from .utils import open_compat_array

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


@login_required()
def index(request, conn=None, **kwargs):
    home = request.build_absolute_uri(reverse("omero_web_zarr_index"))
    return HttpResponse(
        "To open an Image in Vizarr go to "
        "https://hms-dbmi.github.io/vizarr/?source=%simage/[IMAGE_ID].zarr" % home
    )


@login_required()
def image_zattrs(request, iid, version, conn=None, **kwargs):
    if version not in ("0.3", "0.4"):
        raise Http404("version not supported")

    image = conn.getObject("Image", iid)

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
    for dim in ("TCZ"):
        if getattr(image, "getSize" + dim)() > 1:
            chunks.append(1)
    if image.requiresPixelsPyramid():
        image.getZoomLevelScaling()
        width, height = image._re.getTileSize()
    else:
        width = image.getSizeY()
        height = image.getSizeX()
    chunks.extend([height, width])
    return chunks


@login_required()
def image_zarray(request, iid, level, conn=None, **kwargs):
    level = int(level)
    image = conn.getObject("Image", iid)
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


def apps(request, app, url):
    source = request.GET.get("source")
    if source is not None and not source.startswith("http"):
        source = request.build_absolute_uri(source)
        new_url = reverse("zarr_app", kwargs={"url": "", "app": app})
        return redirect(new_url + "?source=" + source)

    base_urls = {
        "vizarr": "https://hms-dbmi.github.io/vizarr/",
        "validator": "https://ome.github.io/ome-ngff-validator/",
    }
    if app not in base_urls:
        raise Http404("App: %s not found" % app)

    target_url = base_urls[app] + url
    response = requests.get(target_url, timeout=20)
    rsp = HttpResponse(response.content, status=response.status_code)
    content_type = response.headers.get("content-type")
    if content_type:
        rsp["content-type"] = content_type
    elif url.endswith(".js"):
        rsp["content-type"] = "application/javascript"
    return rsp
