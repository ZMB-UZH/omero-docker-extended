"""OME-Zarr inspection helpers backed by the ``ome-zarr`` package."""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import metadata as importlib_metadata
from itertools import product
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

OME_ZARR_IMPORT_KIND_IMAGE = "ome_zarr_image"
OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW = "bioformats2raw_layout3"
OME_ZARR_NATIVE_GZIP_LEVEL_ENV = "OMERO_WEB_UPLOAD_NATIVE_ZARR_GZIP_LEVEL"
DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL = 1


@dataclass(frozen=True)
class OMEZarrImageInspection:
    """Summary of how the native OME-Zarr branch should treat a store."""

    recognized: bool = False
    kind: Optional[str] = None
    support_error: Optional[str] = None
    format_version: Optional[str] = None
    zarr_format: Optional[int] = None
    relative_path: Optional[str] = None
    compatibility_details: str = ""
    verify_lsid_prefix: bool = False
    image_relative_paths: tuple[str, ...] = ()
    image_node_relative_paths: tuple[str, ...] = ()
    image_display_names: tuple[str, ...] = ()
    physical_sizes: dict[str, tuple[float, str]] = field(default_factory=dict)
    dtype_name: str = ""
    shape: tuple[int, ...] = ()

    @property
    def supported(self) -> bool:
        return self.recognized and self.support_error is None and bool(self.kind)


@lru_cache(maxsize=1)
def ome_zarr_package_version() -> str:
    """Handle ome Zarr package version."""
    try:
        return importlib_metadata.version("ome-zarr")
    except importlib_metadata.PackageNotFoundError:
        return ""


def inspect_ome_zarr_image(store_root: Path) -> OMEZarrImageInspection:
    """Inspect *store_root* as a native ``omero zarr import`` source.

    This keeps the plugin's native branch grounded in the upstream
    ``ome-zarr`` reader model rather than hand-parsing NGFF metadata.
    """
    store_root = Path(store_root)
    metadata_payload, inspection = _load_root_ome_zarr_metadata(store_root)
    if inspection is not None:
        return inspection

    if metadata_payload is None:
        return OMEZarrImageInspection(
            recognized=False,
            support_error="Root metadata loaded but payload is unexpectedly None.",
        )
    if metadata_payload.get("bioformats2raw.layout") == 3:
        return _inspect_bioformats2raw_layout(store_root)

    return _inspect_single_ome_zarr_image(store_root, metadata_payload)


def normalize_native_ome_zarr_copy(store_root: Path) -> Optional[str]:
    """Normalize an ephemeral native-import copy in place.

    The installed OMERO render stack can import some valid OME-Zarr stores but
    later fail to render thumbnails when image arrays are backed by large
    Blosc-compressed chunks.  Additionally, 3D stores whose pyramids
    downsample the z-axis produce blurry slices in 2D viewers like Vizarr
    that select resolution level based on XY viewport zoom.

    This function:

    1. Rewrites Blosc-compressed chunks to gzip so the OMERO render stack
       can read them.
    2. Regenerates pyramid levels that downsample all three spatial axes
       (z, y, x) so that only y and x are downsampled — matching the
       approach used by ``ome-zarr-py``'s ``Scaler.local_mean`` and
       napari's dimension-aware multiscale level selection.
    """
    inspection = inspect_ome_zarr_image(store_root)
    if not inspection.supported:
        return inspection.support_error or (
            "Zarr source is not supported by the installed omero-cli-zarr runtime."
        )

    rewrite_error = _rewrite_problematic_native_image_arrays(store_root, inspection)
    if rewrite_error:
        return rewrite_error

    pyramid_error = _regenerate_xy_only_pyramid(store_root)
    if pyramid_error:
        return pyramid_error

    normalized = inspect_ome_zarr_image(store_root)
    if not normalized.supported:
        return normalized.support_error or (
            "Normalized OME-Zarr copy is no longer supported by the installed runtime."
        )
    return None


