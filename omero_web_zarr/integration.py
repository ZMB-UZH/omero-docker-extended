import base64
import logging
import time
import traceback
from functools import wraps

from django.conf import settings
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
import omero
from django.urls.resolvers import URLPattern, URLResolver
import numpy as np
from omero.rtypes import rlong
from omeroweb.httprsp import HttpJavascriptResponseServerError
from omeroweb.webclient.decorators import login_required
from omeroweb.webgateway.marshal import channelMarshal

from .utils import encode_store_backed_pil_image
from .utils import get_safe_image_tile_size
from .utils import get_store_backed_channel_overrides
from .utils import get_store_backed_level_count
from .utils import get_store_backed_level_sizes
from .utils import get_store_backed_tile_size
from .utils import get_store_backed_zoom_level_scaling
from .utils import is_known_tile_size_failure
from .utils import is_store_backed_image
from .utils import load_store_backed_image_node
from .utils import render_store_backed_pil_image
from .utils import render_store_backed_region_pil_image
from .utils import render_store_backed_thumbnail_bytes
from .utils import sanitize_download_basename
from .utils import select_store_backed_viewer_level

LOGGER = logging.getLogger(__name__)


class _StoreBackedChannelWrapper:
    def __init__(self, channel, override):
        self._channel = channel
        self._override = override or {}

    def __getattr__(self, name):
        return getattr(self._channel, name)

    def getLabel(self):
        label = self._override.get("label")
        if label:
            return label
        return self._channel.getLabel()

    def getColor(self):
        color = self._override.get("color")
        if color is None:
            return self._channel.getColor()
        from omero.gateway import ColorHolder

        return ColorHolder.fromRGBA(color[0], color[1], color[2], 255)

    def isActive(self):
        active = self._override.get("active")
        if active is None:
            return self._channel.isActive()
        return bool(active)

    def isInverted(self):
        inverted = self._override.get("inverted")
        if inverted is None:
            value = self._channel.isInverted()
            return False if value is None else bool(value)
        return bool(inverted)

    def getWindowStart(self):
        window = self._override.get("window")
        if window is None:
            return self._channel.getWindowStart()
        return window[0]

    def getWindowEnd(self):
        window = self._override.get("window")
        if window is None:
            return self._channel.getWindowEnd()
        return window[1]


def _decorate_store_backed_channels(image, channels):
    if not channels:
        return channels

    overrides = get_store_backed_channel_overrides(image, channels=channels)
    wrapped = []
    for index, channel in enumerate(channels):
        override = overrides[index] if index < len(overrides) else None
        wrapped.append(_StoreBackedChannelWrapper(channel, override))
    return wrapped


def _get_store_backed_image(conn, iid):
    image = conn.getObject("Image", iid)
    if image is None or not is_store_backed_image(image):
        return None
    return image


def _store_backed_render_response(image, request, z=None, t=None, download=False):
    requested_format = request.GET.get("format", "jpeg")
    pil_image = render_store_backed_pil_image(image, z=z, t=t)
    payload, content_type, suffix = encode_store_backed_pil_image(
        pil_image,
        requested_format,
    )

    if not download:
        return HttpResponse(payload, content_type=content_type)

    response = HttpResponse(payload, content_type="application/force-download")
    response["Content-Length"] = len(payload)
    filename = sanitize_download_basename(
        image.getName(),
        default=f"Image-{image.id}",
    )
    response["Content-Disposition"] = "attachment; filename=%s.%s" % (filename, suffix)
    return response


def _store_backed_pixel_range(node):
    metadata = getattr(node, "metadata", {}) or {}
    contrast_limits = metadata.get("contrast_limits") or []
    values = []
    for limits in contrast_limits:
        if isinstance(limits, (list, tuple)) and len(limits) >= 2:
            values.extend((float(limits[0]), float(limits[1])))
    if values:
        return (min(values), max(values))

    dtype = np.dtype(getattr(node.data[0], "dtype", np.uint8))
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return (int(info.min), int(info.max))
    if np.issubdtype(dtype, np.floating):
        return (0.0, 1.0)
    return (0, 255)


