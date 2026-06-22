import json
import logging
import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np
from django.http import Http404
import zarr

LOGGER = logging.getLogger(__name__)
_MISSING = object()
_STORE_BACKED_NODE_CACHE_SIZE = 64
ZARR_ALLOWED_STORE_ROOTS_ENV = "OMERO_WEB_ZARR_ALLOWED_STORE_ROOTS"
DEFAULT_CHANNEL_COLORS = (
    (255, 255, 255),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (0, 255, 255),
    (255, 0, 255),
)


def marshal_pixel_sizes(image):
    """Return the marshal pixel sizes.

    Inputs: `image`. Output: `pixel_sizes`.
    """
    pixel_sizes = {}
    pix_size_x = image.getPixelSizeX(units=True)
    pix_size_y = image.getPixelSizeY(units=True)
    pix_size_z = image.getPixelSizeZ(units=True)
    if pix_size_x is not None:
        pixel_sizes["x"] = {
            "unit": str(pix_size_x.getUnit()).lower(),
            "value": pix_size_x.getValue(),
        }
    if pix_size_y is not None:
        pixel_sizes["y"] = {
            "unit": str(pix_size_y.getUnit()).lower(),
            "value": pix_size_y.getValue(),
        }
    if pix_size_z is not None:
        pixel_sizes["z"] = {
            "unit": str(pix_size_z.getUnit()).lower(),
            "value": pix_size_z.getValue(),
        }
    return pixel_sizes


def marshal_axes_v3(image):
    """Return the marshal axes v3.

    Inputs: `image`. Output: `axes`.
    """
    dims = ["t", "c", "z", "y", "x"]
    axes: list[Any] = []
    for dim in dims:
        if getattr(image, "getSize" + dim.upper())() > 1:
            axes.append(dim)
    return axes


def marshal_axes(image, version):
    """Return the marshal axes.

    Inputs: `image`, `version`. Output: `axes`. Raises: Http404 when validation or
    external operations fail.
    """
    if version not in ("0.3", "0.4"):
        raise Http404("version not supported")

    if version == "0.3":
        return marshal_axes_v3(image)

    size_c = image.getSizeC()
    size_z = image.getSizeZ()
    size_t = image.getSizeT()
    pixel_sizes = marshal_pixel_sizes(image)

    axes = []
    if size_t > 1:
        axes.append({"name": "t", "type": "time"})
    if size_c > 1:
        axes.append({"name": "c", "type": "channel"})
    if size_z > 1:
        axes.append({"name": "z", "type": "space"})
        if pixel_sizes and "z" in pixel_sizes:
            axes[-1]["unit"] = pixel_sizes["z"]["unit"]
    for dim in ("y", "x"):
        axes.append({"name": dim, "type": "space"})
        if pixel_sizes and dim in pixel_sizes:
            axes[-1]["unit"] = pixel_sizes[dim]["unit"]

    return axes


def generate_coordinate_transformations(shapes):
    """Generate the coordinate transformations.

    Inputs: `shapes`. Output: `transformations`. Raises: ValueError when validation or
    external operations fail.
    """
    data_shape = shapes[0]
    transformations = []
    for shape in shapes:
        if len(shape) != len(data_shape):
            raise ValueError(
                f"Shape dimension mismatch: expected {len(data_shape)}, "
                f"got {len(shape)}"
            )
        scale = [full / level for full, level in zip(data_shape, shape)]
        transformations.append([{"type": "scale", "scale": scale}])

    return transformations


def open_compat_array(path, *, mode, shape, chunks, dtype):
    """Open the compat array.

    Inputs: `path` path, `mode`, `shape`, `chunks`, `dtype`. Output: `open_array`
    """
    kwargs = {
        "mode": mode,
        "shape": shape,
        "chunks": chunks,
        "dtype": dtype,
    }
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "error",
                message=r".*ignoring keyword argument 'zarr_format'.*",
                category=UserWarning,
            )
            return zarr.open_array(path, zarr_format=2, **kwargs)
    except (TypeError, UserWarning) as exc:
        if "zarr_format" not in str(exc):
            raise
        return zarr.open_array(path, **kwargs)


def resolve_image_backing_zarr_store(image):
    """Return resolve image backing Zarr store.

    Inputs: `image`. Output: `resolve_local_zarr_store` result.
    """
    lsid = _resolve_image_external_lsid(image)
    return resolve_local_zarr_store(lsid)


def get_image_connection(image):
    """Return the OMERO gateway connection attached to an ImageWrapper.

    Inputs: `image`. Output: `getattr` result.
    """
    return getattr(image, "_conn", None)


def prepare_image_rendering_engine(image, *, required=True):
    """Prepare the image rendering engine.

    Inputs: `image`, `required`. Output: `prepare` result. Raises: AttributeError when
    validation or the called operation fails.
    """
    prepare = getattr(image, "prepareRenderingEngine", None)
    if not callable(prepare):
        prepare = getattr(image, "_prepareRenderingEngine", None)
    if not callable(prepare):
        if required:
            raise AttributeError("OMERO image rendering engine preparer is unavailable")
        return False
    return prepare()


