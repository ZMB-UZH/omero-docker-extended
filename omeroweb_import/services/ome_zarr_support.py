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
from pathlib import Path, PurePosixPath
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

OME_ZARR_IMPORT_KIND_IMAGE = "ome_zarr_image"
OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW = "bioformats2raw_layout3"
OME_ZARR_NATIVE_GZIP_LEVEL_ENV = "OMERO_WEB_UPLOAD_NATIVE_ZARR_GZIP_LEVEL"
OME_ZARR_NATIVE_MAX_ARRAY_BYTES_ENV = "OMERO_WEB_UPLOAD_NATIVE_ZARR_MAX_ARRAY_BYTES"
OME_ZARR_NATIVE_MAX_CHUNKS_ENV = "OMERO_WEB_UPLOAD_NATIVE_ZARR_MAX_CHUNKS"
DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL = 1
DEFAULT_OME_ZARR_NATIVE_MAX_ARRAY_BYTES = 1024 * 1024 * 1024
DEFAULT_OME_ZARR_NATIVE_MAX_CHUNKS = 250000


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
        """Return the supported for `OMEZarrImageInspection`.

        Inputs: none. Output: `bool`.
        """
        return self.recognized and self.support_error is None and bool(self.kind)


@lru_cache(maxsize=1)
def ome_zarr_package_version() -> str:
    """Ome Zarr package version.

    Inputs: none. Output: `str`.
    """
    try:
        return importlib_metadata.version("ome-zarr")
    except importlib_metadata.PackageNotFoundError:
        return ""