def _store_backed_rendering_model(channels):
    if len(channels) > 1:
        return "color"
    if not channels:
        return "greyscale"
    try:
        color = channels[0].getColor()
        if color is not None and color.getHtml() != "FFFFFF":
            return "color"
    except Exception:
        LOGGER.debug("Failed to inspect store-backed channel color", exc_info=True)
    return "greyscale"


def _store_backed_metadata(image):
    project = None
    dataset = None
    well = None
    try:
        project = image.getProject()
    except Exception:
        LOGGER.debug("Failed to resolve project for image %s", image.id, exc_info=True)

    try:
        parents = image.listParents()
        if parents is not None:
            datasets = [parent for parent in parents if parent.OMERO_CLASS == "Dataset"]
            wells = [parent for parent in parents if parent.OMERO_CLASS == "WellSample"]
            if len(datasets) == 1:
                dataset = datasets[0]
            if len(wells) == 1 and getattr(wells[0], "well", None) is not None:
                well = wells[0].well
    except Exception:
        LOGGER.debug(
            "Failed to resolve store-backed parents for image %s",
            image.id,
            exc_info=True,
        )

    image_name = getattr(image, "name", None) or image.getName() or ""
    return {
        "imageName": image_name,
        "imageDescription": image.description or "",
        "imageAuthor": image.getAuthor(),
        "imageArchived": image.archived or False,
        "projectName": project and project.name or "Multiple",
        "projectId": project and project.id or None,
        "projectDescription": project and project.description or "",
        "datasetName": dataset and dataset.name or "Multiple",
        "datasetId": dataset and dataset.id or None,
        "datasetDescription": dataset and dataset.description or "",
        "wellSampleId": "",
        "wellId": well and well.id.val or "",
        "imageTimestamp": time.mktime(image.getDate().timetuple()),
        "imageId": image.id,
        "pixelsType": image.getPixelsType(),
    }


def _pixel_size_in_microns(image):
    pixel_size = {}
    for axis, getter in (
        ("x", image.getPixelSizeX),
        ("y", image.getPixelSizeY),
        ("z", image.getPixelSizeZ),
    ):
        try:
            size = getter("MICROMETER")
            pixel_size[axis] = size.getValue() if size is not None else None
        except Exception:
            LOGGER.debug(
                "Unable to convert physical pixel size to microns",
                exc_info=True,
            )
            pixel_size[axis] = None
    return pixel_size