def get_image_rendering_engine(image, *, initialize=False):
    """Return the OMERO rendering engine attached to an ImageWrapper, if present.

    Inputs: `image`, `initialize`. Output: `rendering_engine`.
    """
    if initialize:
        zoom_level_scaling = getattr(image, "getZoomLevelScaling", None)
        if callable(zoom_level_scaling):
            zoom_level_scaling()
    rendering_engine = getattr(image, "_re", None)
    if rendering_engine is None and initialize:
        prepare_image_rendering_engine(image, required=False)
        rendering_engine = getattr(image, "_re", None)
    return rendering_engine


def require_image_rendering_engine(image, *, initialize=False):
    """Return the ImageWrapper rendering engine or fail with a clear adapter error.

    Inputs: `image`, `initialize`. Output: `rendering_engine`. Raises: AttributeError
    when validation or the called operation fails.
    """
    rendering_engine = get_image_rendering_engine(image, initialize=initialize)
    if rendering_engine is None:
        raise AttributeError("OMERO image rendering engine is unavailable")
    return rendering_engine


def _resolve_image_external_lsid(image):
    """Resolve the image external lsid.

    Inputs: `image`. Output: `getattr` result.
    """
    details = image.getDetails()
    external_info = getattr(details, "externalInfo", None)
    lsid = getattr(getattr(external_info, "lsid", None), "val", None)
    if lsid:
        return lsid

    conn = get_image_connection(image)
    if conn is None:
        return None

    image_id = getattr(image, "id", None)
    if image_id is None and hasattr(image, "getId"):
        image_id = image.getId()
    if image_id is None:
        return None

    try:
        import omero

        params = omero.sys.ParametersI().addId(int(image_id))
        rows = conn.getQueryService().projection(
            "select i.details.externalInfo.lsid from Image i where i.id = :id",
            params,
            conn.SERVICE_OPTS,
        )
    except Exception:
        LOGGER.debug(
            "Failed to resolve externalInfo.lsid for image %s via query service",
            image_id,
            exc_info=True,
        )
        return None

    if not rows or not rows[0] or rows[0][0] is None:
        return None
    return getattr(rows[0][0], "val", None)


def resolve_local_zarr_store(location):
    """Return resolve local Zarr store.

    Inputs: `location`. Output: `resolved` or None.
    """
    if not location:
        return None

    location_text = str(location)
    if Path(location_text).is_absolute():
        candidate_text = location_text
    else:
        parsed = urlparse(location_text)
        if parsed.scheme not in ("", "file"):
            return None
        candidate_text = unquote(parsed.path if parsed.scheme == "file" else location_text)
    if not candidate_text:
        return None

    candidate = Path(candidate_text)
    if not candidate.is_absolute():
        return None

    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None

    if not resolved.is_dir():
        return None

    if not is_local_zarr_store(resolved):
        return None

    if not _is_allowed_local_zarr_store(resolved):
        LOGGER.warning("Rejecting Zarr store outside configured roots: %s", resolved)
        return None

    return resolved


def _configured_allowed_zarr_roots():
    """Return configured local roots that may back OMERO.web Zarr responses.

    Inputs: environment. Output: resolved existing directory list.
    """
    configured = os.environ.get(ZARR_ALLOWED_STORE_ROOTS_ENV)
    if configured:
        candidates = [part.strip() for part in configured.split(os.pathsep)]
    else:
        candidates = []
        managed_dir = os.environ.get("CONFIG_omero_managed_dir")
        if managed_dir:
            candidates.append(managed_dir)
        else:
            data_dir = os.environ.get("OMERO_DATA_DIR")
            if data_dir:
                candidates.append(str(Path(data_dir) / "ManagedRepository"))
            tmp_root = os.environ.get("OMERO_TMP_PATH")
            if not candidates and tmp_root:
                candidates.append(tmp_root)

    roots = []
    for candidate_text in candidates:
        if not candidate_text:
            continue
        try:
            candidate = Path(candidate_text).resolve(strict=True)
        except OSError:
            LOGGER.debug(
                "Skipping unavailable Zarr allowed root %s",
                candidate_text,
                exc_info=True,
            )
            continue
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _is_allowed_local_zarr_store(path):
    """Return whether `path` is below a configured allowed local store root.

    Inputs: `path`. Output: bool.
    """
    roots = _configured_allowed_zarr_roots()
    if not roots:
        return False
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_local_zarr_file(store_root, *parts):
    """Resolve the local Zarr file.

    Inputs: `store_root`, `*parts`. Output: `target`. Raises: Http404 when validation or
    external operations fail.
    """
    relative_path = Path(*parts)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise Http404("zarr path not found")

    try:
        target = (store_root / relative_path).resolve(strict=True)
    except OSError as exc:
        raise Http404("zarr path not found") from exc

    try:
        target.relative_to(store_root)
    except ValueError as exc:
        raise Http404("zarr path not found") from exc

    if not target.is_file():
        raise Http404("zarr path not found")

    return target


def is_store_metadata_path(path):
    """Return whether store metadata path.

    Inputs: `path`. Output: bool.
    """
    return path.name in {".zattrs", ".zgroup", ".zarray", "zarr.json"}


def is_local_zarr_store(path):
    """Return whether local Zarr store.

    Inputs: `path`. Output: bool.
    """
    return (path / "zarr.json").is_file() or (path / ".zgroup").is_file()