def _load_root_ome_zarr_metadata(
    store_root: Path,
) -> tuple[Optional[dict[str, Any]], Optional[OMEZarrImageInspection]]:
    """Handle load root ome Zarr metadata."""
    if not store_root.is_dir():
        return None, OMEZarrImageInspection()

    metadata_payload, metadata_error = _read_store_metadata_payload(store_root)
    if metadata_payload is None:
        if metadata_error is None:
            return None, OMEZarrImageInspection()
        return None, OMEZarrImageInspection(
            recognized=True, support_error=metadata_error
        )

    if not isinstance(metadata_payload, dict):
        return None, OMEZarrImageInspection(
            recognized=True,
            support_error=f"Invalid OME-Zarr metadata payload in {store_root.name}.",
        )

    if "plate" in metadata_payload:
        return None, OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr plate layouts are not supported by the native "
                "image-import path."
            ),
        )
    if "well" in metadata_payload:
        return None, OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr well layouts are not supported by the native "
                "image-import path."
            ),
        )

    return metadata_payload, None


def _inspect_single_ome_zarr_image(
    store_root: Path,
    metadata_payload: dict,
) -> OMEZarrImageInspection:
    """Handle inspect single ome Zarr image."""
    multiscales = metadata_payload.get("multiscales")
    if not isinstance(multiscales, list) or not multiscales:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr metadata was found, but no multiscale image definition "
                "was present in the root metadata."
            ),
        )

    if len(multiscales) != 1:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr store contains multiple image nodes; the native "
                "image-import path expects a single image store."
            ),
        )

    multiscale = multiscales[0]
    if not isinstance(multiscale, dict):
        return OMEZarrImageInspection(
            recognized=True,
            support_error="OME-Zarr multiscale metadata is malformed.",
        )

    display_name = str(multiscale.get("name") or "").strip()
    format_version = str(multiscale.get("version") or "").strip() or None
    zarr_format = _read_zarr_format_metadata(store_root, metadata_payload)
    axis_names, axis_units, axis_error = _extract_axes(multiscale.get("axes"))
    if axis_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=axis_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )

    if "x" not in axis_names or "y" not in axis_names:
        return OMEZarrImageInspection(
            recognized=True,
            support_error="OME-Zarr axes must include x and y for native image import.",
            format_version=format_version,
            zarr_format=zarr_format,
        )

    dataset_entries = multiscale.get("datasets")
    if not isinstance(dataset_entries, list) or not dataset_entries:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr metadata is missing multiscale dataset entries for the "
                "native image-import path."
            ),
            format_version=format_version,
            zarr_format=zarr_format,
        )

    primary_dataset = dataset_entries[0]
    if not isinstance(primary_dataset, dict):
        return OMEZarrImageInspection(
            recognized=True,
            support_error="OME-Zarr primary dataset metadata is malformed.",
            format_version=format_version,
            zarr_format=zarr_format,
        )

    primary_dataset_path = str(primary_dataset.get("path") or "").strip().strip("/")
    if not primary_dataset_path:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr primary dataset metadata is missing a readable dataset path."
            ),
            format_version=format_version,
            zarr_format=zarr_format,
        )

    physical_sizes, scale_error = _extract_physical_sizes(
        axis_names,
        axis_units,
        [
            dataset_entry.get("coordinateTransformations")
            if isinstance(dataset_entry, dict)
            else None
            for dataset_entry in dataset_entries
        ],
    )
    if scale_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=scale_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )

    array_metadata, array_error = _read_array_metadata_payload(
        store_root, primary_dataset_path
    )
    if array_metadata is None:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=array_error
            or (
                "OME-Zarr metadata was found, but the primary dataset metadata "
                "could not be read."
            ),
            format_version=format_version,
            zarr_format=zarr_format,
        )

    try:
        shape = tuple(int(value) for value in array_metadata.get("shape", ()) or ())
    except Exception:
        shape = ()
    dtype_name = _normalize_dtype_name(array_metadata.get("dtype", ""))
    dataset_relative_paths = _extract_dataset_relative_paths(metadata_payload)

    version_text = ome_zarr_package_version()
    details = "OME-Zarr image detected by ome-zarr"
    if version_text:
        details = f"{details} {version_text}"

    return OMEZarrImageInspection(
        recognized=True,
        kind=OME_ZARR_IMPORT_KIND_IMAGE,
        format_version=format_version,
        zarr_format=zarr_format,
        relative_path=primary_dataset_path or None,
        compatibility_details=details,
        image_relative_paths=dataset_relative_paths,
        image_node_relative_paths=(".",),
        image_display_names=(display_name,),
        physical_sizes=physical_sizes,
        dtype_name=dtype_name,
        shape=shape,
    )


