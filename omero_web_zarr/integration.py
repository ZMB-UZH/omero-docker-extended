import base64
import json
import logging
import time
import traceback
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.urls.resolvers import URLPattern, URLResolver
import numpy as np
import omero
from omero.rtypes import rlong
from omeroweb.httprsp import HttpJavascriptResponseServerError
from omeroweb.webclient.decorators import login_required
from omeroweb.webgateway.marshal import channelMarshal

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_bool_env
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info

from .utils import encode_store_backed_pil_image
from .utils import get_safe_image_tile_size
from .utils import get_image_connection
from .utils import prepare_image_rendering_engine
from .utils import require_image_rendering_engine
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


_SAFE_RENDERING_ENV = "OMERO_WEB_ZARR_ALTERNATIVE_RENDERING"
_REGULAR_IMAGE_RENDERING_ERROR = "Image rendering metadata is unavailable."


def _safe_rendering_enabled():
    """Return safe rendering enabled.

    Inputs: none. Output: `get_bool_env` result.
    """
    return get_bool_env(_SAFE_RENDERING_ENV, env_file=ENV_FILE_OMEROWEB)


def _require_webgateway_callable(module, name):
    """Require the webgateway callable.

    Inputs: `module` module object, `name` name. Output: `hook`. Raises: AttributeError
    when validation or the called operation fails.
    """
    hook = getattr(module, name, None)
    if callable(hook):
        return hook
    module_name = getattr(module, "__name__", type(module).__name__)
    raise AttributeError(f"{module_name}.{name} is unavailable")


class _StoreBackedChannelWrapper:
    """Helper type for store backed channel wrapper behavior."""

    def __init__(self, channel, override):
        """Create `_StoreBackedChannelWrapper` with `channel` and `override`.

        Inputs: `channel`, `override`. Output: None.
        """
        self._channel = channel
        self._override = override or {}

    def __getattr__(self, name):
        """Return a dynamic attribute value by name.

        Inputs: `name`. Output: `getattr` result.
        """
        return getattr(self._channel, name)

    def getLabel(self):
        """Return the label for `_StoreBackedChannelWrapper`.

        Inputs: none. Output: `getLabel` result.
        """
        label = self._override.get("label")
        if label:
            return label
        return self._channel.getLabel()

    def getColor(self):
        """Return the color for `_StoreBackedChannelWrapper`.

        Inputs: none. Output: `fromRGBA` result.
        """
        color = self._override.get("color")
        if color is None:
            return self._channel.getColor()
        from omero.gateway import ColorHolder

        return ColorHolder.fromRGBA(color[0], color[1], color[2], 255)

    def isActive(self):
        """Report the active boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `bool`.
        """
        active = self._override.get("active")
        if active is None:
            return self._channel.isActive()
        return bool(active)

    def isInverted(self):
        """Report the inverted boolean exposed by this OMERO-compatible object.

        Inputs: none. Output: `bool`.
        """
        inverted = self._override.get("inverted")
        if inverted is None:
            value = self._channel.isInverted()
            return False if value is None else bool(value)
        return bool(inverted)

    def getWindowStart(self):
        """Return the window start value exposed by this OMERO-compatible object.

        Inputs: none. Output: get window start result.
        """
        window = self._override.get("window")
        if window is None:
            return self._channel.getWindowStart()
        return window[0]

    def getWindowEnd(self):
        """Return the window end value exposed by this OMERO-compatible object.

        Inputs: none. Output: get window end result.
        """
        window = self._override.get("window")
        if window is None:
            return self._channel.getWindowEnd()
        return window[1]


def _decorate_store_backed_channels(image, channels):
    """Return the decorate store backed channels.

    Inputs: `image`, `channels`. Output: `wrapped`.
    """
    if not channels:
        return channels

    overrides = get_store_backed_channel_overrides(image, channels=channels)
    wrapped = []
    for index, channel in enumerate(channels):
        override = overrides[index] if index < len(overrides) else None
        wrapped.append(_StoreBackedChannelWrapper(channel, override))
    return wrapped


def _get_store_backed_image(conn, iid):
    """Return store backed image.

    Inputs: `conn`, `iid`. Output: `image` or None.
    """
    image = conn.getObject("Image", iid)
    if image is None or not is_store_backed_image(image):
        return None
    return image


def _store_backed_render_response(image, request, z=None, t=None, download=False):
    """Backed render response.

    Inputs: `image`, `request` Django request, `z`, `t`, `download`. Output: response
    object.
    """
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
    response["Content-Disposition"] = f"attachment; filename={filename}.{suffix}"
    return response


def _store_backed_pixel_range(node):
    """Backed pixel range.

    Inputs: `node`. Output: tuple.
    """
    metadata = getattr(node, "metadata", {}) or {}
    contrast_limits = metadata.get("contrast_limits") or []
    values: list[float] = []
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
    """Backed rendering model.

    Inputs: `channels`. Output: `str`.
    """
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


def _store_backed_project(image):
    """Return the store backed project.

    Inputs: `image`. Output: `getProject` result.
    """
    try:
        return image.getProject()
    except Exception:
        LOGGER.debug("Failed to resolve project for image %s", image.id, exc_info=True)
        return None


def _store_backed_parent_context(image):
    """Backed parent context.

    Inputs: `image`. Output: tuple.
    """
    dataset = None
    well = None
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
    return dataset, well


def _truthy_attribute(entity, name, default):
    """Return the truthy attribute.

    Inputs: `entity`, `name` name, `default`. Output: `bool`.
    """
    if entity is None:
        return default
    value = getattr(entity, name)
    return value or default


def _store_backed_well_id(well):
    """Backed well ID.

    Inputs: `well`. Output: `bool`.
    """
    if well is None:
        return ""
    return well.id.val or ""