def _resolve_store_root(store_root):
    """Resolve the store root.

    Inputs: `store_root`. Output: `resolved`. Raises: FileNotFoundError when validation or the
    called operation fails.
    """
    try:
        resolved = Path(store_root).resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise FileNotFoundError("zarr store root not found") from exc
    if not resolved.is_dir() or not is_local_zarr_store(resolved):
        raise FileNotFoundError("zarr store root not found")
    return resolved


def _resolve_store_metadata_file(store_root, *parts):
    """Resolve the store metadata file.

    Inputs: `store_root`, `*parts`. Output: `target`. Raises: FileNotFoundError when validation
    or the called operation fails.
    """
    root = _resolve_store_root(store_root)
    relative_path = Path(*parts)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise FileNotFoundError("zarr metadata path not found")
    try:
        target = (root / relative_path).resolve(strict=True)
        target.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError("zarr metadata path not found") from exc
    if not target.is_file() or not is_store_metadata_path(target):
        raise FileNotFoundError("zarr metadata path not found")
    return target


def is_store_backed_image(image):
    """Return whether store backed image.

    Inputs: `image`. Output: bool.
    """
    return resolve_image_backing_zarr_store(image) is not None


def sanitize_download_basename(name, default="ome-zarr"):
    """Sanitize the download basename.

    Inputs: `name` name, `default`. Output: `replace` result.
    """
    candidate = Path((name or "").strip()).name
    if not candidate:
        candidate = default
    return candidate.replace(",", ".").replace(" ", "_")


def collect_store_metadata_documents(image):
    """Collect the store metadata documents.

    Inputs: `image`. Output: `documents`.
    """
    store_root = resolve_image_backing_zarr_store(image)
    if store_root is None:
        return None

    documents = {}
    for path in sorted(store_root.rglob("*")):
        if not path.is_file() or not is_store_metadata_path(path):
            continue
        relative_path = path.relative_to(store_root)
        metadata_path = _resolve_store_metadata_file(store_root, relative_path)
        with metadata_path.open("r", encoding="utf-8") as handle:
            documents[str(relative_path)] = json.load(handle)

    return documents


def _read_store_root_attrs(store_root):
    """Read the store root attrs.

    Inputs: `store_root`. Output: `load` result.
    """
    zattrs_path = _resolve_store_metadata_file(store_root, ".zattrs")
    with zattrs_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_store_json(store_root, *parts):
    """Read the store JSON.

    Inputs: `store_root`, `*parts`. Output: `load` result.
    """
    target = _resolve_store_metadata_file(store_root, *parts)
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_store_attrs(store_root):
    """Read the store attrs.

    Inputs: `store_root`. Output: `dict`.
    """
    zattrs_path = store_root / ".zattrs"
    if zattrs_path.is_file():
        return _read_store_json(store_root, ".zattrs")

    zarr_json_path = store_root / "zarr.json"
    if zarr_json_path.is_file():
        payload = _read_store_json(store_root, "zarr.json")
        attributes = payload.get("attributes")
        if isinstance(attributes, dict):
            return attributes
    return {}


def _store_relative_metadata_path(store_root, dataset_path):
    """Relative metadata path.

    Inputs: `store_root`, `dataset_path`. Output: `Path` or path text.
    """
    dataset_root = (
        store_root if dataset_path in ("", ".") else store_root / dataset_path
    )
    if (dataset_root / ".zarray").is_file():
        return (
            str(Path(dataset_path) / ".zarray")
            if dataset_path not in ("", ".")
            else ".zarray"
        )
    if (dataset_root / "zarr.json").is_file():
        return (
            str(Path(dataset_path) / "zarr.json")
            if dataset_path not in ("", ".")
            else "zarr.json"
        )
    return None


def _store_node_signature(store_root):
    """Return the store node signature.

    Inputs: `store_root`. Output: `tuple`.
    """
    attrs = _read_store_attrs(store_root)
    multiscales = attrs.get("multiscales") or []
    documents = []
    for candidate in (
        store_root / ".zattrs",
        store_root / "zarr.json",
        store_root / ".zgroup",
    ):
        if candidate.is_file():
            documents.append(candidate)
            break

    if multiscales:
        datasets = multiscales[0].get("datasets") or []
        for dataset in datasets:
            dataset_path = str(dataset.get("path") or "").strip("/")
            relative_metadata_path = _store_relative_metadata_path(
                store_root, dataset_path
            )
            if not relative_metadata_path:
                continue
            documents.append(store_root / relative_metadata_path)

    signature = []
    for document in documents:
        stat = document.stat()
        signature.append(
            (str(document.relative_to(store_root)), stat.st_mtime_ns, stat.st_size)
        )
    return tuple(signature)


class _StoreBackedNode:
    """Helper type for store backed node behavior."""

    __slots__ = ("data", "metadata")

    def __init__(self, data, metadata):
        """Create `_StoreBackedNode` with `data` and `metadata`.

        Inputs: `data`, `metadata`. Output: None.
        """
        self.data = data
        self.metadata = metadata


def _channel_limits_from_omero_channel(channel):
    """Return the channel limits from OMERO channel.

    Inputs: `channel`. Output: `tuple`.
    """
    window = channel.get("window") or {}
    start = window.get("start")
    end = window.get("end")
    if start is None or end is None:
        return None
    try:
        return (float(start), float(end))
    except (TypeError, ValueError):
        return None


