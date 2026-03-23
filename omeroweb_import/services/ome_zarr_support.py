"""OME-Zarr inspection helpers backed by the ``ome-zarr`` package."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Optional

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
    physical_sizes: dict[str, tuple[float, str]] = field(default_factory=dict)
    dtype_name: str = ""
    shape: tuple[int, ...] = ()

    @property
    def supported(self) -> bool:
        return self.recognized and self.support_error is None and bool(self.kind)


@lru_cache(maxsize=1)
def ome_zarr_package_version() -> str:
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

    assert metadata_payload is not None  # for type checkers
    if metadata_payload.get("bioformats2raw.layout") == 3:
        return _inspect_bioformats2raw_layout(store_root)

    return _inspect_single_ome_zarr_image(store_root, metadata_payload)


def normalize_native_ome_zarr_copy(store_root: Path) -> Optional[str]:
    """Normalize an ephemeral native-import copy in place.

    The installed OMERO render stack can import some valid OME-Zarr stores but
    later fail to render thumbnails when image arrays are backed by large
    Blosc-compressed chunks. Normalize only the image arrays referenced by the
    parsed OME-Zarr metadata and keep the logical image layout intact.
    """

    inspection = inspect_ome_zarr_image(store_root)
    if not inspection.supported:
        return inspection.support_error or (
            "Zarr source is not supported by the installed omero-cli-zarr runtime."
        )

    rewrite_error = _rewrite_problematic_native_image_arrays(store_root, inspection)
    if rewrite_error:
        return rewrite_error

    normalized = inspect_ome_zarr_image(store_root)
    if not normalized.supported:
        return normalized.support_error or (
            "Normalized OME-Zarr copy is no longer supported by the installed runtime."
        )
    return None


def _load_root_ome_zarr_metadata(
    store_root: Path,
) -> tuple[Optional[dict], Optional[OMEZarrImageInspection]]:
    if not store_root.is_dir():
        return None, OMEZarrImageInspection()

    metadata_payload, metadata_error = _read_store_metadata_payload(store_root)
    if metadata_payload is None:
        if metadata_error is None:
            return None, OMEZarrImageInspection()
        return None, OMEZarrImageInspection(recognized=True, support_error=metadata_error)

    if not isinstance(metadata_payload, dict):
        return None, OMEZarrImageInspection(
            recognized=True,
            support_error=f"Invalid OME-Zarr metadata payload in {store_root.name}.",
        )

    if "plate" in metadata_payload:
        return None, OMEZarrImageInspection(
            recognized=True,
            support_error="OME-Zarr plate layouts are not supported by the native image-import path.",
        )
    if "well" in metadata_payload:
        return None, OMEZarrImageInspection(
            recognized=True,
            support_error="OME-Zarr well layouts are not supported by the native image-import path.",
        )

    return metadata_payload, None


def _inspect_single_ome_zarr_image(
    store_root: Path,
    metadata_payload: dict,
) -> OMEZarrImageInspection:
    runtime, runtime_error = _ome_zarr_runtime()
    if runtime is None:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=runtime_error or "The ome-zarr Python package is not available.",
        )

    parse_url = runtime["parse_url"]
    Reader = runtime["Reader"]
    detect_format = runtime["detect_format"]
    CurrentFormat = runtime["CurrentFormat"]

    detected_format = detect_format(metadata_payload, CurrentFormat())
    format_version = getattr(detected_format, "version", None)
    zarr_format = getattr(detected_format, "zarr_format", None)

    try:
        zarr_location = parse_url(str(store_root), mode="r", fmt=detected_format)
    except Exception as exc:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=f"Failed to open OME-Zarr metadata with ome-zarr: {exc}",
            format_version=format_version,
            zarr_format=zarr_format,
        )

    if zarr_location is None:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=f"ome-zarr could not open {store_root.name}.",
            format_version=format_version,
            zarr_format=zarr_format,
        )

    try:
        nodes = list(Reader(zarr_location)())
    except Exception as exc:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=f"ome-zarr failed to read {store_root.name}: {exc}",
            format_version=format_version,
            zarr_format=zarr_format,
        )

    image_nodes = []
    for node in nodes:
        spec_names = {type(spec).__name__ for spec in getattr(node, "specs", [])}
        if "Plate" in spec_names or "Well" in spec_names:
            return OMEZarrImageInspection(
                recognized=True,
                support_error="OME-Zarr plate and well layouts are not supported by the native image-import path.",
                format_version=format_version,
                zarr_format=zarr_format,
            )
        if "Multiscales" not in spec_names:
            continue
        if not getattr(node, "data", None):
            continue
        image_nodes.append(node)

    if not image_nodes:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=(
                "OME-Zarr metadata was found, but ome-zarr did not expose a readable multiscale image node."
            ),
            format_version=format_version,
            zarr_format=zarr_format,
        )

    if len(image_nodes) != 1:
        return OMEZarrImageInspection(
            recognized=True,
            support_error="OME-Zarr store contains multiple image nodes; the native image-import path expects a single image store.",
            format_version=format_version,
            zarr_format=zarr_format,
        )

    node = image_nodes[0]
    axis_names, axis_units, axis_error = _extract_axes(node.metadata.get("axes"))
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

    physical_sizes, scale_error = _extract_physical_sizes(
        axis_names,
        axis_units,
        node.metadata.get("coordinateTransformations"),
    )
    if scale_error:
        return OMEZarrImageInspection(
            recognized=True,
            support_error=scale_error,
            format_version=format_version,
            zarr_format=zarr_format,
        )

    try:
        shape = tuple(int(value) for value in getattr(node.data[0], "shape", ()) or ())
    except Exception:
        shape = ()
    dtype_name = _normalize_dtype_name(getattr(node.data[0], "dtype", ""))
    dataset_relative_paths = _extract_dataset_relative_paths(metadata_payload)

    relative_path = None
    try:
        node_path = Path(getattr(node.zarr, "path", "") or "").resolve(strict=False)
        root_path = store_root.resolve(strict=False)
        if node_path != root_path:
            relative_path = node_path.relative_to(root_path).as_posix() or None
    except Exception:
        relative_path = None

    version_text = ome_zarr_package_version()
    details = "OME-Zarr image detected by ome-zarr"
    if version_text:
        details = f"{details} {version_text}"

    return OMEZarrImageInspection(
        recognized=True,
        kind=OME_ZARR_IMPORT_KIND_IMAGE,
        format_version=format_version,
        zarr_format=zarr_format,
        relative_path=relative_path,
        compatibility_details=details,
        image_relative_paths=dataset_relative_paths,
        physical_sizes=physical_sizes,
        dtype_name=dtype_name,
        shape=shape,
    )


def _inspect_bioformats2raw_layout(store_root: Path) -> OMEZarrImageInspection:
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
    dataset_relative_paths = []
    for series_dir in series_dirs:
        series_metadata, inspection = _load_root_ome_zarr_metadata(series_dir)
        if inspection is not None:
            error_text = inspection.support_error or "ome-zarr did not recognize this series."
            return OMEZarrImageInspection(
                recognized=True,
                support_error=f"Series {series_dir.name} is not a supported OME-Zarr image: {error_text}",
            )
        series_inspection = _inspect_single_ome_zarr_image(series_dir, series_metadata)
        if not series_inspection.supported:
            error_text = series_inspection.support_error or "ome-zarr did not recognize this series."
            return OMEZarrImageInspection(
                recognized=True,
                support_error=f"Series {series_dir.name} is not a supported OME-Zarr image: {error_text}",
            )
        if first_supported is None:
            first_supported = series_inspection
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
    )


def _read_store_metadata_payload(store_root: Path) -> tuple[Optional[dict], Optional[str]]:
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
        return None, f"Failed to read OME-Zarr metadata from {metadata_path.name}: {exc}"


def _extract_axes(axes_payload) -> tuple[list[str], dict[str, str], Optional[str]]:
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
    if not isinstance(transforms_payload, list) or not transforms_payload:
        return {}, "OME-Zarr metadata is missing coordinate transformations for the primary resolution level."

    primary_transforms = transforms_payload[0]
    if not isinstance(primary_transforms, list):
        return {}, "OME-Zarr coordinate transformations for the primary resolution level are malformed."

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
    try:
        import numpy as np

        return np.dtype(raw_dtype).name
    except Exception:
        return str(raw_dtype or "").strip()


def _native_ome_zarr_gzip_level() -> int:
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
                return f"Failed to normalize OME-Zarr chunk {chunk_path.relative_to(store_root)}: {exc}"

        metadata_payload["compressor"] = gzip_spec
        try:
            zarray_path.write_text(json.dumps(metadata_payload), encoding="utf-8")
        except OSError as exc:
            return f"Failed to update OME-Zarr compressor metadata for {relative_path}: {exc}"

    return None


def _iter_zarr_chunk_files(array_dir: Path):
    for path in sorted(array_dir.rglob("*")):
        if path.is_dir():
            continue
        if path.name.startswith("."):
            continue
        yield path


@lru_cache(maxsize=1)
def _ome_zarr_runtime() -> tuple[Optional[dict[str, object]], Optional[str]]:
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