def _store_backed_metadata(image):
    """Return the store backed metadata.

    Inputs: `image`. Output: `dict`.
    """
    project = _store_backed_project(image)
    dataset, well = _store_backed_parent_context(image)

    image_name = getattr(image, "name", None) or image.getName() or ""
    return {
        "imageName": image_name,
        "imageDescription": _truthy_attribute(image, "description", ""),
        "imageAuthor": image.getAuthor(),
        "imageArchived": _truthy_attribute(image, "archived", False),
        "projectName": _truthy_attribute(project, "name", "Multiple"),
        "projectId": _truthy_attribute(project, "id", None),
        "projectDescription": _truthy_attribute(project, "description", ""),
        "datasetName": _truthy_attribute(dataset, "name", "Multiple"),
        "datasetId": _truthy_attribute(dataset, "id", None),
        "datasetDescription": _truthy_attribute(dataset, "description", ""),
        "wellSampleId": "",
        "wellId": _store_backed_well_id(well),
        "imageTimestamp": time.mktime(image.getDate().timetuple()),
        "imageId": image.id,
        "pixelsType": image.getPixelsType(),
    }


def _exception_text(exc):
    """Return the exception text.

    Inputs: `exc`. Output: `join` result.
    """
    parts = [
        str(exc),
        getattr(exc, "message", None),
        getattr(exc, "serverStackTrace", None),
    ]
    return "\n".join(str(part) for part in parts if part)


def _is_known_rendering_engine_failure(exc):
    """Return whether known rendering engine failure.

    Inputs: `exc`. Output: bool.
    """
    text = _exception_text(exc)
    return is_known_tile_size_failure(exc) or (
        "Error instantiating pixel buffer" in text
        and "ZarrPixelsService.getPixelBuffer" in text
    )


def _pixel_size_in_microns(image):
    """Return the pixel size in microns.

    Inputs: `image`. Output: `pixel_size`.
    """
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


def _regular_image_marshal_base_payload(image):
    """Return the regular image marshal base payload.

    Inputs: `image`. Output: `dict`.
    """
    return {
        "id": image.id,
        "meta": _store_backed_metadata(image),
        "perms": {
            "canAnnotate": image.canAnnotate(),
            "canEdit": image.canEdit(),
            "canDelete": image.canDelete(),
            "canLink": image.canLink(),
        },
    }


def _regular_image_rendering_engine_or_payload(image, payload):
    """Return the regular image rendering engine or payload.

    Inputs: `image`, `payload` payload. Output: `tuple`.
    """
    try:
        rendering_engine_ready = prepare_image_rendering_engine(image)
        if not rendering_engine_ready:
            LOGGER.debug("Failed to prepare Rendering Engine for imageMarshal")
            return None, payload
    except omero.ConcurrencyException as concurrency_error:
        return None, {"ConcurrencyException": {"backOff": concurrency_error.backOff}}
    except Exception as exc:
        payload["Exception"] = _REGULAR_IMAGE_RENDERING_ERROR
        LOGGER.error(
            "Failed to prepare regular image rendering engine for imageMarshal: %s",
            sanitize_log_value(exc),
            exc_info=sanitized_exc_info(exc),
        )
        return None, payload
    return require_image_rendering_engine(image), None


def _apply_regular_tile_metadata(payload, image, rendering_engine):
    """Apply the regular tile metadata.

    Inputs: `payload` payload, `image`, `rendering_engine`. Output: `levels`.
    """
    levels = rendering_engine.getResolutionLevels()
    tiles = levels > 1
    payload["tiles"] = tiles
    if tiles:
        width, height = get_safe_image_tile_size(
            image, conn=get_image_connection(image)
        )
        payload.update(
            {
                "tile_size": {"width": width, "height": height},
                "levels": levels,
            }
        )
        resolution_descriptions = rendering_engine.getResolutionDescriptions()
        payload["resolutions"] = {
            index: {"sizeX": resolution.sizeX, "sizeY": resolution.sizeY}
            for index, resolution in enumerate(resolution_descriptions)
        }
        payload["zoomLevelScaling"] = {
            index: resolution.sizeX / resolution_descriptions[0].sizeX
            for index, resolution in enumerate(resolution_descriptions)
        }
    return levels


def _regular_nominal_magnification(image):
    """Return the regular nominal magnification.

    Inputs: `image`. Output: `bool`.
    """
    objective_settings = image.getObjectiveSettings()
    return (
        objective_settings is not None
        and objective_settings.getObjective().getNominalMagnification()
        or None
    )


def _regular_viewer_settings(request):
    """Return the regular viewer settings.

    Inputs: `request` Django request. Output: `get` result.
    """
    try:
        return request.session.get("server_settings", {}).get("viewer", {})
    except Exception:
        return {}


def _regular_initial_zoom(viewer_settings, levels):
    """Return the regular initial zoom.

    Inputs: `viewer_settings`, `levels`. Output: `init_zoom`.
    """
    init_zoom = viewer_settings.get("initial_zoom_level", 0)
    if init_zoom is not None and init_zoom < 0:
        return levels + init_zoom
    return init_zoom


def _apply_regular_viewer_metadata(payload, image, viewer_settings, levels):
    """Apply the regular viewer metadata.

    Inputs: `payload` payload, `image`, `viewer_settings`, `levels`. Output: None.
    """
    init_zoom = _regular_initial_zoom(viewer_settings, levels)
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


def _apply_regular_objective_metadata(payload, image):
    """Apply the regular objective metadata.

    Inputs: `payload` payload, `image`. Output: None.
    """
    nominal_magnification = _regular_nominal_magnification(image)
    if nominal_magnification is not None:
        payload["nominalMagnification"] = nominal_magnification