def _marshal_regular_image_data_with_safe_tile_size(image, request):
    payload = {
        "id": image.id,
        "meta": _store_backed_metadata(image),
        "perms": {
            "canAnnotate": image.canAnnotate(),
            "canEdit": image.canEdit(),
            "canDelete": image.canDelete(),
            "canLink": image.canLink(),
        },
    }
    try:
        rendering_engine_ready = image._prepareRenderingEngine()
        if not rendering_engine_ready:
            LOGGER.debug("Failed to prepare Rendering Engine for imageMarshal")
            return payload
    except omero.ConcurrencyException as concurrency_error:
        return {"ConcurrencyException": {"backOff": concurrency_error.backOff}}
    except Exception as exc:
        payload["Exception"] = getattr(exc, "message", str(exc))
        LOGGER.error(traceback.format_exc())
        return payload

    levels = image._re.getResolutionLevels()
    tiles = levels > 1
    payload["tiles"] = tiles
    if tiles:
        width, height = get_safe_image_tile_size(image, conn=getattr(image, "_conn", None))
        payload.update(
            {
                "tile_size": {"width": width, "height": height},
                "levels": levels,
            }
        )
        resolution_descriptions = image._re.getResolutionDescriptions()
        payload["resolutions"] = {
            index: {"sizeX": resolution.sizeX, "sizeY": resolution.sizeY}
            for index, resolution in enumerate(resolution_descriptions)
        }
        payload["zoomLevelScaling"] = {
            index: resolution.sizeX / resolution_descriptions[0].sizeX
            for index, resolution in enumerate(resolution_descriptions)
        }

    objective_settings = image.getObjectiveSettings()
    nominal_magnification = (
        objective_settings is not None
        and objective_settings.getObjective().getNominalMagnification()
        or None
    )

    try:
        viewer_settings = request.session.get("server_settings", {}).get("viewer", {})
    except Exception:
        viewer_settings = {}
    init_zoom = viewer_settings.get("initial_zoom_level", 0)
    if init_zoom is not None and init_zoom < 0:
        init_zoom = levels + init_zoom

    try:
        payload.update(
            {
                "interpolate": viewer_settings.get("interpolate_pixels", True),
                "size": {
                    "width": image.getSizeX(),
                    "height": image.getSizeY(),
                    "z": image.getSizeZ(),
                    "t": image.getSizeT(),
                    "c": image.getSizeC(),
                },
                "pixel_size": _pixel_size_in_microns(image),
            }
        )
        if init_zoom is not None:
            payload["init_zoom"] = init_zoom
        if nominal_magnification is not None:
            payload["nominalMagnification"] = nominal_magnification
        try:
            payload["pixel_range"] = image.getPixelRange()
            payload["channels"] = [channelMarshal(channel) for channel in image.getChannels()]
            payload["split_channel"] = image.splitChannelDims()
            payload["rdefs"] = {
                "model": image.isGreyscaleRenderingModel() and "greyscale" or "color",
                "projection": image.getProjection(),
                "defaultZ": image._re.getDefaultZ(),
                "defaultT": image._re.getDefaultT(),
                "invertAxis": image.isInvertedAxis(),
            }
        except TypeError:
            LOGGER.error("imageMarshal", exc_info=True)
            payload["pixel_range"] = (0, 0)
            payload["channels"] = ()
            payload["split_channel"] = ()
            payload["rdefs"] = {
                "model": "color",
                "projection": image.getProjection(),
                "defaultZ": 0,
                "defaultT": 0,
                "invertAxis": image.isInvertedAxis(),
            }
    except AttributeError:
        raise

    return payload


def _render_regular_image_region_with_safe_tile_size(request, iid, z, t, conn=None):
    from omeroweb.webgateway import views as webgateway_views

    server_id = request.session["connector"]["server_id"]
    prepared_image = webgateway_views._get_prepared_image(
        request,
        iid,
        server_id=server_id,
        conn=conn,
    )
    if prepared_image is None:
        raise Http404
    image, compress_quality = prepared_image

    tile = request.GET.get("tile")
    region = request.GET.get("region")
    level = None

    if tile:
        try:
            image._prepareRenderingEngine()
            width, height = get_safe_image_tile_size(image, conn=conn)
            max_viewer_level = image._re.getResolutionLevels() - 1

            fields = tile.split(",")
            if len(fields) > 4:
                requested_tile_size = [int(fields[3]), int(fields[4])]
                defaults = [width, height]
                max_tile_length = 1024
                if conn is not None:
                    try:
                        max_tile_length = int(
                            conn.getConfigService().getConfigValue(
                                "omero.pixeldata.max_tile_length"
                            )
                        )
                    except Exception:
                        LOGGER.debug(
                            "Failed to load max tile length from OMERO config",
                            exc_info=True,
                        )
                for index, tile_length in enumerate(requested_tile_size):
                    if tile_length <= 0:
                        requested_tile_size[index] = defaults[index]
                    if tile_length > max_tile_length:
                        requested_tile_size[index] = max_tile_length
                width, height = requested_tile_size

            viewer_level = int(fields[0])
            if viewer_level < 0:
                message = "Invalid resolution level %s < 0" % viewer_level
                LOGGER.debug(message, exc_info=True)
                return HttpResponseBadRequest(message)

            if max_viewer_level == 0:
                if viewer_level > 0:
                    message = "Invalid resolution level %s, non pyramid file" % viewer_level
                    LOGGER.debug(message, exc_info=True)
                    return HttpResponseBadRequest(message)
                level = None
            else:
                level = max_viewer_level - viewer_level
                if level < 0:
                    message = (
                        "Invalid resolution level, %s > number of available levels %s "
                        % (viewer_level, max_viewer_level)
                    )
                    LOGGER.debug(message, exc_info=True)
                    return HttpResponseBadRequest(message)

            x = int(fields[1]) * width
            y = int(fields[2]) * height
        except Exception:
            message = "malformed tile argument, tile=%s" % tile
            LOGGER.debug(message, exc_info=True)
            return HttpResponseBadRequest(message)
    elif region:
        try:
            x, y, width, height = [int(value) for value in region.split(",")]
        except Exception:
            message = "malformed region argument, region=%s" % region
            LOGGER.debug(message, exc_info=True)
            return HttpResponseBadRequest(message)
    else:
        return HttpResponseBadRequest("tile or region argument required")

    jpeg_data = image.renderJpegRegion(
        z,
        t,
        x,
        y,
        width,
        height,
        level=level,
        compression=compress_quality,
    )
    if jpeg_data is None:
        raise Http404
    return HttpResponse(jpeg_data, content_type="image/jpeg")