def _inspect_bioformats2raw_layout(store_root: Path) -> OMEZarrImageInspection:
    """Handle inspect bioformats2raw layout."""
    series_dirs = sorted(
        child
        for child in store_root.iterdir()
        if child.is_dir() and child.name.isdigit()
    )
    if not series_dirs:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "bioformats2raw.layout=3 metadata was found, but the store does not "
                "contain any numeric series directories to inspect with ome-zarr."
            ),
        )

    series_numbers = [int(series_dir.name) for series_dir in series_dirs]
    expected_numbers = list(range(series_numbers[-1] + 1))
    if series_numbers != expected_numbers:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "bioformats2raw.layout=3 stores must expose contiguous numeric "
                "series directories starting at 0."
            ),
        )

    first_supported = None
    dataset_relative_paths: list[str] = []
    image_node_relative_paths: list[str] = []
    image_display_names: list[str] = []
    for series_dir in series_dirs:
        series_metadata, inspection = _load_root_ome_zarr_metadata(series_dir)
        if inspection is not None:
            error_text = (
                inspection.support_error or "ome-zarr did not recognize this series."
            )
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    f"Series {series_dir.name} is not a supported "
                    f"OME-Zarr image: {error_text}"
                ),
            )
        if series_metadata is None:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=f"Series {series_dir.name} did not expose OME-Zarr metadata.",
            )
        series_inspection = _inspect_single_ome_zarr_image(series_dir, series_metadata)
        if not series_inspection.supported:
            error_text = (
                series_inspection.support_error
                or "ome-zarr did not recognize this series."
            )
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    f"Series {series_dir.name} is not a supported "
                    f"OME-Zarr image: {error_text}"
                ),
            )
        if first_supported is None:
            first_supported = series_inspection
        image_node_relative_paths.append(series_dir.name)
        if series_inspection.image_display_names:
            image_display_names.append(series_inspection.image_display_names[0])
        else:
            image_display_names.append("")
        if series_inspection.image_relative_paths:
            dataset_relative_paths.extend(
                f"{series_dir.name}/{relative_path}"
                for relative_path in series_inspection.image_relative_paths
            )
        else:
            dataset_relative_paths.append(series_dir.name)

    version_text = ome_zarr_package_version()
    details = "bioformats2raw.layout=3 OME-Zarr detected by ome-zarr"
    if version_text:
        details = f"{details} {version_text}"

    return OMEZarrImageInspection(
        recognized=True,
        kind=OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW,
        format_version=first_supported.format_version if first_supported else None,
        zarr_format=first_supported.zarr_format if first_supported else None,
        compatibility_details=details,
        verify_lsid_prefix=True,
        image_relative_paths=tuple(dict.fromkeys(dataset_relative_paths)),
        image_node_relative_paths=tuple(image_node_relative_paths),
        image_display_names=tuple(image_display_names),
    )


def _read_store_metadata_payload(
    store_root: Path,
) -> tuple[object | None, Optional[str]]:
    """Handle read store metadata payload."""
    metadata_path = None
    for candidate_name in (".zattrs", "zarr.json"):
        candidate = store_root / candidate_name
        if candidate.is_file():
            metadata_path = candidate
            break

    if metadata_path is None:
        return None, None

    try:
        with open(metadata_path, encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, json.JSONDecodeError) as exc:
        return (
            None,
            f"Failed to read OME-Zarr metadata from {metadata_path.name}: {exc}",
        )