def _apply_regular_channel_metadata(payload, image, rendering_engine):
    """Apply the regular channel metadata.

    Inputs: `payload` payload, `image`, `rendering_engine`. Output: None.
    """
    try:
        payload["pixel_range"] = image.getPixelRange()
        payload["channels"] = [
            channelMarshal(channel) for channel in image.getChannels()
        ]
        payload["split_channel"] = image.splitChannelDims()
        payload["rdefs"] = {
            "model": image.isGreyscaleRenderingModel() and "greyscale" or "color",
            "projection": image.getProjection(),
            "defaultZ": rendering_engine.getDefaultZ(),
            "defaultT": rendering_engine.getDefaultT(),
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


def _marshal_regular_image_data_with_safe_tile_size(image, request):
    """Return the marshal regular image data with safe tile size.

    Inputs: `image`, `request` Django request. Output: `int` size.
    """
    payload = _regular_image_marshal_base_payload(image)
    rendering_engine, fallback_payload = _regular_image_rendering_engine_or_payload(
        image, payload
    )
    if fallback_payload is not None:
        return fallback_payload

    levels = _apply_regular_tile_metadata(payload, image, rendering_engine)
    viewer_settings = _regular_viewer_settings(request)
    _apply_regular_viewer_metadata(payload, image, viewer_settings, levels)
    _apply_regular_objective_metadata(payload, image)
    _apply_regular_channel_metadata(payload, image, rendering_engine)
    return payload


def _select_marshaled_key(payload, key):
    """Select the marshaled key.

    Inputs: `payload` payload, `key` lookup key. Output: select marshaled key result.
    """
    result = payload
    for part in key.split("."):
        if not isinstance(result, dict):
            return None
        result = result.get(part, {})
    return None if result == {} else result


def _regular_region_bad_request(message):
    """Return the regular region bad request.

    Inputs: `message`. Output: Django bad-request response.
    """
    return HttpResponseBadRequest(message, content_type="text/plain; charset=utf-8")


def _prepared_regular_region_image(request, iid, conn=None):
    """Return the prepared regular region image.

    Inputs: `request` Django request, `iid`, `conn` OMERO gateway connection. Output:
    `prepared_image`. Raises: Http404 when validation or the called operation fails.
    """
    from omeroweb.webgateway import views as webgateway_views

    server_id = request.session["connector"]["server_id"]
    get_prepared_image = _require_webgateway_callable(
        webgateway_views, "_get_prepared_image"
    )
    prepared_image = get_prepared_image(
        request,
        iid,
        server_id=server_id,
        conn=conn,
    )
    if prepared_image is None:
        raise Http404
    return prepared_image


def _regular_max_tile_length(conn):
    """Return the regular max tile length.

    Inputs: `conn` OMERO gateway connection. Output: `max_tile_length`.
    """
    max_tile_length = 1024
    if conn is None:
        return max_tile_length
    try:
        return int(
            conn.getConfigService().getConfigValue("omero.pixeldata.max_tile_length")
        )
    except Exception:
        LOGGER.debug(
            "Failed to load max tile length from OMERO config",
            exc_info=True,
        )
        return max_tile_length


def _regular_requested_tile_size(fields, width, height, conn=None):
    """Return the regular requested tile size.

    Inputs: `fields`, `width`, `height`, `conn` OMERO gateway connection. Output:
    `requested_tile_size`.
    """
    if len(fields) <= 4:
        return width, height
    requested_tile_size = [int(fields[3]), int(fields[4])]
    defaults = [width, height]
    max_tile_length = _regular_max_tile_length(conn)
    for index, tile_length in enumerate(requested_tile_size):
        if tile_length <= 0:
            requested_tile_size[index] = defaults[index]
        if tile_length > max_tile_length:
            requested_tile_size[index] = max_tile_length
    return requested_tile_size


def _regular_viewer_level(viewer_level, max_viewer_level):
    """Return the regular viewer level.

    Inputs: `viewer_level`, `max_viewer_level`. Output: `tuple`.
    """
    if viewer_level < 0:
        return None, "invalid resolution level"
    if max_viewer_level == 0:
        if viewer_level > 0:
            return None, "invalid resolution level"
        return None, None
    level = max_viewer_level - viewer_level
    if level < 0:
        return None, "invalid resolution level"
    return level, None


def _regular_tile_region_args(request, image, conn=None):
    """Return the regular tile region args.

    Inputs: `request` Django request, `image`, `conn` OMERO gateway connection. Output:
    `tuple`.
    """
    try:
        prepare_image_rendering_engine(image)
        width, height = get_safe_image_tile_size(image, conn=conn)
        rendering_engine = require_image_rendering_engine(image)
        max_viewer_level = rendering_engine.getResolutionLevels() - 1
        fields = request.GET["tile"].split(",")
        width, height = _regular_requested_tile_size(fields, width, height, conn=conn)
        viewer_level = int(fields[0])
        level, message = _regular_viewer_level(viewer_level, max_viewer_level)
        if message is not None:
            LOGGER.debug(message, exc_info=True)
            return _regular_region_bad_request(message)
        return int(fields[1]) * width, int(fields[2]) * height, width, height, level
    except Exception:
        message = "malformed tile argument"
        LOGGER.debug("%s; rejected tile argument", message, exc_info=True)
        return _regular_region_bad_request(message)


def _regular_explicit_region_args(region):
    """Return the regular explicit region args.

    Inputs: `region`. Output: `tuple`.
    """
    try:
        x, y, width, height = [int(value) for value in region.split(",")]
    except Exception:
        message = "malformed region argument"
        LOGGER.debug("%s; rejected region argument", message, exc_info=True)
        return _regular_region_bad_request(message)
    return x, y, width, height, None


def _regular_region_args(request, image, conn=None):
    """Return the regular region args.

    Inputs: `request` Django request, `image`, `conn` OMERO gateway connection. Output:
    `_regular_region_bad_request` result.
    """
    if request.GET.get("tile"):
        return _regular_tile_region_args(request, image, conn=conn)
    region = request.GET.get("region")
    if region:
        return _regular_explicit_region_args(region)
    return _regular_region_bad_request("tile or region argument required")


def _render_regular_image_region_with_safe_tile_size(request, iid, z, t, conn=None):
    """Render the regular image region with safe tile size.

    Inputs: `request` Django request, `iid`, `z`, `t`, `conn` OMERO gateway connection.
    Output: Django `HttpResponse`. Raises: Http404 for the exercised failure path.
    """
    image, compress_quality = _prepared_regular_region_image(request, iid, conn=conn)
    region_args = _regular_region_args(request, image, conn=conn)
    if isinstance(region_args, HttpResponse):
        return region_args
    x, y, width, height, level = region_args

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


def _safe_regular_image_marshal(original_image_marshal, image, key=None, request=None):
    """Return safe regular image marshal.

    Inputs: `original_image_marshal`, `image`, `key` lookup key, `request` Django
    request. Output: `original_image_marshal` result.
    """
    try:
        return original_image_marshal(image, key=key, request=request)
    except Exception as exc:
        if not is_known_tile_size_failure(exc):
            raise
        payload = _marshal_regular_image_data_with_safe_tile_size(image, request)
        if key is not None:
            payload = _select_marshaled_key(payload, key)
        return payload


def _install_safe_image_marshal_overrides(webgateway_marshal):
    """Install the safe image marshal overrides.

    Inputs: `webgateway_marshal`. Output: `safe_image_marshal`.
    """
    if getattr(
        webgateway_marshal, "_omero_web_zarr_safe_image_marshal_installed", False
    ):
        return webgateway_marshal.imageMarshal

    original_image_marshal = webgateway_marshal.imageMarshal

    @wraps(original_image_marshal)
    def safe_image_marshal(image, key=None, request=None):
        """Return safe image marshal.

        Inputs: `image`, `key` lookup key, `request` Django request. Output:
        `_safe_regular_image_marshal` result.
        """
        return _safe_regular_image_marshal(
            original_image_marshal,
            image,
            key=key,
            request=request,
        )

    webgateway_marshal.imageMarshal = safe_image_marshal
    setattr(
        webgateway_marshal,
        "_omero_web_zarr_original_image_marshal",
        original_image_marshal,
    )
    setattr(webgateway_marshal, "_omero_web_zarr_safe_image_marshal_installed", True)

    candidate_modules: list[Any] = []
    from omeroweb.webgateway import views as webgateway_views

    candidate_modules.append(webgateway_views)
    try:
        import omero_iviewer.views as iviewer_views
    except ImportError:
        pass
    else:
        candidate_modules.append(iviewer_views)
    try:
        import omero_figure.views as figure_views
    except ImportError:
        pass
    else:
        candidate_modules.append(figure_views)

    for module in candidate_modules:
        if getattr(module, "imageMarshal", None) is not None:
            setattr(module, "imageMarshal", safe_image_marshal)

    return safe_image_marshal


def _load_metadata_preview_with_safe_rendering(
    request, c_type, c_id, conn=None, share_id=None, **kwargs
):
    """Load the metadata preview with safe rendering.

    Inputs: `request` Django request, `c_type`, `c_id`, `conn` OMERO gateway connection,
    `share_id`, `**kwargs` keyword arguments. Output: `context`.
    """
    from omeroweb.webclient import views as webclient_views

    context: dict[str, Any] = {}
    index = webclient_views.getIntOrDefault(request, "index", 0)
    manager = webclient_views.BaseContainer(conn, **{str(c_type): int(c_id)})
    if share_id:
        context["share"] = webclient_views.BaseShare(conn, share_id)
    if c_type == "well":
        manager.image = manager.well.getImage(index)

    rdefs: list[Any] = []
    rdef_queries: list[dict[str, Any]] = []
    try:
        all_rdefs = manager.image.getAllRenderingDefs()
        current_rdef_id = manager.image.getRenderingDefId()
    except Exception as exc:
        if not _is_known_rendering_engine_failure(exc):
            raise
        LOGGER.warning(
            "Using metadata preview fallback without rendering definitions for image %s",
            getattr(manager.image, "id", c_id),
        )
    else:
        deduped_rdefs: dict[Any, dict[str, Any]] = {}
        for rendering_def in all_rdefs:
            owner_id = rendering_def["owner"]["id"]
            rendering_def["current"] = rendering_def["id"] == current_rdef_id
            if (
                owner_id not in deduped_rdefs
                or deduped_rdefs[owner_id]["id"] < rendering_def["id"]
            ):
                deduped_rdefs[owner_id] = rendering_def
        rdefs = list(deduped_rdefs.values())
        for rendering_def in rdefs:
            channels: list[str] = []
            for index, channel in enumerate(rendering_def["c"]):
                active_prefix = "" if channel["active"] else "-"
                color = channel["lut"] if "lut" in channel else channel["color"]
                reverse = "r" if channel["inverted"] else "-r"
                channels.append(
                    f"{active_prefix}{index + 1}|"
                    f"{channel['start']}:{channel['end']}{reverse}${color}"
                )
            rdef_queries.append(
                {
                    "id": rendering_def["id"],
                    "owner": rendering_def["owner"],
                    "c": ",".join(channels),
                    "m": rendering_def["model"] == "greyscale" and "g" or "c",
                }
            )

    max_w, max_h = conn.getMaxPlaneSize()
    size_x = manager.image.getSizeX()
    size_y = manager.image.getSizeY()

    context["tiledImage"] = (size_x * size_y) > (max_w * max_h)
    context["manager"] = manager
    context["rdefsJson"] = json.dumps(rdef_queries)
    context["rdefs"] = rdefs
    context["template"] = "webclient/annotations/metadata_preview.html"
    return context


def _store_backed_level_metadata(image, node):
    """Backed level metadata.

    Inputs: `image`, `node`. Output: tuple.
    """
    level_count = get_store_backed_level_count(node) if node is not None else 1
    level_sizes = (
        get_store_backed_level_sizes(node)
        if node is not None
        else [{"sizeX": int(image.getSizeX()), "sizeY": int(image.getSizeY())}]
    )
    tile_size = (
        get_store_backed_tile_size(node)
        if node is not None
        else {"width": 256, "height": 256}
    )
    zoom_scaling = (
        get_store_backed_zoom_level_scaling(node) if node is not None else {0: 1.0}
    )
    return level_count, level_sizes, tile_size, zoom_scaling


def _store_backed_tiles_enabled(image, level_count):
    """Backed tiles enabled.

    Inputs: `image`, `level_count`. Output: `tiles`.
    """
    tiles = level_count > 1
    conn = get_image_connection(image)
    if not tiles and conn is not None:
        try:
            max_plane_width, max_plane_height = conn.getMaxPlaneSize()
            tiles = (image.getSizeX() * image.getSizeY()) > (
                max_plane_width * max_plane_height
            )
        except Exception:
            LOGGER.debug(
                "Failed to determine store-backed tiling threshold for image %s",
                image.id,
                exc_info=True,
            )
    return tiles


def _store_backed_projection(image):
    """Return the store backed projection.

    Inputs: `image`. Output: `getProjection` result.
    """
    try:
        return image.getProjection()
    except Exception:
        return "normal"


def _store_backed_pixel_sizes(image):
    """Backed pixel sizes.

    Inputs: `image`. Output: `pixel_size`.
    """
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
    return pixel_size


def _store_backed_base_image_data(
    image,
    request,
    node,
    channels,
    tiles,
    pixel_size,
    projection,
):
    """Backed base image data.

    Inputs: `image`, `request`, `node`, `channels`, `tiles`, `pixel_size`, `projection`.
    Output: dict.
    """
    return {
        "id": image.id,
        "meta": _store_backed_metadata(image),
        "perms": {
            "canAnnotate": image.canAnnotate(),
            "canEdit": image.canEdit(),
            "canDelete": image.canDelete(),
            "canLink": image.canLink(),
        },
        "tiles": tiles,
        "interpolate": request.session.get("server_settings", {})
        .get("viewer", {})
        .get(
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


def _apply_store_backed_init_zoom(payload, request, level_count):
    """Apply the store backed init zoom.

    Inputs: `payload` payload, `request` Django request, `level_count`. Output: None.
    """
    viewer_settings = request.session.get("server_settings", {}).get("viewer", {})
    init_zoom = viewer_settings.get("initial_zoom_level", 0)
    if init_zoom is not None:
        if init_zoom < 0:
            init_zoom = level_count + init_zoom
        payload["init_zoom"] = init_zoom


def _apply_store_backed_objective(payload, image):
    """Apply the store backed objective.

    Inputs: `payload` payload, `image`. Output: None.
    """
    try:
        objective_settings = image.getObjectiveSettings()
    except Exception:
        objective_settings = None
    if objective_settings is not None:
        objective = objective_settings.getObjective()
        if objective is not None:
            magnification = objective.getNominalMagnification()
            if magnification is not None:
                payload["nominalMagnification"] = magnification


def _apply_store_backed_tile_metadata(
    payload,
    tiles,
    tile_size,
    level_count,
    level_sizes,
    zoom_scaling,
):
    """Apply the store backed tile metadata.

    Inputs: `payload` payload, `tiles`, `tile_size`, `level_count`, `level_sizes`,
    `zoom_scaling`. Output: None.
    """
    if tiles:
        payload.update(
            {
                "tile_size": tile_size,
                "levels": max(level_count, 1),
                "resolutions": {
                    index: level_sizes[index] for index in range(len(level_sizes))
                },
                "zoomLevelScaling": zoom_scaling,
            }
        )


def _store_backed_image_data(image, request):
    """Backed image data.

    Inputs: `image`, `request`. Output: `payload`.
    """
    node = load_store_backed_image_node(image)
    channels = _decorate_store_backed_channels(image, image.getChannels(noRE=True))
    level_count, level_sizes, tile_size, zoom_scaling = _store_backed_level_metadata(
        image, node
    )
    tiles = _store_backed_tiles_enabled(image, level_count)
    payload = _store_backed_base_image_data(
        image,
        request,
        node,
        channels,
        tiles,
        _store_backed_pixel_sizes(image),
        _store_backed_projection(image),
    )
    _apply_store_backed_init_zoom(payload, request, level_count)
    _apply_store_backed_objective(payload, image)
    _apply_store_backed_tile_metadata(
        payload,
        tiles,
        tile_size,
        level_count,
        level_sizes,
        zoom_scaling,
    )
    return payload


def _store_backed_region_response(image, request, z=None, t=None, conn=None):
    """Backed region response.

    Inputs: `image`, `request` Django request, `z`, `t`, `conn` OMERO gateway
    connection. Output: Django `HttpResponse`.
    """
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
            LOGGER.debug(
                "Malformed tile request for store-backed region", exc_info=True
            )
            return HttpResponseBadRequest("malformed tile argument")
    elif region:
        try:
            x, y, width, height = [int(value) for value in region.split(",")]
        except Exception:
            LOGGER.debug(
                "Malformed region request for store-backed image", exc_info=True
            )
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
    """Patch the urlpatterns.

    Inputs: `urlpatterns`, `replacements`. Output: None.
    """
    for pattern in urlpatterns:
        if isinstance(pattern, URLResolver):
            _patch_urlpatterns(pattern.url_patterns, replacements)
            continue
        if not isinstance(pattern, URLPattern):
            continue
        replacement = replacements.get(pattern.name)
        if replacement is not None:
            pattern.callback = replacement
            pattern.__dict__.pop("lookup_str", None)


def _unwrap_callback(callback, *, depth):
    """Return the unwrap callback.

    Inputs: `callback`, `depth`. Output: `unwrapped`.
    """
    unwrapped = callback
    for _ in range(depth):
        unwrapped = getattr(unwrapped, "__wrapped__", unwrapped)
    return unwrapped


def _store_backed_thumbnail_size(request, w=None, h=None):
    """Backed thumbnail size.

    Inputs: `request` Django request, `w`, `h`. Output: `int` size.
    """
    server_settings = request.session.get("server_settings", {}).get("browser", {})
    default_size = server_settings.get("thumb_default_size", 96)
    if w is None:
        return default_size
    if h is None:
        return int(w)
    return max(int(w), int(h))


def _batch_thumbnail_size(request, w=None):
    """Return the batch thumbnail size.

    Inputs: `request` Django request, `w`. Output: `get` result.
    """
    if w is not None:
        return w
    server_settings = request.session.get("server_settings", {}).get("browser", {})
    return server_settings.get("thumb_default_size", 96)


def _make_get_channels_override(original_get_channels):
    """Create the get channels override.

    Inputs: `original_get_channels`. Output: `get_channels_override`.
    """

    @wraps(original_get_channels)
    def get_channels_override(self, *args, **kwargs):
        """Return channels override.

        Inputs: `*args` positional arguments, `**kwargs` keyword arguments. Output:
        `_decorate_store_backed_channels` result.
        """
        if not is_store_backed_image(self):
            return original_get_channels(self, *args, **kwargs)
        channels = original_get_channels(self, noRE=True)
        return _decorate_store_backed_channels(self, channels)

    return get_channels_override


def _make_render_thumbnail_override(original_render_thumbnail, webgateway_views):
    """Create the render thumbnail override.

    Inputs: `original_render_thumbnail`, `webgateway_views`. Output:
    `render_thumbnail_override`.
    """

    @wraps(original_render_thumbnail)
    def render_thumbnail_override(
        request,
        iid,
        w=None,
        h=None,
        conn=None,
        _defcb=None,
        **kwargs,
    ):
        """Render the thumbnail override.

        Inputs: `request` Django request, `iid`, `w`, `h`, `conn` OMERO gateway
        connection, `_defcb`, `**kwargs` keyword arguments. Output:
        `render_store_backed_thumbnail_bytes` result.
        """
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

        return render_store_backed_thumbnail_bytes(
            image,
            size=_store_backed_thumbnail_size(request, w=w, h=h),
            z=webgateway_views.getIntOrDefault(request, "z", None),
            t=webgateway_views.getIntOrDefault(request, "t", None),
        )

    return render_thumbnail_override


def _store_backed_thumbnail_entries(image_ids, conn, size, z_index, t_index):
    """Backed thumbnail entries.

    Inputs: `image_ids`, `conn`, `size`, `z_index`, `t_index`. Output: tuple.
    """
    response: dict[Any, str | None] = {}
    regular_ids: list[Any] = []
    for image_id in image_ids:
        image = _get_store_backed_image(conn, image_id)
        if image is None:
            regular_ids.append(image_id)
            continue
        try:
            thumbnail = render_store_backed_thumbnail_bytes(
                image,
                size=size,
                z=z_index,
                t=t_index,
            )
            response[image_id] = (
                f"data:image/jpeg;base64,{base64.b64encode(thumbnail).decode('utf-8')}"
            )
        except Exception:
            LOGGER.error(
                "Failed to render store-backed thumbnail for image %s",
                image_id,
            )
            LOGGER.error(traceback.format_exc())
            response[image_id] = None
    return response, regular_ids


def _add_regular_thumbnail_entries(response, conn, regular_ids, size):
    """Add the regular thumbnail entries.

    Inputs: `response` response object, `conn` OMERO gateway connection, `regular_ids`,
    `size`. Output: None.
    """
    if not regular_ids:
        return
    thumbnails = conn.getThumbnailSet([rlong(i) for i in regular_ids], size)
    for image_id in regular_ids:
        response[image_id] = None
        try:
            payload = thumbnails[image_id]
            if payload:
                response[image_id] = (
                    f"data:image/jpeg;base64,"
                    f"{base64.b64encode(payload).decode('utf-8')}"
                )
        except KeyError:
            LOGGER.error("Thumbnail not available. (img id: %d)", image_id)
        except Exception:
            LOGGER.error(traceback.format_exc())


def _make_get_thumbnails_json_override(original_get_thumbnails_json, webgateway_views):
    """Thumbnails JSON override with.

    Inputs: `original_get_thumbnails_json`, `webgateway_views`. Output:
    `get_thumbnails_json_override`.
    """

    @wraps(original_get_thumbnails_json)
    def get_thumbnails_json_override(request, w=None, conn=None, **kwargs):
        """Return thumbnails JSON override.

        Inputs: `request` Django request, `w`, `conn` OMERO gateway connection,
        `**kwargs` keyword arguments. Output: ID value.
        """
        image_ids = list(set(webgateway_views.get_longs(request, "id")))
        if len(image_ids) <= 1:
            return original_get_thumbnails_json(request, w=w, conn=conn, **kwargs)

        size = _batch_thumbnail_size(request, w=w)
        if len(image_ids) > settings.THUMBNAILS_BATCH:
            return HttpJavascriptResponseServerError(
                f"Max {settings.THUMBNAILS_BATCH} thumbnails at a time."
            )

        z_index = webgateway_views.getIntOrDefault(request, "z", None)
        t_index = webgateway_views.getIntOrDefault(request, "t", None)
        response, regular_ids = _store_backed_thumbnail_entries(
            image_ids, conn, size, z_index, t_index
        )
        _add_regular_thumbnail_entries(response, conn, regular_ids, size)
        return response

    return get_thumbnails_json_override


def _make_render_image_override(original_render_image):
    """Create the render image override.

    Inputs: `original_render_image`. Output: `render_image_override`.
    """

    @wraps(original_render_image)
    def render_image_override(request, iid, z=None, t=None, conn=None, **kwargs):
        """Render the image override.

        Inputs: `request` Django request, `iid`, `z`, `t`, `conn` OMERO gateway
        connection, `**kwargs` keyword arguments. Output:
        `_store_backed_render_response` result.
        """
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

    return render_image_override


def _regular_image_region_response(
    original_render_image_region_impl,
    safe_rendering_on,
    request,
    iid,
    z,
    t,
    conn=None,
    **kwargs,
):
    """Return the regular image region response.

    Inputs: `original_render_image_region_impl`, `safe_rendering_on`, `request` Django
    request, `iid`, `z`, `t`, `conn` OMERO gateway connection, `**kwargs` keyword
    arguments. Output: `original_render_image_region_impl` result.
    """
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
        if not safe_rendering_on or not is_known_tile_size_failure(exc):
            raise
        return _render_regular_image_region_with_safe_tile_size(
            request,
            iid,
            z,
            t,
            conn=conn,
        )


def _make_render_image_region_override(
    original_render_image_region,
    original_render_image_region_impl,
    safe_rendering_on,
):
    """Image region override with.

    Inputs: `original_render_image_region`, `original_render_image_region_impl`,
    `safe_rendering_on`. Output: `render_image_region_override`.
    """

    @wraps(original_render_image_region)
    def render_image_region_override(request, iid, z, t, conn=None, **kwargs):
        """Render the image region override.

        Inputs: `request` Django request, `iid`, `z`, `t`, `conn` OMERO gateway
        connection, `**kwargs` keyword arguments. Output:
        `_store_backed_region_response` result.
        """
        image = _get_store_backed_image(conn, iid)
        if image is None:
            return _regular_image_region_response(
                original_render_image_region_impl,
                safe_rendering_on,
                request,
                iid,
                z,
                t,
                conn=conn,
                **kwargs,
            )
        return _store_backed_region_response(
            image,
            request,
            z=z,
            t=t,
            conn=conn,
        )

    return render_image_region_override


def _select_payload_key(payload, key):
    """Select the payload key.

    Inputs: `payload` payload, `key` lookup key. Output: `_select_marshaled_key` result.
    """
    if key is None:
        return payload
    return _select_marshaled_key(payload, key)


def _regular_image_data_json_response(
    original_image_data_json_impl,
    safe_rendering_on,
    image,
    request,
    conn=None,
    _internal=False,
    **kwargs,
):
    """Return the regular image data JSON response.

    Inputs: `original_image_data_json_impl`, `safe_rendering_on`, `image`, `request`
    Django request, `conn` OMERO gateway connection, `_internal`, `**kwargs` keyword
    arguments. Output: `original_image_data_json_impl` result.
    """
    try:
        return original_image_data_json_impl(
            request,
            conn=conn,
            _internal=_internal,
            **kwargs,
        )
    except Exception as exc:
        if not safe_rendering_on or not is_known_tile_size_failure(exc):
            raise
        payload = _marshal_regular_image_data_with_safe_tile_size(
            image,
            request,
        )
        return _select_payload_key(payload, kwargs.get("key"))


def _make_image_data_json_override(
    original_image_data_json,
    original_image_data_json_impl,
    safe_rendering_on,
):
    """Image data JSON override with.

    Inputs: `original_image_data_json`, `original_image_data_json_impl`,
    `safe_rendering_on`. Output: `image_data_json_override`.
    """

    @wraps(original_image_data_json)
    def image_data_json_override(request, conn=None, _internal=False, **kwargs):
        """Return the image data JSON override.

        Inputs: `request` Django request, `conn` OMERO gateway connection, `_internal`,
        `**kwargs` keyword arguments. Output: `_select_payload_key` result.
        """
        image = conn.getObject("Image", kwargs["iid"])
        if image is None:
            return original_image_data_json_impl(
                request,
                conn=conn,
                _internal=_internal,
                **kwargs,
            )
        if not is_store_backed_image(image):
            return _regular_image_data_json_response(
                original_image_data_json_impl,
                safe_rendering_on,
                image,
                request,
                conn=conn,
                _internal=_internal,
                **kwargs,
            )

        payload = _store_backed_image_data(image, request)
        return _select_payload_key(payload, kwargs.get("key"))

    return image_data_json_override


def _make_load_metadata_preview_override(
    original_load_metadata_preview,
    original_load_metadata_preview_impl,
    safe_rendering_on,
):
    """Metadata preview override with.

    Inputs: `original_load_metadata_preview`, `original_load_metadata_preview_impl`,
    `safe_rendering_on`. Output: `load_metadata_preview_override`.
    """

    @wraps(original_load_metadata_preview)
    def load_metadata_preview_override(
        request, c_type, c_id, conn=None, share_id=None, **kwargs
    ):
        """Load the metadata preview override.

        Inputs: `request` Django request, `c_type`, `c_id`, `conn` OMERO gateway
        connection, `share_id`, `**kwargs` keyword arguments. Output:
        `original_load_metadata_preview_impl` result.
        """
        try:
            return original_load_metadata_preview_impl(
                request,
                c_type,
                c_id,
                conn=conn,
                share_id=share_id,
                **kwargs,
            )
        except Exception as exc:
            if not safe_rendering_on or not _is_known_rendering_engine_failure(exc):
                raise
            return _load_metadata_preview_with_safe_rendering(
                request,
                c_type,
                c_id,
                conn=conn,
                share_id=share_id,
                **kwargs,
            )

    return load_metadata_preview_override


def _decorate_webgateway_overrides(
    webgateway_views,
    webclient_views,
    get_thumbnails_json_override,
    image_data_json_override,
    render_image_override,
    render_image_region_override,
    load_metadata_preview_override,
):
    """Return the decorate webgateway overrides.

    Inputs: `webgateway_views`, `webclient_views`, `get_thumbnails_json_override`,
    `image_data_json_override`, `render_image_override`, `render_image_region_override`,
    `load_metadata_preview_override`. Output: `dict`.
    """
    return {
        "get_thumbnails_json": login_required()(
            webgateway_views.jsonp(get_thumbnails_json_override)
        ),
        "image_data_json": login_required()(
            webgateway_views.jsonp(image_data_json_override)
        ),
        "render_image": login_required()(render_image_override),
        "render_image_region": login_required()(render_image_region_override),
        "load_metadata_preview": login_required()(
            webclient_views.render_response()(load_metadata_preview_override)
        ),
    }


def _apply_webgateway_overrides(
    webclient_gateway,
    webgateway_views,
    webclient_views,
    webgateway_urls,
    webclient_urls,
    get_channels_override,
    render_thumbnail_override,
    decorated_overrides,
):
    """Apply the webgateway overrides.

    Inputs: `webclient_gateway`, `webgateway_views`, `webclient_views`,
    `webgateway_urls`, `webclient_urls`, `get_channels_override`,
    `render_thumbnail_override`, `decorated_overrides`. Output: None.
    """
    decorated_get_thumbnails_json = decorated_overrides["get_thumbnails_json"]
    decorated_image_data_json = decorated_overrides["image_data_json"]
    decorated_render_image = decorated_overrides["render_image"]
    decorated_render_image_region = decorated_overrides["render_image_region"]
    decorated_load_metadata_preview = decorated_overrides["load_metadata_preview"]

    setattr(webclient_gateway.ImageWrapper, "getChannels", get_channels_override)
    setattr(webgateway_views, "imageData_json", decorated_image_data_json)
    setattr(webgateway_views, "_render_thumbnail", render_thumbnail_override)
    setattr(webgateway_views, "get_thumbnails_json", decorated_get_thumbnails_json)
    setattr(webgateway_views, "render_image", decorated_render_image)
    setattr(webgateway_views, "render_image_region", decorated_render_image_region)
    setattr(webclient_views, "load_metadata_preview", decorated_load_metadata_preview)

    _patch_urlpatterns(
        webgateway_urls.urlpatterns,
        {
            "webgateway_imageData_json": decorated_image_data_json,
            "webgateway_get_thumbnails_json": decorated_get_thumbnails_json,
            "webgateway_render_image": decorated_render_image,
            "webgateway_render_image_region": decorated_render_image_region,
        },
    )

    _patch_urlpatterns(
        webclient_urls.urlpatterns,
        {
            "web_imageData_json": decorated_image_data_json,
            "get_thumbnails_json": decorated_get_thumbnails_json,
            "web_render_image_download": decorated_render_image,
            "web_render_image_region": decorated_render_image_region,
            "load_metadata_preview": decorated_load_metadata_preview,
        },
    )


def install_webgateway_overrides():
    """Install the webgateway overrides.

    Inputs: no caller arguments. Output: installs the described state and returns None.
    """
    try:
        from omeroweb.webgateway import urls as webgateway_urls
        from omeroweb.webgateway import views as webgateway_views
        from omeroweb.webgateway import marshal as webgateway_marshal
        from omeroweb.webclient import urls as webclient_urls
        from omeroweb.webclient import views as webclient_views
        from omeroweb.webclient import webclient_gateway
    except ImportError:
        return

    if getattr(webgateway_views, "_omero_web_zarr_store_backed_overrides", False):
        return

    _safe_rendering_on = _safe_rendering_enabled()

    if _safe_rendering_on:
        _install_safe_image_marshal_overrides(webgateway_marshal)

    original_get_channels = webclient_gateway.ImageWrapper.getChannels
    original_image_data_json = webgateway_views.imageData_json
    original_render_thumbnail = _require_webgateway_callable(
        webgateway_views, "_render_thumbnail"
    )
    original_get_thumbnails_json = webgateway_views.get_thumbnails_json
    original_render_image = webgateway_views.render_image
    original_render_image_region = webgateway_views.render_image_region
    original_load_metadata_preview = webclient_views.load_metadata_preview
    original_image_data_json_impl = _unwrap_callback(original_image_data_json, depth=2)
    original_render_image_region_impl = _unwrap_callback(
        original_render_image_region, depth=1
    )
    original_load_metadata_preview_impl = _unwrap_callback(
        original_load_metadata_preview, depth=2
    )

    get_channels_override = _make_get_channels_override(original_get_channels)
    render_thumbnail_override = _make_render_thumbnail_override(
        original_render_thumbnail, webgateway_views
    )
    get_thumbnails_json_override = _make_get_thumbnails_json_override(
        original_get_thumbnails_json, webgateway_views
    )
    render_image_override = _make_render_image_override(original_render_image)
    render_image_region_override = _make_render_image_region_override(
        original_render_image_region,
        original_render_image_region_impl,
        _safe_rendering_on,
    )
    image_data_json_override = _make_image_data_json_override(
        original_image_data_json,
        original_image_data_json_impl,
        _safe_rendering_on,
    )
    load_metadata_preview_override = _make_load_metadata_preview_override(
        original_load_metadata_preview,
        original_load_metadata_preview_impl,
        _safe_rendering_on,
    )
    decorated_overrides = _decorate_webgateway_overrides(
        webgateway_views,
        webclient_views,
        get_thumbnails_json_override,
        image_data_json_override,
        render_image_override,
        render_image_region_override,
        load_metadata_preview_override,
    )
    _apply_webgateway_overrides(
        webclient_gateway,
        webgateway_views,
        webclient_views,
        webgateway_urls,
        webclient_urls,
        get_channels_override,
        render_thumbnail_override,
        decorated_overrides,
    )

    setattr(webgateway_views, "_omero_web_zarr_store_backed_overrides", True)