def inspect_ome_zarr_image(store_root: Path) -> OMEZarrImageInspection:
    """Inspect *store_root* as a native ``omero zarr import`` source.

    Inputs: `store_root`. Output: `OMEZarrImageInspection`.

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
    """Normalize the native OME Zarr copy.

    Inputs: `store_root` (Path). Output: `Optional[str]`.
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
    """Load the root OME Zarr metadata.

    Inputs: `store_root` (Path). Output: `tuple[Optional[dict[str, Any]],
    Optional[OMEZarrImageInspection]]`.
    """
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
    """Inspect single ome Zarr image.

    Inputs: `store_root`, `metadata_payload`. Output: `OMEZarrImageInspection`.
    """
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
    format_version = (
        str(multiscale.get("version") or metadata_payload.get("version") or "").strip()
        or None
    )
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

    primary_dataset_path, path_error = _normalize_zarr_relative_path(
        primary_dataset.get("path")
    )
    if path_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=f"OME-Zarr primary dataset path is invalid: {path_error}",
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
        multiscale.get("coordinateTransformations"),
    )
    if scale_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=scale_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )

    dataset_relative_paths, path_error = _extract_dataset_relative_paths(
        metadata_payload
    )
    if path_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=path_error,
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

    shape, shape_error = _extract_array_shape(array_metadata, len(axis_names))
    if shape_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=shape_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )
    dimension_error = _validate_dimension_names(
        array_metadata,
        axis_names,
        zarr_format,
    )
    if dimension_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=dimension_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )
    dtype_name, dtype_error = _normalize_dtype_name(
        array_metadata.get("dtype", array_metadata.get("data_type"))
    )
    if dtype_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=dtype_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )

    for relative_path in dataset_relative_paths:
        if relative_path == primary_dataset_path:
            continue
        level_metadata, level_error = _read_array_metadata_payload(
            store_root,
            relative_path,
        )
        if level_metadata is None:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=level_error
                or "OME-Zarr dataset array metadata could not be read.",
                format_version=format_version,
                zarr_format=zarr_format,
            )
        _, level_shape_error = _extract_array_shape(level_metadata, len(axis_names))
        if level_shape_error:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    f"OME-Zarr array metadata for {relative_path} is invalid: "
                    f"{level_shape_error}"
                ),
                format_version=format_version,
                zarr_format=zarr_format,
            )
        level_dimension_error = _validate_dimension_names(
            level_metadata,
            axis_names,
            zarr_format,
        )
        if level_dimension_error:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    f"OME-Zarr array metadata for {relative_path} is invalid: "
                    f"{level_dimension_error}"
                ),
                format_version=format_version,
                zarr_format=zarr_format,
            )

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
    """Return the inspect bioformats2raw layout.

    Inputs: `store_root` (Path). Output: `OMEZarrImageInspection`.
    """
    series_paths, series_error = _bioformats2raw_series_paths(store_root)
    if series_error:
        return OMEZarrImageInspection(recognized=True, support_error=series_error)
    if not series_paths:
        numeric_dirs = sorted(
            child
            for child in store_root.iterdir()
            if child.is_dir() and child.name.isdigit()
        )
        if not numeric_dirs:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    "bioformats2raw.layout=3 metadata was found, but the store "
                    "does not contain any numeric series directories or OME "
                    "series metadata to inspect with ome-zarr."
                ),
            )

        series_numbers = [int(series_dir.name) for series_dir in numeric_dirs]
        expected_numbers = list(range(series_numbers[-1] + 1))
        if series_numbers != expected_numbers:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    "bioformats2raw.layout=3 stores must expose contiguous numeric "
                    "series directories starting at 0 when OME series metadata "
                    "does not declare explicit image paths."
                ),
            )
        series_paths = tuple(series_dir.name for series_dir in numeric_dirs)

    first_supported = None
    dataset_relative_paths: list[str] = []
    image_node_relative_paths: list[str] = []
    image_display_names: list[str] = []
    for series_path in series_paths:
        series_dir = store_root / series_path
        if not series_dir.is_dir():
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    f"Series {series_path} from bioformats2raw metadata is not "
                    "a readable OME-Zarr image directory."
                ),
            )
        series_metadata, inspection = _load_root_ome_zarr_metadata(series_dir)
        if inspection is not None:
            error_text = (
                inspection.support_error or "ome-zarr did not recognize this series."
            )
            return OMEZarrImageInspection(
                recognized=True,
                support_error=(
                    f"Series {series_path} is not a supported "
                    f"OME-Zarr image: {error_text}"
                ),
            )
        if series_metadata is None:
            return OMEZarrImageInspection(
                recognized=True,
                support_error=f"Series {series_path} did not expose OME-Zarr metadata.",
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
                    f"Series {series_path} is not a supported "
                    f"OME-Zarr image: {error_text}"
                ),
            )
        if first_supported is None:
            first_supported = series_inspection
        image_node_relative_paths.append(series_path)
        if series_inspection.image_display_names:
            image_display_names.append(series_inspection.image_display_names[0])
        else:
            image_display_names.append("")
        if series_inspection.image_relative_paths:
            dataset_relative_paths.extend(
                f"{series_path}/{relative_path}"
                for relative_path in series_inspection.image_relative_paths
            )
        else:
            dataset_relative_paths.append(series_path)

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


def _bioformats2raw_series_paths(
    store_root: Path,
) -> tuple[tuple[str, ...], Optional[str]]:
    """Return series paths declared by bioformats2raw OME metadata.

    Inputs: `store_root` (Path). Output: `(paths, error)`.
    """
    ome_payload, inspection = _load_root_ome_zarr_metadata(store_root / "OME")
    if inspection is not None:
        if inspection.recognized and inspection.support_error:
            return (), inspection.support_error
        return (), None
    if not isinstance(ome_payload, dict) or "series" not in ome_payload:
        return (), None

    series_payload = ome_payload.get("series")
    if not isinstance(series_payload, list) or not series_payload:
        return (
            (),
            "bioformats2raw.layout=3 OME series metadata must be a non-empty list.",
        )

    paths = []
    seen = set()
    for raw_path in series_payload:
        normalized, path_error = _normalize_zarr_relative_path(raw_path)
        if path_error:
            return (), f"Invalid bioformats2raw OME series path: {path_error}"
        if normalized in seen:
            return (), f"Duplicate bioformats2raw OME series path: {normalized}"
        seen.add(normalized)
        paths.append(normalized)
    return tuple(paths), None