def _read_zarr_format_metadata(
    store_root: Path, metadata_payload: dict
) -> Optional[int]:
    """Handle read Zarr format metadata."""
    raw_value = metadata_payload.get("zarr_format")
    if isinstance(raw_value, int):
        return raw_value

    for candidate_name in (".zgroup", "zarr.json"):
        candidate = store_root / candidate_name
        if not candidate.is_file():
            continue
        try:
            with open(candidate, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("zarr_format"), int):
            return int(payload["zarr_format"])
    return None


def _read_array_metadata_payload(
    store_root: Path, relative_path: str
) -> tuple[Optional[dict], Optional[str]]:
    """Handle read array metadata payload."""
    array_root = store_root / relative_path
    metadata_path = None
    for candidate_name in (".zarray", "zarr.json"):
        candidate = array_root / candidate_name
        if candidate.is_file():
            metadata_path = candidate
            break

    if metadata_path is None:
        return (
            None,
            f"OME-Zarr dataset path is missing its array metadata: {relative_path}",
        )

    try:
        with open(metadata_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return (
            None,
            f"Failed to read OME-Zarr array metadata for {relative_path}: {exc}",
        )

    if not isinstance(payload, dict):
        return (
            None,
            f"OME-Zarr array metadata for {relative_path} must be a JSON object.",
        )
    return payload, None


def _extract_axes(axes_payload) -> tuple[list[str], dict[str, str], Optional[str]]:
    """Handle extract axes."""
    if not isinstance(axes_payload, list) or not axes_payload:
        return [], {}, "OME-Zarr metadata is missing multiscale axes information."

    axis_names = []
    axis_units = {}
    for axis in axes_payload:
        if not isinstance(axis, dict):
            return [], {}, "OME-Zarr axes must be described by metadata objects."
        axis_name = str(axis.get("name") or "").strip().lower()
        if not axis_name:
            return [], {}, "OME-Zarr axes must include non-empty axis names."
        axis_names.append(axis_name)
        axis_unit = str(axis.get("unit") or "").strip()
        if axis_unit:
            axis_units[axis_name] = axis_unit
    return axis_names, axis_units, None


def _extract_dataset_relative_paths(metadata_payload: dict) -> tuple[str, ...]:
    """Handle extract dataset relative paths."""
    paths = []
    for multiscale_entry in metadata_payload.get("multiscales") or []:
        if not isinstance(multiscale_entry, dict):
            continue
        for dataset_entry in multiscale_entry.get("datasets") or []:
            if not isinstance(dataset_entry, dict):
                continue
            dataset_path = str(dataset_entry.get("path") or "").strip().strip("/")
            if dataset_path:
                paths.append(dataset_path)
    return tuple(dict.fromkeys(paths))


def _extract_physical_sizes(
    axis_names: list[str],
    axis_units: dict[str, str],
    transforms_payload,
) -> tuple[dict[str, tuple[float, str]], Optional[str]]:
    """Handle extract physical sizes."""
    if not isinstance(transforms_payload, list) or not transforms_payload:
        return (
            {},
            "OME-Zarr metadata is missing coordinate transformations for the "
            "primary resolution level.",
        )

    primary_transforms = transforms_payload[0]
    if not isinstance(primary_transforms, list):
        return (
            {},
            "OME-Zarr coordinate transformations for the primary resolution level are malformed.",
        )

    scale_values = None
    for transform in primary_transforms:
        if not isinstance(transform, dict) or transform.get("type") != "scale":
            continue
        scale_values = transform.get("scale")
        break

    if not isinstance(scale_values, list) or len(scale_values) != len(axis_names):
        return {}, "OME-Zarr primary scale metadata does not match the image axes."

    physical_sizes = {}
    for index, axis_name in enumerate(axis_names):
        if axis_name not in {"x", "y", "z"}:
            continue
        try:
            numeric_value = float(scale_values[index])
        except (TypeError, ValueError):
            return {}, f"OME-Zarr scale value for axis {axis_name!r} is not numeric."
        if numeric_value <= 0:
            return {}, f"OME-Zarr scale value for axis {axis_name!r} must be positive."
        physical_sizes[axis_name] = (numeric_value, axis_units.get(axis_name, ""))

    return physical_sizes, None


def _normalize_dtype_name(raw_dtype) -> str:
    """Handle normalize dtype name."""
    try:
        import numpy as np

        return np.dtype(raw_dtype).name
    except Exception:
        return str(raw_dtype or "").strip()


def _native_ome_zarr_gzip_level() -> int:
    """Handle native ome Zarr gzip level."""
    raw_value = str(os.environ.get(OME_ZARR_NATIVE_GZIP_LEVEL_ENV) or "").strip()
    if not raw_value:
        return DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL
    if parsed < 0:
        return DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL
    return parsed


def _rewrite_problematic_native_image_arrays(
    store_root: Path,
    inspection: OMEZarrImageInspection,
) -> Optional[str]:
    """Handle rewrite problematic native image arrays."""
    if not inspection.image_relative_paths:
        return None

    try:
        import numcodecs
        from numcodecs import GZip
    except Exception as exc:
        return f"Failed to load numcodecs for native OME-Zarr normalization: {exc}"

    gzip_level = _native_ome_zarr_gzip_level()
    gzip_codec = GZip(level=gzip_level)
    gzip_spec = {"id": "gzip", "level": gzip_level}

    for relative_path in inspection.image_relative_paths:
        array_dir = store_root / relative_path
        zarray_path = array_dir / ".zarray"
        if not zarray_path.is_file():
            return f"OME-Zarr dataset path is missing its .zarray metadata: {relative_path}"

        try:
            metadata_payload = json.loads(zarray_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"Failed to read OME-Zarr array metadata for {relative_path}: {exc}"

        compressor_spec = metadata_payload.get("compressor")
        if not isinstance(compressor_spec, dict):
            continue
        if str(compressor_spec.get("id") or "").strip().lower() != "blosc":
            continue

        try:
            source_codec = numcodecs.get_codec(compressor_spec)
        except Exception as exc:
            return f"Failed to load OME-Zarr compressor for {relative_path}: {exc}"

        for chunk_path in _iter_zarr_chunk_files(array_dir):
            try:
                encoded_bytes = chunk_path.read_bytes()
                decoded_bytes = source_codec.decode(encoded_bytes)
                chunk_path.write_bytes(gzip_codec.encode(decoded_bytes))
            except Exception as exc:
                relative_chunk_path = chunk_path.relative_to(store_root)
                return (
                    f"Failed to normalize OME-Zarr chunk {relative_chunk_path}: {exc}"
                )

        metadata_payload["compressor"] = gzip_spec
        try:
            zarray_path.write_text(json.dumps(metadata_payload), encoding="utf-8")
        except OSError as exc:
            return f"Failed to update OME-Zarr compressor metadata for {relative_path}: {exc}"

    return None


def _iter_zarr_chunk_files(array_dir: Path):
    """Handle iter Zarr chunk files."""
    for path in sorted(array_dir.rglob("*")):
        if path.is_dir():
            continue
        if path.name.startswith("."):
            continue
        yield path


def _has_3d_pyramid_downsampling(store_root: Path) -> Optional[dict]:
    """Detect if a zarr store downsamples the z-axis between pyramid levels.

    3D-downsampled pyramids cause blurry z-slices in 2D viewers (Vizarr)
    that select resolution level based on XY viewport zoom.  Returns a
    metadata dict when 3D downsampling is detected, ``None`` otherwise.
    """
    metadata_payload, _ = _read_store_metadata_payload(store_root)
    if not isinstance(metadata_payload, dict):
        return None

    multiscales = metadata_payload.get("multiscales")
    if not isinstance(multiscales, list) or not multiscales:
        return None

    ms = multiscales[0]
    if not isinstance(ms, dict):
        return None
    axes = ms.get("axes")
    datasets = ms.get("datasets")
    if (
        not isinstance(axes, list)
        or not isinstance(datasets, list)
        or len(datasets) < 2
    ):
        return None

    z_axis_index = None
    yx_indices = []
    for i, axis in enumerate(axes):
        if not isinstance(axis, dict):
            continue
        name = str(axis.get("name") or "").strip().lower()
        if name == "z":
            z_axis_index = i
        elif name in ("y", "x"):
            yx_indices.append(i)

    if z_axis_index is None or len(yx_indices) < 2:
        return None

    s0_path = datasets[0].get("path", "")
    s1_path = datasets[1].get("path", "")
    s0_zarray = store_root / s0_path / ".zarray"
    s1_zarray = store_root / s1_path / ".zarray"
    if not s0_zarray.is_file() or not s1_zarray.is_file():
        return None

    try:
        s0_shape = json.loads(s0_zarray.read_text(encoding="utf-8")).get("shape", [])
        s1_shape = json.loads(s1_zarray.read_text(encoding="utf-8")).get("shape", [])
    except (OSError, json.JSONDecodeError):
        return None

    ndim = len(axes)
    if len(s0_shape) != ndim or len(s1_shape) != ndim:
        return None

    if s0_shape[z_axis_index] == s1_shape[z_axis_index]:
        return None

    return {
        "metadata_payload": metadata_payload,
        "multiscale": ms,
        "axes": axes,
        "datasets": datasets,
        "z_axis_index": z_axis_index,
        "yx_indices": yx_indices,
        "s0_path": s0_path,
    }


def _downscale_local_mean_fallback(data, factors):
    """Handle downscale local mean fallback."""
    import numpy as np

    result = np.asarray(data, dtype=np.float64)
    if result.ndim != len(factors):
        raise ValueError("Downscale factor count must match the data rank.")

    for axis, raw_factor in enumerate(factors):
        factor = int(raw_factor)
        if factor <= 1:
            continue
        axis_length = result.shape[axis]
        block_count = math.ceil(axis_length / factor)
        pad = block_count * factor - axis_length
        if pad:
            pad_width = [(0, 0)] * result.ndim
            pad_width[axis] = (0, pad)
            result = np.pad(
                result,
                pad_width,
                mode="constant",
                constant_values=np.nan,
            )
        new_shape = (
            result.shape[:axis] + (block_count, factor) + result.shape[axis + 1 :]
        )
        result = np.nanmean(result.reshape(new_shape), axis=axis + 1)
    return result


def _downscale_local_mean(data, factors):
    """Handle downscale local mean."""
    try:
        from skimage.transform import (
            downscale_local_mean as _skimage_downscale_local_mean,
        )
    except Exception:
        return _downscale_local_mean_fallback(data, factors)
    return _skimage_downscale_local_mean(data, factors=factors)


def _read_zarr_v2_array(array_dir: Path, metadata: dict):
    """Handle read Zarr v2 array."""
    import numpy as np

    try:
        shape = tuple(int(value) for value in metadata["shape"])
        chunks = tuple(int(value) for value in metadata["chunks"])
        dtype = np.dtype(metadata["dtype"])
    except Exception as exc:
        raise RuntimeError(f"invalid zarr array metadata: {exc}") from exc

    fill_value = metadata.get("fill_value", 0)
    filters_spec = metadata.get("filters")
    if filters_spec not in (None, []):
        raise RuntimeError("filters are not supported for pyramid regeneration input")

    codec = None
    compressor_spec = metadata.get("compressor")
    if compressor_spec:
        try:
            import numcodecs

            codec = numcodecs.get_codec(compressor_spec)
        except Exception as exc:
            raise RuntimeError(
                f"failed to load source compressor for pyramid regeneration: {exc}"
            ) from exc

    data = np.full(shape, fill_value, dtype=dtype)
    chunk_grid = [math.ceil(size / chunk) for size, chunk in zip(shape, chunks)]
    dimension_separator = str(metadata.get("dimension_separator") or ".")

    for coords in product(*(range(size) for size in chunk_grid)):
        relative_path = (
            "/".join(str(coord) for coord in coords)
            if dimension_separator == "/"
            else ".".join(str(coord) for coord in coords)
        )
        chunk_path = array_dir / relative_path
        if not chunk_path.is_file():
            continue
        raw_bytes = chunk_path.read_bytes()
        if codec is not None:
            raw_bytes = codec.decode(raw_bytes)
        chunk_array = np.frombuffer(raw_bytes, dtype=dtype).reshape(chunks)

        chunk_slices = []
        chunk_crop = []
        for axis, coord in enumerate(coords):
            start = coord * chunks[axis]
            stop = min(start + chunks[axis], shape[axis])
            chunk_slices.append(slice(start, stop))
            chunk_crop.append(slice(0, stop - start))
        data[tuple(chunk_slices)] = chunk_array[tuple(chunk_crop)]

    return data


def _regenerate_xy_only_pyramid(
    store_root: Path, downscale_factor: int = 2
) -> Optional[str]:
    """Regenerate pyramid levels so only YX axes are downsampled.

    Preserves ``s0`` (full resolution) unchanged.  Removes old
    downsampled levels and writes new ones using ``local_mean``
    downsampling on the YX axes only — the same strategy used by
    ``ome-zarr-py``'s ``Scaler.local_mean`` and by napari's
    dimension-aware level selection.

    Returns ``None`` on success or an error string on failure.
    """
    detection = _has_3d_pyramid_downsampling(store_root)
    if detection is None:
        return None

    try:
        import numpy as np
    except Exception as exc:
        return f"Missing dependency for pyramid regeneration: {exc}"

    ms = detection["multiscale"]
    axes = detection["axes"]
    datasets = detection["datasets"]
    yx_indices = detection["yx_indices"]
    s0_path = detection["s0_path"]
    ndim = len(axes)

    s0_zarray_path = store_root / s0_path / ".zarray"
    try:
        s0_meta = json.loads(s0_zarray_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"Failed to read s0 .zarray metadata: {exc}"

    s0_chunks = s0_meta["chunks"]
    s0_dtype = np.dtype(s0_meta["dtype"])
    s0_compressor = s0_meta.get("compressor")
    s0_filters = s0_meta.get("filters")

    if isinstance(s0_filters, list) and len(s0_filters) == 0:
        s0_filters = None
        s0_meta["filters"] = None
        try:
            s0_zarray_path.write_text(json.dumps(s0_meta), encoding="utf-8")
        except OSError:
            LOGGER.debug("Suppressed OSError writing .zarray metadata", exc_info=True)

    s0_transforms = datasets[0].get("coordinateTransformations", [])
    s0_scale = None
    s0_translation = None
    for t in s0_transforms:
        if isinstance(t, dict) and t.get("type") == "scale":
            s0_scale = list(t["scale"])
        elif isinstance(t, dict) and t.get("type") == "translation":
            s0_translation = list(t["translation"])
    if s0_scale is None or len(s0_scale) != ndim:
        return "Cannot regenerate pyramid: s0 scale transform is missing or malformed."

    try:
        s0_data = _read_zarr_v2_array(store_root / s0_path, s0_meta)
    except Exception as exc:
        return f"Failed to read full-resolution data: {exc}"

    base_factors = tuple(
        downscale_factor if i in yx_indices else 1 for i in range(ndim)
    )

    for ds in datasets[1:]:
        old_dir = store_root / ds["path"]
        if old_dir.is_dir():
            shutil.rmtree(old_dir)

    codec = None
    if s0_compressor:
        try:
            import numcodecs

            codec = numcodecs.get_codec(s0_compressor)
        except Exception as exc:
            return f"Failed to load compressor for pyramid regeneration: {exc}"

    new_datasets = [datasets[0]]
    current_data = s0_data
    current_scale = list(s0_scale)
    current_translation = list(s0_translation) if s0_translation else [0.0] * ndim

    for level_idx in range(1, len(datasets)):
        next_yx = [current_data.shape[i] // downscale_factor for i in yx_indices]
        if any(s < 2 for s in next_yx):
            break

        downsampled = _downscale_local_mean(current_data, base_factors).astype(s0_dtype)
        new_scale = list(current_scale)
        new_translation = list(current_translation)
        for ax_i in yx_indices:
            new_scale[ax_i] = current_scale[ax_i] * downscale_factor
            new_translation[ax_i] = (
                current_translation[ax_i]
                + (current_scale[ax_i] * (downscale_factor - 1)) / 2
            )

        level_path = datasets[level_idx]["path"]
        level_dir = store_root / level_path
        error = _write_zarr_v2_level(
            level_dir, downsampled, s0_chunks, s0_compressor, s0_filters, codec
        )
        if error:
            return error

        transforms = [{"type": "scale", "scale": new_scale}]
        if s0_translation is not None:
            transforms.append({"type": "translation", "translation": new_translation})
        new_datasets.append(
            {"path": level_path, "coordinateTransformations": transforms}
        )

        current_data = downsampled
        current_scale = new_scale
        current_translation = new_translation

    ms["datasets"] = new_datasets
    if "coordinateTransformations" in ms and not ms["coordinateTransformations"]:
        del ms["coordinateTransformations"]

    payload = detection["metadata_payload"]
    payload["multiscales"] = [ms]
    try:
        (store_root / ".zattrs").write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        return f"Failed to write updated .zattrs: {exc}"

    return None


def _write_zarr_v2_level(
    output_dir: Path,
    data,
    chunks: list,
    compressor_spec: Optional[dict],
    filters_spec,
    codec,
) -> Optional[str]:
    """Write a numpy array as zarr v2 chunk files."""
    import numpy as np

    output_dir.mkdir(parents=True, exist_ok=True)
    shape = list(data.shape)
    ndim = len(shape)

    zarray_meta = {
        "zarr_format": 2,
        "shape": shape,
        "chunks": chunks,
        "dtype": data.dtype.str,
        "compressor": compressor_spec,
        "fill_value": 0,
        "filters": filters_spec,
        "order": "C",
        "dimension_separator": "/",
    }
    try:
        (output_dir / ".zarray").write_text(json.dumps(zarray_meta), encoding="utf-8")
    except OSError as exc:
        return f"Failed to write .zarray for {output_dir.name}: {exc}"

    chunk_grid = [math.ceil(s / c) for s, c in zip(shape, chunks)]
    total_chunks = 1
    for g in chunk_grid:
        total_chunks *= g

    for flat_idx in range(total_chunks):
        coords: list[int] = []
        remainder = flat_idx
        for dim in range(ndim - 1, -1, -1):
            coords.insert(0, remainder % chunk_grid[dim])
            remainder //= chunk_grid[dim]

        slices = tuple(
            slice(
                coords[d] * chunks[d], min(coords[d] * chunks[d] + chunks[d], shape[d])
            )
            for d in range(ndim)
        )
        chunk_data = data[slices]

        if chunk_data.shape != tuple(chunks):
            padded = np.zeros(chunks, dtype=data.dtype)
            padded[tuple(slice(0, s) for s in chunk_data.shape)] = chunk_data
            chunk_data = padded

        raw_bytes = chunk_data.tobytes(order="C")
        if codec is not None:
            raw_bytes = codec.encode(raw_bytes)

        chunk_path = output_dir / "/".join(str(c) for c in coords)
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            chunk_path.write_bytes(raw_bytes)
        except OSError as exc:
            return f"Failed to write chunk {'/'.join(str(c) for c in coords)}: {exc}"

    return None


@lru_cache(maxsize=1)
def _ome_zarr_runtime() -> tuple[Optional[dict[str, object]], Optional[str]]:
    """Handle ome Zarr runtime."""
    try:
        from ome_zarr.format import CurrentFormat, detect_format
        from ome_zarr.io import parse_url
        from ome_zarr.reader import Reader
    except Exception as exc:
        return None, str(exc)

    return {
        "CurrentFormat": CurrentFormat,
        "Reader": Reader,
        "detect_format": detect_format,
        "parse_url": parse_url,
    }, None