def _select_marshaled_key(payload, key):
    result = payload
    for part in key.split("."):
        if not isinstance(result, dict):
            return None
        result = result.get(part, {})
    return None if result == {} else result


def _store_backed_image_data(image, request):
    node = load_store_backed_image_node(image)
    channels = _decorate_store_backed_channels(image, image.getChannels(noRE=True))
    level_count = get_store_backed_level_count(node) if node is not None else 1
    level_sizes = get_store_backed_level_sizes(node) if node is not None else [
        {"sizeX": int(image.getSizeX()), "sizeY": int(image.getSizeY())}
    ]
    tile_size = get_store_backed_tile_size(node) if node is not None else {"width": 256, "height": 256}
    zoom_scaling = (
        get_store_backed_zoom_level_scaling(node)
        if node is not None
        else {0: 1.0}
    )

    tiles = level_count > 1
    conn = getattr(image, "_conn", None)
    if not tiles and conn is not None:
        try:
            max_plane_width, max_plane_height = conn.getMaxPlaneSize()
            tiles = (image.getSizeX() * image.getSizeY()) > (max_plane_width * max_plane_height)
        except Exception:
            LOGGER.debug(
                "Failed to determine store-backed tiling threshold for image %s",
                image.id,
                exc_info=True,
            )

    try:
        projection = image.getProjection()
    except Exception:
        projection = "normal"

    pixel_size = {}
    for axis, getter in (
        ("x", image.getPixelSizeX),
        ("y", image.getPixelSizeY),
        ("z", image.getPixelSizeZ),
    ):
        try:
            size = getter("MICROMETER")
        except Exception:
            size = None
        if size is not None:
            pixel_size[axis] = size.getValue()

    rv = {
        "id": image.id,
        "meta": _store_backed_metadata(image),
        "perms": {
            "canAnnotate": image.canAnnotate(),
            "canEdit": image.canEdit(),
            "canDelete": image.canDelete(),
            "canLink": image.canLink(),
        },
        "tiles": tiles,
        "interpolate": request.session.get("server_settings", {}).get("viewer", {}).get(
            "interpolate_pixels",
            True,
        ),
        "size": {
            "width": image.getSizeX(),
            "height": image.getSizeY(),
            "z": image.getSizeZ(),
            "t": image.getSizeT(),
            "c": image.getSizeC(),
        },
        "pixel_size": pixel_size,
        "pixel_range": _store_backed_pixel_range(node) if node is not None else (0, 0),
        "channels": [channelMarshal(channel) for channel in channels],
        "split_channel": image.splitChannelDims(),
        "rdefs": {
            "model": _store_backed_rendering_model(channels),
            "projection": projection,
            "defaultZ": 0,
            "defaultT": 0,
            "invertAxis": False,
        },
    }

    viewer_settings = request.session.get("server_settings", {}).get("viewer", {})
    init_zoom = viewer_settings.get("initial_zoom_level", 0)
    if init_zoom is not None:
        if init_zoom < 0:
            init_zoom = level_count + init_zoom
        rv["init_zoom"] = init_zoom

    try:
        objective_settings = image.getObjectiveSettings()
    except Exception:
        objective_settings = None
    if objective_settings is not None:
        objective = objective_settings.getObjective()
        if objective is not None:
            magnification = objective.getNominalMagnification()
            if magnification is not None:
                rv["nominalMagnification"] = magnification

    if tiles:
        rv.update(
            {
                "tile_size": tile_size,
                "levels": max(level_count, 1),
                "resolutions": {
                    index: level_sizes[index]
                    for index in range(len(level_sizes))
                },
                "zoomLevelScaling": zoom_scaling,
            }
        )

    return rv