def _normalize_zarr_relative_path(raw_path) -> tuple[str, Optional[str]]:
    """Return a safe Zarr relative group path from metadata.

    Inputs: `raw_path`. Output: `(path, error)`.
    """
    if not isinstance(raw_path, str):
        return "", "series and dataset paths must be strings."
    path_text = raw_path.strip()
    if not path_text:
        return "", "series paths must be non-empty strings."
    if "\\" in path_text:
        return "", f"{path_text!r} contains a backslash path separator."
    pure_path = PurePosixPath(path_text)
    if pure_path.is_absolute():
        return "", f"{path_text!r} must be relative."
    path_text = path_text.strip("/")
    pure_path = PurePosixPath(path_text)
    parts = pure_path.parts
    if any(part in {"", ".", ".."} for part in parts):
        return "", f"{path_text!r} contains an unsafe path component."
    return "/".join(parts), None


def _read_store_metadata_payload(
    store_root: Path,
) -> tuple[object | None, Optional[str]]:
    """Read the store metadata payload.

    Inputs: `store_root` (Path). Output: `tuple[object | None, Optional[str]]`.
    """
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
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return (
            None,
            f"Failed to read OME-Zarr metadata from {metadata_path.name}: {exc}",
        )
    return _normalize_store_metadata_payload(payload, metadata_path.name)


def _normalize_store_metadata_payload(
    payload,
    metadata_name: str,
) -> tuple[object | None, Optional[str]]:
    """Return OME metadata normalized across Zarr v2 and v3 containers.

    Inputs: `payload`, `metadata_name` (str). Output: `(payload, error)`.
    """
    if not isinstance(payload, dict):
        return payload, None
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict) or "ome" not in attributes:
        return payload, None
    ome_payload = attributes.get("ome")
    if not isinstance(ome_payload, dict):
        return (
            None,
            f"Invalid OME-Zarr metadata payload in {metadata_name}: "
            "attributes.ome must be a JSON object.",
        )
    return dict(ome_payload), None