def _build_store_backed_metadata(attrs):
    """Build the store backed metadata.

    Inputs: `attrs`. Output: `dict`.
    """
    multiscales = attrs.get("multiscales") or []
    axes: list[Any] = []
    if multiscales:
        axes = multiscales[0].get("axes") or []

    omero_metadata = attrs.get("omero") or {}
    channels = omero_metadata.get("channels") or []
    channel_names = []
    visible = []
    contrast_limits = []
    colormap = []
    for channel in channels:
        label = channel.get("label")
        channel_names.append(None if label is None else str(label))
        visible.append(bool(channel.get("active", True)))
        contrast_limits.append(_channel_limits_from_omero_channel(channel))
        colormap.append(channel.get("color"))

    return {
        "axes": axes,
        "multiscales": multiscales,
        "channel_names": channel_names,
        "visible": visible,
        "contrast_limits": contrast_limits,
        "colormap": colormap,
    }


def _load_store_backed_image_node_from_metadata(store_root):
    """Load the store backed image node from metadata.

    Inputs: `store_root`. Output: `_StoreBackedNode` result.
    """
    attrs = _read_store_attrs(store_root)
    multiscales = attrs.get("multiscales") or []
    if not multiscales:
        return None

    datasets = multiscales[0].get("datasets") or []
    if not datasets:
        return None

    arrays = []
    for dataset in datasets:
        dataset_path = str(dataset.get("path") or "").strip("/")
        array_root = (
            store_root if dataset_path in ("", ".") else store_root / dataset_path
        )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Found an empty list of filters in the array metadata document\..*",
                category=UserWarning,
            )
            arrays.append(zarr.open_array(array_root, mode="r"))

    return _StoreBackedNode(tuple(arrays), _build_store_backed_metadata(attrs))


def _resolve_ome_zarr_format(store_root):
    """Resolve the OME Zarr format.

    Inputs: `store_root`. Output: `CurrentFormat` result.
    """
    version = ""
    try:
        attrs = _read_store_attrs(store_root)
        multiscales = attrs.get("multiscales") or []
        if multiscales:
            version = str(multiscales[0].get("version") or "")
    except OSError:
        LOGGER.debug("Failed to inspect root .zattrs for %s", store_root, exc_info=True)

    from ome_zarr.format import CurrentFormat, FormatV04

    if version.startswith("0.4"):
        return FormatV04()
    return CurrentFormat()


def _load_store_backed_image_node_with_reader(store_root):
    """Load the store backed image node with reader.

    Inputs: `store_root`. Output: `node`.
    """
    from ome_zarr.io import parse_url
    from ome_zarr.reader import Reader

    fmt = _resolve_ome_zarr_format(store_root)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Found an empty list of filters in the array metadata document\..*",
            category=UserWarning,
        )
        location = parse_url(store_root, fmt=fmt)
        if location is None:
            return None
        for node in Reader(location)():
            if getattr(node, "data", None):
                return node
    return None


@lru_cache(maxsize=_STORE_BACKED_NODE_CACHE_SIZE)
def _load_store_backed_image_node_cached(store_root_text, _signature):
    """Load the store backed image node cached.

    Inputs: `store_root_text`, `_signature`. Output:
    `_load_store_backed_image_node_with_reader` result.
    """
    store_root = Path(store_root_text)
    try:
        node = _load_store_backed_image_node_from_metadata(store_root)
    except Exception:
        LOGGER.debug(
            "Direct metadata load failed for store-backed image node %s",
            store_root,
            exc_info=True,
        )
    else:
        if node is not None:
            return node
    return _load_store_backed_image_node_with_reader(store_root)


def load_store_backed_image_node(image):
    """Return load store backed image node.

    Inputs: `image`. Output: `cached`.
    """
    cached = getattr(image, "_omero_web_zarr_node", _MISSING)
    if cached is not _MISSING:
        return cached

    try:
        store_root = resolve_image_backing_zarr_store(image)
    except OSError:
        LOGGER.debug(
            "Failed to resolve store-backed image root for %s",
            getattr(image, "id", None),
            exc_info=True,
        )
        setattr(image, "_omero_web_zarr_node", None)
        return None
    if store_root is None:
        setattr(image, "_omero_web_zarr_node", None)
        return None

    try:
        signature = _store_node_signature(store_root)
        node = _load_store_backed_image_node_cached(str(store_root), signature)
        setattr(image, "_omero_web_zarr_node", node)
        return node
    except OSError:
        LOGGER.debug(
            "Failed to load store-backed image node for %s", store_root, exc_info=True
        )
    setattr(image, "_omero_web_zarr_node", None)
    return None


def _cached_channel_overrides(image, channels):
    """Return the cached channel overrides.

    Inputs: `image`, `channels`. Output: `_MISSING`.
    """
    cached = getattr(image, "_omero_web_zarr_channel_overrides", _MISSING)
    if (
        cached is not _MISSING
        and isinstance(cached, list)
        and (channels is None or len(cached) == len(channels))
    ):
        return cached
    return _MISSING