def _store_backed_region_response(image, request, z=None, t=None, conn=None):
    node = load_store_backed_image_node(image)
    if node is None:
        return HttpResponseBadRequest("store-backed image data not found")

    tile = request.GET.get("tile")
    region = request.GET.get("region")
    level = 0
    if tile:
        try:
            tile_fields = tile.split(",")
            viewer_level = int(tile_fields[0])
            max_viewer_level = get_store_backed_level_count(node) - 1
            if viewer_level < 0 or viewer_level > max_viewer_level:
                return HttpResponseBadRequest("invalid resolution level")

            default_tile_size = get_store_backed_tile_size(node)
            width = default_tile_size["width"]
            height = default_tile_size["height"]
            if len(tile_fields) > 4:
                width = int(tile_fields[3])
                height = int(tile_fields[4])
                max_tile_length = 1024
                if conn is not None:
                    try:
                        max_tile_length = int(
                            conn.getConfigService().getConfigValue(
                                "omero.pixeldata.max_tile_length"
                            )
                        )
                    except Exception:
                        LOGGER.debug(
                            "Failed to load max tile length from OMERO config",
                            exc_info=True,
                        )
                width = min(max(width, 1), max_tile_length)
                height = min(max(height, 1), max_tile_length)

            x = int(tile_fields[1]) * width
            y = int(tile_fields[2]) * height
            level = select_store_backed_viewer_level(node, viewer_level)
        except Exception:
            LOGGER.debug("Malformed tile request for store-backed region", exc_info=True)
            return HttpResponseBadRequest("malformed tile argument")
    elif region:
        try:
            x, y, width, height = [int(value) for value in region.split(",")]
        except Exception:
            LOGGER.debug("Malformed region request for store-backed image", exc_info=True)
            return HttpResponseBadRequest("malformed region argument")
    else:
        return HttpResponseBadRequest("tile or region argument required")

    pil_image = render_store_backed_region_pil_image(
        image,
        x=x,
        y=y,
        width=width,
        height=height,
        z=z,
        t=t,
        level=level,
    )
    payload, content_type, _ = encode_store_backed_pil_image(pil_image, "jpeg")
    return HttpResponse(payload, content_type=content_type)


def _patch_urlpatterns(urlpatterns, replacements):
    for pattern in urlpatterns:
        if isinstance(pattern, URLResolver):
            _patch_urlpatterns(pattern.url_patterns, replacements)
            continue
        if not isinstance(pattern, URLPattern):
            continue
        replacement = replacements.get(pattern.name)
        if replacement is not None:
            pattern._callback = replacement