def _read_zarr_format_metadata(
    store_root: Path, metadata_payload: dict
) -> Optional[int]:
    """Read the Zarr format metadata.

    Inputs: `store_root` (Path), `metadata_payload` (dict). Output: `Optional[int]`.
    """
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
    """Read the array metadata payload.

    Inputs: `store_root` (Path), `relative_path` (str). Output: `tuple[Optional[dict],
    Optional[str]]`.
    """
    safe_relative_path, path_error = _normalize_zarr_relative_path(relative_path)
    if path_error:
        return None, f"OME-Zarr dataset path is invalid: {path_error}"

    array_root = store_root / safe_relative_path
    metadata_path = None
    for candidate_name in (".zarray", "zarr.json"):
        candidate = array_root / candidate_name
        if candidate.is_file():
            metadata_path = candidate
            break

    if metadata_path is None:
        return (
            None,
            f"OME-Zarr dataset path is missing its array metadata: {safe_relative_path}",
        )

    try:
        with open(metadata_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return (
            None,
            f"Failed to read OME-Zarr array metadata for {safe_relative_path}: {exc}",
        )

    if not isinstance(payload, dict):
        return (
            None,
            f"OME-Zarr array metadata for {safe_relative_path} must be a JSON object.",
        )
    return payload, None


def _validate_dimension_names(
    array_metadata: dict,
    axis_names: list[str],
    zarr_format: Optional[int],
) -> Optional[str]:
    """Return an error when Zarr dimension names disagree with NGFF axes.

    Inputs: `array_metadata` (dict), `axis_names` (list[str]), `zarr_format`
    (Optional[int]). Output: optional error text.
    """
    dimension_names = array_metadata.get("dimension_names")
    if dimension_names is None:
        if zarr_format == 3:
            return (
                "OME-Zarr v0.5/Zarr v3 arrays must declare dimension_names that "
                "match the multiscale axes."
            )
        return None
    if (
        not isinstance(dimension_names, list)
        or not all(isinstance(name, str) for name in dimension_names)
        or [name.strip().lower() for name in dimension_names] != axis_names
    ):
        return "OME-Zarr primary array dimension_names must match the multiscale axes."
    return None


def _extract_array_shape(
    array_metadata: dict,
    axis_count: int,
) -> tuple[tuple[int, ...], Optional[str]]:
    """Return the primary array shape from metadata.

    Inputs: `array_metadata` (dict), `axis_count` (int). Output: `(shape, error)`.
    """
    raw_shape = array_metadata.get("shape")
    if not isinstance(raw_shape, list) or not raw_shape:
        return (
            (),
            "OME-Zarr primary array shape must be a non-empty list that matches the image axes.",
        )
    if len(raw_shape) != axis_count:
        return (
            (),
            "OME-Zarr primary array shape rank does not match the image axes.",
        )
    shape = []
    for index, raw_value in enumerate(raw_shape):
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            return (
                (),
                f"OME-Zarr primary array shape axis index {index} must be a positive integer.",
            )
        if raw_value <= 0:
            return (
                (),
                f"OME-Zarr primary array shape axis index {index} must be a positive integer.",
            )
        shape.append(raw_value)
    return tuple(shape), None


def _extract_axes(axes_payload) -> tuple[list[str], dict[str, str], Optional[str]]:
    """Extract the axes.

    Inputs: `axes_payload`. Output: `tuple[list[str], dict[str, str], Optional[str]]`.
    """
    if not isinstance(axes_payload, list) or not axes_payload:
        return [], {}, "OME-Zarr metadata is missing multiscale axes information."

    axis_names = []
    axis_units = {}
    for axis in axes_payload:
        if not isinstance(axis, dict):
            return [], {}, "OME-Zarr axes must be described by metadata objects."
        raw_axis_name = axis.get("name")
        if not isinstance(raw_axis_name, str):
            return [], {}, "OME-Zarr axes must include string axis names."
        axis_name = raw_axis_name.strip().lower()
        if not axis_name:
            return [], {}, "OME-Zarr axes must include non-empty axis names."
        if axis_name in axis_names:
            return [], {}, "OME-Zarr axes must include unique axis names."
        axis_names.append(axis_name)
        raw_axis_unit = axis.get("unit")
        if raw_axis_unit is not None and not isinstance(raw_axis_unit, str):
            return [], {}, "OME-Zarr axis units must be strings when present."
        axis_unit = (raw_axis_unit or "").strip()
        if axis_unit:
            axis_units[axis_name] = axis_unit
    return axis_names, axis_units, None


def _extract_dataset_relative_paths(
    metadata_payload: dict,
) -> tuple[tuple[str, ...], Optional[str]]:
    """Extract the dataset relative paths.

    Inputs: `metadata_payload` (dict). Output: `(paths, error)`.
    """
    paths = []
    for multiscale_entry in metadata_payload.get("multiscales") or []:
        if not isinstance(multiscale_entry, dict):
            return (), "OME-Zarr multiscale metadata is malformed."
        for dataset_entry in multiscale_entry.get("datasets") or []:
            if not isinstance(dataset_entry, dict):
                return (), "OME-Zarr multiscale dataset metadata is malformed."
            dataset_path, path_error = _normalize_zarr_relative_path(
                dataset_entry.get("path")
            )
            if path_error:
                return (
                    (),
                    f"OME-Zarr multiscale dataset path is invalid: {path_error}",
                )
            paths.append(dataset_path)
    if not paths:
        return (), "OME-Zarr metadata is missing multiscale dataset paths."
    return tuple(dict.fromkeys(paths)), None


def _extract_physical_sizes(
    axis_names: list[str],
    axis_units: dict[str, str],
    transforms_payload,
    multiscale_transforms_payload=None,
) -> tuple[dict[str, tuple[float, str]], Optional[str]]:
    """Extract the physical sizes.

    Inputs: `axis_names` (list[str]), `axis_units` (dict[str, str]),
    `transforms_payload`, `multiscale_transforms_payload`. Output:
    `tuple[dict[str, tuple[float, str]], Optional[str]]`.
    """
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

    primary_scale, scale_error = _extract_scale_values(
        primary_transforms,
        len(axis_names),
        "primary",
        required=True,
    )
    if scale_error:
        return {}, scale_error
    for level_index, level_transforms in enumerate(transforms_payload[1:], start=1):
        _, scale_error = _extract_scale_values(
            level_transforms,
            len(axis_names),
            f"dataset level {level_index}",
            required=True,
        )
        if scale_error:
            return {}, scale_error
    multiscale_scale, scale_error = _extract_scale_values(
        multiscale_transforms_payload,
        len(axis_names),
        "multiscale",
        required=False,
    )
    if scale_error:
        return {}, scale_error
    scale_values = [
        primary_scale[index] * multiscale_scale[index]
        for index in range(len(axis_names))
    ]

    physical_sizes = {}
    for index, axis_name in enumerate(axis_names):
        if axis_name not in {"x", "y", "z"}:
            continue
        physical_sizes[axis_name] = (
            scale_values[index],
            axis_units.get(axis_name, ""),
        )

    return physical_sizes, None


def _extract_scale_values(
    transforms_payload,
    axis_count: int,
    label: str,
    *,
    required: bool,
) -> tuple[list[float], Optional[str]]:
    """Return the composed scale values for one transform list.

    Inputs: `transforms_payload`, `axis_count` (int), `label` (str), `required` (bool).
    Output: `(scale_values, error)`.
    """
    identity = [1.0] * axis_count
    if transforms_payload is None:
        if required:
            return (
                identity,
                "OME-Zarr primary scale metadata does not match the image axes.",
            )
        return identity, None
    if not isinstance(transforms_payload, list):
        return (
            identity,
            f"OME-Zarr {label} coordinate transformations are malformed.",
        )
    if not transforms_payload:
        return (
            identity,
            f"OME-Zarr {label} scale metadata does not match the image axes.",
        )

    scale_values = list(identity)
    saw_scale = False
    saw_translation = False
    for transform in transforms_payload:
        if not isinstance(transform, dict):
            return (
                identity,
                f"OME-Zarr {label} coordinate transformations are malformed.",
            )
        transform_type = transform.get("type")
        if transform_type == "translation":
            if not saw_scale:
                return (
                    identity,
                    f"OME-Zarr {label} translation metadata must follow scale metadata.",
                )
            translation = transform.get("translation")
            if not isinstance(translation, list) or len(translation) != axis_count:
                return (
                    identity,
                    f"OME-Zarr {label} translation metadata does not match the image axes.",
                )
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in translation
            ):
                return (
                    identity,
                    f"OME-Zarr {label} translation metadata must contain numeric values.",
                )
            if saw_translation:
                return (
                    identity,
                    f"OME-Zarr {label} coordinate transformations contain multiple translations.",
                )
            saw_translation = True
            continue
        if transform_type != "scale":
            return (
                identity,
                f"OME-Zarr {label} coordinate transformation type {transform_type!r} "
                "is not supported for native image import.",
            )
        if saw_scale:
            return (
                identity,
                f"OME-Zarr {label} coordinate transformations contain multiple scales.",
            )
        raw_scale = transform.get("scale")
        if not isinstance(raw_scale, list) or len(raw_scale) != axis_count:
            return (
                identity,
                f"OME-Zarr {label} scale metadata does not match the image axes.",
            )
        for index, raw_value in enumerate(raw_scale):
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                return (
                    identity,
                    f"OME-Zarr scale value for axis index {index} is not numeric.",
                )
            numeric_value = float(raw_value)
            if numeric_value <= 0:
                return (
                    identity,
                    f"OME-Zarr scale value for axis index {index} must be positive.",
                )
            scale_values[index] *= numeric_value
        saw_scale = True

    return scale_values, None