def _channel_override_metadata(node):
    """Return the channel override metadata.

    Inputs: `node`. Output: `tuple`.
    """
    metadata = (getattr(node, "metadata", {}) or {}) if node is not None else {}
    return (
        metadata.get("channel_names") or [],
        metadata.get("visible") or [],
        metadata.get("contrast_limits") or [],
        metadata.get("colormap") or [],
    )


def _store_backed_channel_count(image, channels, sequences):
    """Backed channel count.

    Inputs: `image`, `channels`, `sequences`. Output: `channel_count`.
    """
    channel_count = 1
    if channels is not None:
        channel_count = max(channel_count, len(channels))
    try:
        channel_count = max(channel_count, int(image.getSizeC()))
    except Exception:
        LOGGER.debug("Suppressed exception reading channel count", exc_info=True)
    for sequence in sequences:
        if isinstance(sequence, (list, tuple)):
            channel_count = max(channel_count, len(sequence))
    return channel_count


def _sequence_value(sequence, index, default=None):
    """Return the sequence value.

    Inputs: `sequence`, `index`, `default`. Output: `default`.
    """
    try:
        if index < len(sequence):
            return sequence[index]
    except TypeError:
        return default
    return default


def _channel_label(channel_names, index):
    """Return the channel label.

    Inputs: `channel_names`, `index`. Output: `str`.
    """
    label = _sequence_value(channel_names, index)
    if label is not None and str(label).strip():
        return str(label)
    return None


def _metadata_window(contrast_limits, index):
    """Return the metadata window.

    Inputs: `contrast_limits`, `index`. Output: `tuple`.
    """
    limits = _sequence_value(contrast_limits, index)
    if isinstance(limits, (list, tuple)) and len(limits) >= 2:
        return (float(limits[0]), float(limits[1]))
    return None


def _omero_channel_window(channels, index):
    """Return the OMERO channel window.

    Inputs: `channels`, `index`. Output: `tuple`.
    """
    if channels is None or index >= len(channels):
        return None
    channel = channels[index]
    window_start = channel.getWindowStart()
    if window_start is None:
        window_start = channel.getWindowMin()
    window_end = channel.getWindowEnd()
    if window_end is None:
        window_end = channel.getWindowMax()
    if window_start is not None and window_end is not None:
        return (float(window_start), float(window_end))
    return None


def _channel_override(
    index, channel_names, visible, contrast_limits, colormap, channels
):
    """Return the channel override.

    Inputs: `index`, `channel_names`, `visible`, `contrast_limits`, `colormap`,
    `channels`. Output: `override`.
    """
    override = {
        "active": bool(_sequence_value(visible, index))
        if index < len(visible)
        else True,
        "color": _channel_color(_sequence_value(colormap, index), index),
        "inverted": False,
    }
    label = _channel_label(channel_names, index)
    if label is not None:
        override["label"] = label

    window = _metadata_window(contrast_limits, index)
    if window is None:
        window = _omero_channel_window(channels, index)
    if window is not None:
        override["window"] = window
    return override


def get_store_backed_channel_overrides(image, channels=None):
    """Return store backed channel overrides.

    Inputs: `image`, `channels`. Output: `overrides`.
    """
    cached = _cached_channel_overrides(image, channels)
    if cached is not _MISSING:
        return cached

    node = load_store_backed_image_node(image)
    channel_names, visible, contrast_limits, colormap = _channel_override_metadata(node)
    channel_count = _store_backed_channel_count(
        image, channels, (channel_names, visible, contrast_limits, colormap)
    )
    overrides = [
        _channel_override(
            index,
            channel_names,
            visible,
            contrast_limits,
            colormap,
            channels,
        )
        for index in range(channel_count)
    ]

    setattr(image, "_omero_web_zarr_channel_overrides", overrides)
    return overrides


def _normalize_axis_name(axis):
    """Normalize the axis name.

    Inputs: `axis`. Output: `lower` result.
    """
    if isinstance(axis, dict):
        return str(axis.get("name") or "").lower()
    return str(axis).lower()


def get_store_backed_axis_names(node, level=0):
    """Return store backed axis names.

    Inputs: `node`, `level`. Output: name string.
    """
    metadata = getattr(node, "metadata", {}) or {}
    axes = metadata.get("axes") or []
    names = [_normalize_axis_name(axis) for axis in axes if _normalize_axis_name(axis)]
    ndim = len(node.data[level].shape)
    if len(names) == ndim:
        return names
    return list("tczyx")[-ndim:]


def _yx_shape(shape, axis_names):
    """Return the yx shape.

    Inputs: `shape`, `axis_names`. Output: `tuple`.
    """
    shape_by_axis = dict(zip(axis_names, shape))
    return int(shape_by_axis.get("y", 1)), int(shape_by_axis.get("x", 1))


def get_store_backed_level_count(node):
    """Return store backed level count.

    Inputs: `node`. Output: `max` result.
    """
    data = getattr(node, "data", None) or ()
    return max(1, len(data))


def get_store_backed_datasets(node):
    """Return store backed datasets.

    Inputs: `node`. Output: get store backed datasets result.
    """
    metadata = getattr(node, "metadata", {}) or {}
    multiscales = metadata.get("multiscales") or []
    datasets: list[Any] = []
    if multiscales:
        datasets = multiscales[0].get("datasets") or []
    if len(datasets) == len(getattr(node, "data", None) or ()):
        return list(datasets)
    return [{"path": str(index)} for index in range(get_store_backed_level_count(node))]