def install_webgateway_overrides():
    try:
        from omeroweb.webgateway import urls as webgateway_urls
        from omeroweb.webgateway import views as webgateway_views
        from omeroweb.webclient import webclient_gateway
    except ImportError:
        return

    if getattr(webgateway_views, "_omero_web_zarr_store_backed_overrides", False):
        return

    original_get_channels = webclient_gateway.ImageWrapper.getChannels
    original_image_data_json = webgateway_views.imageData_json
    original_render_thumbnail = webgateway_views._render_thumbnail
    original_get_thumbnails_json = webgateway_views.get_thumbnails_json
    original_render_image = webgateway_views.render_image
    original_render_image_region = webgateway_views.render_image_region
    original_image_data_json_impl = getattr(
        getattr(original_image_data_json, "__wrapped__", None),
        "__wrapped__",
        original_image_data_json,
    )
    original_render_image_region_impl = getattr(
        original_render_image_region,
        "__wrapped__",
        original_render_image_region,
    )

    @wraps(original_get_channels)
    def get_channels_override(self, *args, **kwargs):
        if not is_store_backed_image(self):
            return original_get_channels(self, *args, **kwargs)
        channels = original_get_channels(self, noRE=True)
        return _decorate_store_backed_channels(self, channels)

    def render_thumbnail_override(
        request,
        iid,
        w=None,
        h=None,
        conn=None,
        _defcb=None,
        **kwargs,
    ):
        image = _get_store_backed_image(conn, iid)
        if image is None:
            return original_render_thumbnail(
                request=request,
                iid=iid,
                w=w,
                h=h,
                conn=conn,
                _defcb=_defcb,
                **kwargs,
            )

        server_settings = request.session.get("server_settings", {}).get("browser", {})
        default_size = server_settings.get("thumb_default_size", 96)
        if w is None:
            size = default_size
        elif h is None:
            size = int(w)
        else:
            size = max(int(w), int(h))

        z_index = webgateway_views.getIntOrDefault(request, "z", None)
        t_index = webgateway_views.getIntOrDefault(request, "t", None)
        return render_store_backed_thumbnail_bytes(
            image,
            size=size,
            z=z_index,
            t=t_index,
        )

    @wraps(original_get_thumbnails_json)
    def get_thumbnails_json_override(request, w=None, conn=None, **kwargs):
        image_ids = list(set(webgateway_views.get_longs(request, "id")))
        if len(image_ids) <= 1:
            return original_get_thumbnails_json(request, w=w, conn=conn, **kwargs)

        server_settings = request.session.get("server_settings", {}).get("browser", {})
        default_size = server_settings.get("thumb_default_size", 96)
        if w is None:
            w = default_size

        if len(image_ids) > settings.THUMBNAILS_BATCH:
            return HttpJavascriptResponseServerError(
                "Max %s thumbnails at a time." % settings.THUMBNAILS_BATCH
            )

        response = {}
        regular_ids = []
        z_index = webgateway_views.getIntOrDefault(request, "z", None)
        t_index = webgateway_views.getIntOrDefault(request, "t", None)

        for image_id in image_ids:
            image = _get_store_backed_image(conn, image_id)
            if image is None:
                regular_ids.append(image_id)
                continue
            try:
                thumbnail = render_store_backed_thumbnail_bytes(
                    image,
                    size=w,
                    z=z_index,
                    t=t_index,
                )
                response[image_id] = "data:image/jpeg;base64,%s" % base64.b64encode(
                    thumbnail
                ).decode("utf-8")
            except Exception:
                LOGGER.error(
                    "Failed to render store-backed thumbnail for image %s",
                    image_id,
                )
                LOGGER.error(traceback.format_exc())
                response[image_id] = None

        if regular_ids:
            thumbnails = conn.getThumbnailSet([rlong(i) for i in regular_ids], w)
            for image_id in regular_ids:
                response[image_id] = None
                try:
                    payload = thumbnails[image_id]
                    if payload:
                        response[image_id] = "data:image/jpeg;base64,%s" % base64.b64encode(
                            payload
                        ).decode("utf-8")
                except KeyError:
                    LOGGER.error("Thumbnail not available. (img id: %d)", image_id)
                except Exception:
                    LOGGER.error(traceback.format_exc())

        return response

    @wraps(original_render_image)
    def render_image_override(request, iid, z=None, t=None, conn=None, **kwargs):
        image = _get_store_backed_image(conn, iid)
        if image is None:
            return original_render_image(request, iid, z=z, t=t, conn=conn, **kwargs)
        return _store_backed_render_response(
            image,
            request,
            z=z,
            t=t,
            download=bool(kwargs.get("download")),
        )

    @wraps(original_render_image_region)
    def render_image_region_override(request, iid, z, t, conn=None, **kwargs):
        image = _get_store_backed_image(conn, iid)
        if image is None:
            try:
                return original_render_image_region_impl(
                    request,
                    iid,
                    z,
                    t,
                    conn=conn,
                    **kwargs,
                )
            except Exception as exc:
                if not is_known_tile_size_failure(exc):
                    raise
                return _render_regular_image_region_with_safe_tile_size(
                    request,
                    iid,
                    z,
                    t,
                    conn=conn,
                )
        return _store_backed_region_response(
            image,
            request,
            z=z,
            t=t,
            conn=conn,
        )

    @wraps(original_image_data_json)
    def image_data_json_override(request, conn=None, _internal=False, **kwargs):
        image = conn.getObject("Image", kwargs["iid"])
        if image is None:
            return original_image_data_json_impl(
                request,
                conn=conn,
                _internal=_internal,
                **kwargs,
            )
        if not is_store_backed_image(image):
            try:
                return original_image_data_json_impl(
                    request,
                    conn=conn,
                    _internal=_internal,
                    **kwargs,
                )
            except Exception as exc:
                if not is_known_tile_size_failure(exc):
                    raise
                payload = _marshal_regular_image_data_with_safe_tile_size(
                    image,
                    request,
                )
                key = kwargs.get("key")
                if key is not None:
                    payload = _select_marshaled_key(payload, key)
                return payload

        payload = _store_backed_image_data(image, request)
        key = kwargs.get("key")
        if key is not None:
            payload = _select_marshaled_key(payload, key)
        return payload

    decorated_get_thumbnails_json = login_required()(webgateway_views.jsonp(get_thumbnails_json_override))
    decorated_image_data_json = login_required()(webgateway_views.jsonp(image_data_json_override))
    decorated_render_image = login_required()(render_image_override)
    decorated_render_image_region = login_required()(render_image_region_override)

    webclient_gateway.ImageWrapper.getChannels = get_channels_override
    webgateway_views.imageData_json = decorated_image_data_json
    webgateway_views._render_thumbnail = render_thumbnail_override
    webgateway_views.get_thumbnails_json = decorated_get_thumbnails_json
    webgateway_views.render_image = decorated_render_image
    webgateway_views.render_image_region = decorated_render_image_region

    _patch_urlpatterns(
        webgateway_urls.urlpatterns,
        {
            "webgateway_imageData_json": decorated_image_data_json,
            "webgateway_get_thumbnails_json": decorated_get_thumbnails_json,
            "webgateway_render_image": decorated_render_image,
            "webgateway_render_image_region": decorated_render_image_region,
        },
    )

    try:
        from omeroweb.webclient import urls as webclient_urls
    except ImportError:
        webclient_urls = None
    if webclient_urls is not None:
        _patch_urlpatterns(
            webclient_urls.urlpatterns,
            {
                "web_imageData_json": decorated_image_data_json,
                "get_thumbnails_json": decorated_get_thumbnails_json,
                "web_render_image_download": decorated_render_image,
                "web_render_image_region": decorated_render_image_region,
            },
        )

    webgateway_views._omero_web_zarr_store_backed_overrides = True