def _normalize_dtype_name(raw_dtype) -> tuple[str, Optional[str]]:
    """Normalize the dtype name.

    Inputs: `raw_dtype`. Output: `(dtype, error)`.
    """
    if raw_dtype is None:
        return "", "OME-Zarr primary array dtype metadata is missing."
    try:
        import numpy as np

        return np.dtype(raw_dtype).name, None
    except Exception:
        return "", "OME-Zarr primary array dtype metadata is invalid."


def _int_env(env_key: str, default: int, min_value: int, max_value: int) -> int:
    """Return an integer environment value within bounds.

    Inputs: `env_key`, `default`, `min_value`, `max_value`. Output: `int`.
    """
    raw_value = str(os.environ.get(env_key) or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    if parsed < min_value or parsed > max_value:
        return default
    return parsed


def _native_ome_zarr_gzip_level() -> int:
    """Native ome Zarr gzip level.

    Inputs: none. Output: `int`.
    """
    return _int_env(
        OME_ZARR_NATIVE_GZIP_LEVEL_ENV,
        DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL,
        0,
        9,
    )


def _native_ome_zarr_max_array_bytes() -> int:
    """Return max native OME-Zarr array bytes for in-process normalization.

    Inputs: none. Output: `int`.
    """
    return _int_env(
        OME_ZARR_NATIVE_MAX_ARRAY_BYTES_ENV,
        DEFAULT_OME_ZARR_NATIVE_MAX_ARRAY_BYTES,
        1,
        64 * 1024 * 1024 * 1024,
    )


def _native_ome_zarr_max_chunks() -> int:
    """Return max native OME-Zarr chunk count for in-process normalization.

    Inputs: none. Output: `int`.
    """
    return _int_env(
        OME_ZARR_NATIVE_MAX_CHUNKS_ENV,
        DEFAULT_OME_ZARR_NATIVE_MAX_CHUNKS,
        1,
        100000000,
    )


def _array_nbytes(shape: tuple[int, ...], dtype) -> int:
    """Return the byte size for an array shape and dtype.

    Inputs: `shape`, `dtype`. Output: `int`.
    """
    total = 1
    for size in shape:
        total *= int(size)
    return total * int(dtype.itemsize)


def _zarr_chunk_grid_size(shape: tuple[int, ...], chunks: tuple[int, ...]) -> int:
    """Return the total Zarr chunk count implied by shape and chunks.

    Inputs: `shape`, `chunks`. Output: `int`.
    """
    total = 1
    for size, chunk in zip(shape, chunks):
        total *= math.ceil(size / chunk)
    return total


def _validate_native_array_bounds(
    shape: tuple[int, ...],
    chunks: tuple[int, ...],
    dtype,
    label: str,
) -> None:
    """Raise when native OME-Zarr normalization would exceed configured bounds.

    Inputs: `shape`, `chunks`, `dtype`, `label`. Output: None.
    """
    array_bytes = _array_nbytes(shape, dtype)
    max_bytes = _native_ome_zarr_max_array_bytes()
    if array_bytes > max_bytes:
        raise RuntimeError(
            f"{label} array size {array_bytes} bytes exceeds configured limit "
            f"{max_bytes} bytes"
        )

    chunk_count = _zarr_chunk_grid_size(shape, chunks)
    max_chunks = _native_ome_zarr_max_chunks()
    if chunk_count > max_chunks:
        raise RuntimeError(
            f"{label} chunk grid {chunk_count} exceeds configured limit {max_chunks}"
        )


def _rewrite_problematic_native_image_arrays(
    store_root: Path,
    inspection: OMEZarrImageInspection,
) -> Optional[str]:
    """Return the rewrite problematic native image arrays.

    Inputs: `store_root` (Path), `inspection` (OMEZarrImageInspection). Output:
    `Optional[str]`.
    """
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
        safe_relative_path, path_error = _normalize_zarr_relative_path(relative_path)
        if path_error:
            return f"OME-Zarr dataset path is invalid: {path_error}"
        array_dir = store_root / safe_relative_path
        zarray_path = array_dir / ".zarray"
        if not zarray_path.is_file():
            return (
                "OME-Zarr dataset path is missing its .zarray metadata: "
                f"{safe_relative_path}"
            )

        try:
            metadata_payload = json.loads(zarray_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return (
                "Failed to read OME-Zarr array metadata for "
                f"{safe_relative_path}: {exc}"
            )

        compressor_spec = metadata_payload.get("compressor")
        if not isinstance(compressor_spec, dict):
            continue
        if str(compressor_spec.get("id") or "").strip().lower() != "blosc":
            continue

        try:
            source_codec = numcodecs.get_codec(compressor_spec)
        except Exception as exc:
            return f"Failed to load OME-Zarr compressor for {safe_relative_path}: {exc}"

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
            return (
                "Failed to update OME-Zarr compressor metadata for "
                f"{safe_relative_path}: {exc}"
            )

    return None


def _iter_zarr_chunk_files(array_dir: Path):
    """Zarr chunk files.

    Inputs: `array_dir`. Output: yielded values.
    """
    for path in sorted(array_dir.rglob("*")):
        if path.is_dir():
            continue
        if path.name.startswith("."):
            continue
        yield path


def _has_3d_pyramid_downsampling(store_root: Path) -> Optional[dict]:
    """Detect if a zarr store downsamples the z-axis between pyramid levels.

    Inputs: `store_root`. Output: `Optional[dict]`.

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

    axis_names, _, axis_error = _extract_axes(axes)
    if (
        axis_error
        or "z" not in axis_names
        or "y" not in axis_names
        or "x" not in axis_names
    ):
        return None
    z_axis_index = axis_names.index("z")
    yx_indices = [axis_names.index("y"), axis_names.index("x")]

    if not isinstance(datasets[0], dict) or not isinstance(datasets[1], dict):
        return None
    s0_path, path_error = _normalize_zarr_relative_path(datasets[0].get("path"))
    if path_error:
        return None
    s1_path, path_error = _normalize_zarr_relative_path(datasets[1].get("path"))
    if path_error:
        return None

    ndim = len(axis_names)
    s0_metadata, _ = _read_array_metadata_payload(store_root, s0_path)
    s1_metadata, _ = _read_array_metadata_payload(store_root, s1_path)
    if s0_metadata is None or s1_metadata is None:
        return None
    s0_shape, shape_error = _extract_array_shape(s0_metadata, ndim)
    if shape_error:
        return None
    s1_shape, shape_error = _extract_array_shape(s1_metadata, ndim)
    if shape_error:
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
    """Return the downscale local mean fallback.

    Inputs: `data` payload, `factors`. Output: downscale local mean fallback result.
    Raises: ValueError when validation or the called operation fails.
    """
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
    """Return the downscale local mean.

    Inputs: `data` payload, `factors`. Output: `_skimage_downscale_local_mean` result.
    """
    try:
        from skimage.transform import (
            downscale_local_mean as _skimage_downscale_local_mean,
        )
    except Exception:
        return _downscale_local_mean_fallback(data, factors)
    return _skimage_downscale_local_mean(data, factors=factors)


def _read_zarr_v2_array(array_dir: Path, metadata: dict):
    """Read the Zarr v2 array.

    Inputs: `array_dir` (Path), `metadata` (dict). Output: read Zarr v2 array result.
    Raises: RuntimeError when validation or the called operation fails.
    """
    import numpy as np

    raw_shape = metadata.get("shape")
    shape_axis_count = len(raw_shape) if isinstance(raw_shape, list) else 0
    shape, shape_error = _extract_array_shape(metadata, shape_axis_count)
    if shape_error:
        raise RuntimeError(f"invalid zarr array metadata: {shape_error}")
    chunks = _extract_positive_int_sequence(
        metadata.get("chunks"), len(shape), "chunks"
    )
    dtype_name, dtype_error = _normalize_dtype_name(metadata.get("dtype"))
    if dtype_error:
        raise RuntimeError(f"invalid zarr array metadata: {dtype_error}")
    dtype = np.dtype(dtype_name)
    _validate_native_array_bounds(shape, chunks, dtype, "native OME-Zarr")

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


def _extract_positive_int_sequence(raw_values, expected_length: int, label: str):
    """Return a positive integer tuple from JSON metadata.

    Inputs: `raw_values`, `expected_length` (int), `label` (str). Output: tuple[int].
    Raises: RuntimeError when metadata is malformed.
    """
    if not isinstance(raw_values, list) or len(raw_values) != expected_length:
        raise RuntimeError(f"{label} must match the array rank")
    values = []
    for index, raw_value in enumerate(raw_values):
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise RuntimeError(f"{label} axis index {index} must be a positive integer")
        if raw_value <= 0:
            raise RuntimeError(f"{label} axis index {index} must be a positive integer")
        values.append(raw_value)
    return tuple(values)


def _extract_translation_values(
    transforms_payload,
    axis_count: int,
) -> tuple[Optional[list[float]], Optional[str]]:
    """Return the optional translation transform from NGFF metadata.

    Inputs: `transforms_payload`, `axis_count` (int). Output: `(translation, error)`.
    """
    if not isinstance(transforms_payload, list):
        return None, "s0 coordinate transformations are malformed."
    translation_values = None
    for transform in transforms_payload:
        if not isinstance(transform, dict):
            return None, "s0 coordinate transformations are malformed."
        if transform.get("type") != "translation":
            continue
        raw_translation = transform.get("translation")
        if not isinstance(raw_translation, list) or len(raw_translation) != axis_count:
            return None, "s0 translation metadata does not match the image axes."
        values = []
        for raw_value in raw_translation:
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                return None, "s0 translation metadata must contain numeric values."
            values.append(float(raw_value))
        if translation_values is not None:
            return None, "s0 coordinate transformations contain multiple translations."
        translation_values = values
    return translation_values, None


def _regenerate_xy_only_pyramid(
    store_root: Path, downscale_factor: int = 2
) -> Optional[str]:
    """Regenerate pyramid levels so only YX axes are downsampled.

    Inputs: `store_root`, `downscale_factor`. Output: `Optional[str]`.

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

    s0_transforms = datasets[0].get("coordinateTransformations")
    s0_scale, scale_error = _extract_scale_values(
        s0_transforms,
        ndim,
        "s0",
        required=True,
    )
    if scale_error:
        return f"Cannot regenerate pyramid: {scale_error}"
    s0_translation, _ = _extract_translation_values(s0_transforms, ndim)

    try:
        s0_data = _read_zarr_v2_array(store_root / s0_path, s0_meta)
    except Exception as exc:
        return f"Failed to read full-resolution data: {exc}"

    base_factors = tuple(
        downscale_factor if i in yx_indices else 1 for i in range(ndim)
    )

    for ds in datasets[1:]:
        if not isinstance(ds, dict):
            return "Cannot regenerate pyramid: dataset metadata is malformed."
        old_path, path_error = _normalize_zarr_relative_path(ds.get("path"))
        if path_error:
            return f"Cannot regenerate pyramid: dataset path is invalid: {path_error}"
        old_dir = store_root / old_path
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

        level_path, path_error = _normalize_zarr_relative_path(
            datasets[level_idx].get("path")
        )
        if path_error:
            return f"Cannot regenerate pyramid: dataset path is invalid: {path_error}"
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
    """Write the Zarr v2 level.

    Inputs: `output_dir` (Path), `data` payload, `chunks` (list), `compressor_spec`
    (Optional[dict]), `filters_spec`, `codec`. Output: `Optional[str]`.
    """
    import numpy as np

    output_dir.mkdir(parents=True, exist_ok=True)
    shape = list(data.shape)
    ndim = len(shape)
    try:
        _validate_native_array_bounds(
            tuple(shape), tuple(chunks), data.dtype, "native OME-Zarr"
        )
    except RuntimeError as exc:
        return f"Cannot write OME-Zarr level: {exc}"

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
    """Ome Zarr runtime.

    Inputs: none. Output: `tuple[Optional[dict[str, object]], Optional[str]]`.
    """
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