def get_store_backed_level_sizes(node):
    """Return store backed level sizes.

    Inputs: `node`. Output: bool.
    """
    axis_names = get_store_backed_axis_names(node)
    sizes = []
    for array in getattr(node, "data", None) or ():
        y_size, x_size = _yx_shape(array.shape, axis_names)
        sizes.append({"sizeX": x_size, "sizeY": y_size})
    return sizes or [{"sizeX": 1, "sizeY": 1}]


def _chunk_shape(array):
    """Return the chunk shape.

    Inputs: `array`. Output: `tuple`.
    """
    chunks = getattr(array, "chunks", None)
    if chunks is None:
        return None

    chunk_shape = []
    for axis_chunks in chunks:
        if isinstance(axis_chunks, (list, tuple)):
            if not axis_chunks:
                return None
            chunk_shape.append(int(axis_chunks[0]))
        else:
            chunk_shape.append(int(axis_chunks))
    return tuple(chunk_shape)


def get_store_backed_tile_size(node, default=256, max_length=1024):
    """Return store backed tile size.

    Inputs: `node`, `default`, `max_length`. Output: dict.
    """
    data = getattr(node, "data", None) or ()
    if not data:
        return {"width": int(default), "height": int(default)}

    axis_names = get_store_backed_axis_names(node, level=0)
    chunk_shape = _chunk_shape(data[0])
    chunk_by_axis = {}
    if chunk_shape is not None and len(chunk_shape) == len(axis_names):
        chunk_by_axis = dict(zip(axis_names, chunk_shape))

    shape_by_axis = dict(zip(axis_names, data[0].shape))
    width = int(chunk_by_axis.get("x", min(default, shape_by_axis.get("x", default))))
    height = int(chunk_by_axis.get("y", min(default, shape_by_axis.get("y", default))))
    width = max(1, min(width, int(max_length)))
    height = max(1, min(height, int(max_length)))
    return {"width": width, "height": height}


def select_store_backed_viewer_level(node, viewer_level):
    """Select the store backed viewer level.

    Inputs: `node`, `viewer_level`. Output: select store backed viewer level result.
    """
    level_count = get_store_backed_level_count(node)
    if level_count <= 1:
        return 0
    viewer_index = _clamp_index(viewer_level, level_count)
    return (level_count - 1) - viewer_index


def get_store_backed_zoom_level_scaling(node):
    """Return store backed zoom level scaling.

    Inputs: `node`. Output: get store backed zoom level scaling result.
    """
    level_sizes = get_store_backed_level_sizes(node)
    base_width = max(1, int(level_sizes[0]["sizeX"]))
    return {
        index: level["sizeX"] / base_width for index, level in enumerate(level_sizes)
    }


def select_store_backed_level(node, max_width=None, max_height=None):
    """Select the store backed level.

    Inputs: `node`, `max_width`, `max_height`. Output: `selected`.
    """
    if not getattr(node, "data", None):
        return 0
    if max_width is None and max_height is None:
        return 0

    target_longest = max(int(max_width or 0), int(max_height or 0), 1)
    axis_names = get_store_backed_axis_names(node)
    selected = len(node.data) - 1
    for index, array in enumerate(node.data):
        y_size, x_size = _yx_shape(array.shape, axis_names)
        selected = index
        if max(y_size, x_size) <= target_longest:
            return index
    return selected


def _clamp_index(index, size):
    """Return the clamp index.

    Inputs: `index`, `size`. Output: bounded minimum value.
    """
    if size <= 0:
        return 0
    return min(max(int(index), 0), size - 1)


def _map_multiscale_index(full_resolution_index, full_resolution_size, level_size):
    """Map multiscale index with.

    Inputs: `full_resolution_index`, `full_resolution_size`, `level_size`. Output:
    bounded minimum value.
    """
    if full_resolution_size <= 1 or level_size <= 1:
        return 0
    return min(
        level_size - 1,
        (int(full_resolution_index) * level_size) // full_resolution_size,
    )


def _select_axis_index(axis_name, requested, full_size, level_size):
    """Select the axis index.

    Inputs: `axis_name`, `requested`, `full_size`, `level_size`. Output: `int`.
    """
    if axis_name == "z":
        full_index = _clamp_index(
            full_size // 2 if requested is None else requested,
            full_size,
        )
        return _map_multiscale_index(full_index, full_size, level_size)
    if axis_name == "t":
        return _clamp_index(0 if requested is None else requested, level_size)
    return 0


def read_store_backed_plane(node, *, level=0, z=None, t=None):
    """Read the store backed plane.

    Inputs: `node`, `level`, `z`, `t`. Output: `tuple`. Raises: ValueError when validation or
    the called operation fails.
    """
    if not getattr(node, "data", None):
        raise ValueError("store-backed node has no image data")

    array = node.data[level]
    axis_names = get_store_backed_axis_names(node, level=level)
    full_shape_by_axis = dict(zip(axis_names, node.data[0].shape))
    level_shape_by_axis = dict(zip(axis_names, array.shape))

    selectors = []
    remaining_axes = []
    for axis_name in axis_names:
        if axis_name in {"y", "x"}:
            selectors.append(slice(None))
            remaining_axes.append(axis_name)
        elif axis_name == "c":
            selectors.append(slice(None))
            remaining_axes.append(axis_name)
        else:
            selectors.append(
                _select_axis_index(
                    axis_name,
                    z if axis_name == "z" else t,
                    full_shape_by_axis.get(axis_name, 1),
                    level_shape_by_axis.get(axis_name, 1),
                )
            )

    plane = np.asarray(array[tuple(selectors)])
    if "c" in remaining_axes and plane.ndim >= 3:
        channel_axis = remaining_axes.index("c")
        if channel_axis != 0:
            plane = np.moveaxis(plane, channel_axis, 0)
            remaining_axes = ["c"] + [axis for axis in remaining_axes if axis != "c"]
    return plane, remaining_axes


def _channel_color(entry, index):
    """Return the channel color.

    Inputs: `entry`, `index`. Output: channel color result.
    """
    if isinstance(entry, str):
        candidate = entry.strip().lstrip("#")
        if len(candidate) >= 6:
            try:
                return (
                    int(candidate[0:2], 16),
                    int(candidate[2:4], 16),
                    int(candidate[4:6], 16),
                )
            except ValueError:
                LOGGER.debug("Invalid channel color string %r", entry, exc_info=True)
    if isinstance(entry, list) and entry:
        endpoint = entry[-1]
        if isinstance(endpoint, (list, tuple)) and len(endpoint) >= 3:
            color = []
            for value in endpoint[:3]:
                component = float(value)
                if component <= 1.0:
                    component *= 255.0
                color.append(_clamp_index(round(component), 256))
            return tuple(color)
    return DEFAULT_CHANNEL_COLORS[index % len(DEFAULT_CHANNEL_COLORS)]


def _channel_limits(entry, data):
    """Return the channel limits.

    Inputs: `entry`, `data` payload. Output: `tuple`.
    """
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        low = float(entry[0])
        high = float(entry[1])
    else:
        low = float(np.nanmin(data))
        high = float(np.nanmax(data))
    return low, high


def _normalize_to_uint8(data, limits=None):
    """Normalize the to uint8.

    Inputs: `data` payload, `limits`. Output: `astype` result.
    """
    plane = np.asarray(data, dtype=np.float32)
    low, high = _channel_limits(limits, plane)
    if not np.isfinite(low) or not np.isfinite(high):
        return np.zeros(plane.shape, dtype=np.uint8)
    if high <= low:
        fill_value = 255 if high > 0 else 0
        return np.full(plane.shape, fill_value, dtype=np.uint8)
    clipped = np.clip(plane, low, high)
    scaled = (clipped - low) / (high - low)
    return np.round(scaled * 255.0).astype(np.uint8)


def render_store_backed_plane(node, *, level=0, z=None, t=None):
    """Render the store backed plane.

    Inputs: `node`, `level`, `z`, `t`. Output: `astype` result.
    """
    plane, remaining_axes = read_store_backed_plane(node, level=level, z=z, t=t)
    metadata = getattr(node, "metadata", {}) or {}

    if plane.ndim == 2 or "c" not in remaining_axes:
        return _normalize_to_uint8(plane)

    if plane.shape[0] == 1:
        single_color = _channel_color((metadata.get("colormap") or [None])[0], 0)
        single_plane = _normalize_to_uint8(
            plane[0],
            (metadata.get("contrast_limits") or [None])[0],
        )
        if single_color == (255, 255, 255):
            return single_plane
        rgb = np.zeros(single_plane.shape + (3,), dtype=np.uint8)
        for idx, component in enumerate(single_color):
            rgb[..., idx] = np.round(
                single_plane.astype(np.float32) * (component / 255.0)
            ).astype(np.uint8)
        return rgb

    visible = metadata.get("visible") or []
    limits = metadata.get("contrast_limits") or []
    colormap = metadata.get("colormap") or []

    composite = np.zeros(plane.shape[1:] + (3,), dtype=np.float32)
    any_visible = False
    for index in range(plane.shape[0]):
        is_visible = visible[index] if index < len(visible) else True
        if not is_visible:
            continue
        any_visible = True
        normalized = (
            _normalize_to_uint8(
                plane[index],
                limits[index] if index < len(limits) else None,
            ).astype(np.float32)
            / 255.0
        )
        color = (
            np.asarray(
                _channel_color(
                    colormap[index] if index < len(colormap) else None, index
                ),
                dtype=np.float32,
            )
            / 255.0
        )
        composite += normalized[..., None] * color

    if not any_visible:
        return _normalize_to_uint8(plane[0], limits[0] if limits else None)

    return np.clip(np.round(composite * 255.0), 0, 255).astype(np.uint8)


def render_store_backed_pil_image(
    image,
    *,
    max_width=None,
    max_height=None,
    z=None,
    t=None,
    level=None,
):
    """Render the store backed pil image.

    Inputs: `image`, `max_width`, `max_height`, `z`, `t`, `level`. Output: `pil_image`.
    Raises: Http404 when validation or the called operation fails.
    """
    node = load_store_backed_image_node(image)
    if node is None:
        raise Http404("store-backed image data not found")

    if level is None:
        level = select_store_backed_level(
            node, max_width=max_width, max_height=max_height
        )
    rendered = render_store_backed_plane(node, level=level, z=z, t=t)

    from PIL import Image

    if rendered.ndim == 2:
        pil_image = Image.fromarray(rendered, mode="L")
    else:
        pil_image = Image.fromarray(rendered, mode="RGB")

    if max_width is not None or max_height is not None:
        target_width = int(max_width or pil_image.width)
        target_height = int(max_height or pil_image.height)
        pil_image.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
    return pil_image


def render_store_backed_region_pil_image(
    image,
    *,
    x,
    y,
    width,
    height,
    z=None,
    t=None,
    level=0,
):
    """Render the store backed region pil image.

    Inputs: `image`, `x`, `y`, `width`, `height`, `z`, `t`, `level`. Output: `fromarray`
    Raises: Http404 when validation or the called operation fails.
    """
    node = load_store_backed_image_node(image)
    if node is None:
        raise Http404("store-backed image data not found")

    rendered = render_store_backed_plane(node, level=level, z=z, t=t)
    plane_height, plane_width = rendered.shape[:2]
    x = _clamp_index(x, plane_width)
    y = _clamp_index(y, plane_height)
    width = max(1, min(int(width), plane_width - x))
    height = max(1, min(int(height), plane_height - y))

    if rendered.ndim == 2:
        cropped = rendered[y : y + height, x : x + width]
    else:
        cropped = rendered[y : y + height, x : x + width, :]

    from PIL import Image

    if cropped.ndim == 2:
        return Image.fromarray(cropped, mode="L")
    return Image.fromarray(cropped, mode="RGB")


def encode_store_backed_pil_image(pil_image, image_format):
    """Encode the store backed pil image.

    Inputs: `pil_image`, `image_format`. Output: `tuple`. Raises: Http404 when validation or the
    called operation fails.
    """
    from io import BytesIO

    requested = (image_format or "jpeg").lower()
    if requested in {"jpg", "jpeg"}:
        output_format = "JPEG"
        suffix = "jpeg"
        content_type = "image/jpeg"
        if pil_image.mode not in {"L", "RGB"}:
            pil_image = pil_image.convert("RGB")
    elif requested == "png":
        output_format = "PNG"
        suffix = "png"
        content_type = "image/png"
    elif requested in {"tif", "tiff"}:
        output_format = "TIFF"
        suffix = "tif"
        content_type = "image/tiff"
    else:
        raise Http404("unsupported image format")

    buffer = BytesIO()
    save_kwargs = {}
    if output_format == "JPEG":
        save_kwargs["quality"] = 90
    pil_image.save(buffer, output_format, **save_kwargs)
    return buffer.getvalue(), content_type, suffix


def render_store_backed_thumbnail_bytes(image, *, size=96, z=None, t=None):
    """Render the store backed thumbnail bytes.

    Inputs: `image`, `size`, `z`, `t`. Output: `bytes` or byte count.
    """
    pil_image = render_store_backed_pil_image(
        image,
        max_width=size,
        max_height=size,
        z=z,
        t=t,
    )
    data, _, _ = encode_store_backed_pil_image(pil_image, "jpeg")
    return data


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


def is_known_tile_size_failure(exc):
    """Return whether known tile size failure.

    Inputs: `exc`. Output: bool.
    """
    text = _exception_text(exc)
    return "ZarrReader" in text and (
        "getOptimalTileWidth" in text or "getTileSize" in text
    )


def _configured_max_tile_length(conn, default=1024):
    """Return the configured max tile length.

    Inputs: `conn` OMERO gateway connection, `default`. Output: `int`.
    """
    if conn is None:
        return int(default)
    try:
        value = conn.getConfigService().getConfigValue(
            "omero.pixeldata.max_tile_length"
        )
        return max(1, int(value))
    except Exception:
        LOGGER.debug(
            "Failed to resolve max tile length from OMERO config", exc_info=True
        )
        return int(default)


def _fallback_tile_size(image, conn=None):
    """Return the fallback tile size.

    Inputs: `image`, `conn` OMERO gateway connection. Output: `tuple`.
    """
    max_tile_length = _configured_max_tile_length(conn or get_image_connection(image))
    return (
        max(1, min(int(image.getSizeX()), max_tile_length)),
        max(1, min(int(image.getSizeY()), max_tile_length)),
    )


def get_safe_image_tile_size(image, conn=None):
    """Return safe image tile size.

    Inputs: `image`, `conn` OMERO gateway connection. Output: `_fallback_tile_size`
    """
    rendering_engine = get_image_rendering_engine(image)
    if rendering_engine is None:
        prepare_image_rendering_engine(image, required=False)
        rendering_engine = get_image_rendering_engine(image)
    if rendering_engine is None:
        return _fallback_tile_size(image, conn=conn)

    try:
        width, height = rendering_engine.getTileSize()
        return int(width), int(height)
    except Exception as exc:
        missing_tile_method = isinstance(exc, AttributeError)
        if not missing_tile_method and not is_known_tile_size_failure(exc):
            raise
        width, height = _fallback_tile_size(image, conn=conn)
        LOGGER.warning(
            "Using fallback tile size for image %s after RenderingEngine failure",
            getattr(image, "id", None) or getattr(image, "getId", lambda: "?")(),
        )
        return width, height
