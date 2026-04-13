from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from omero_plugin_common.omero_helpers import get_id, get_text


logger = logging.getLogger(__name__)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_FIRST_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_NUMBER_WITH_UNIT_RE = re.compile(
    r"(?P<value>[-+]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>nm|nanometer(?:s)?|µm|um|micrometer(?:s)?|micron(?:s)?|mm|millimeter(?:s)?)?",
    re.IGNORECASE,
)
_SEARCH_TEXT_CAP = 8000
_ATTRIBUTE_TEXT_CAP = 512
_METADATA_ATTRIBUTE_CAP = 128
_ATTRIBUTE_KEY_CAP = 120


@dataclass(frozen=True)
class SearchChannel:
    channel_index: int
    label: str = ""
    excitation_nm: float | None = None
    emission_nm: float | None = None


@dataclass(frozen=True)
class SearchAttribute:
    attribute_key: str
    attribute_text: str = ""
    attribute_numeric: float | None = None


@dataclass(frozen=True)
class SearchDocument:
    acquisition_date: datetime | None = None
    instrument_manufacturer: str = ""
    instrument_model: str = ""
    objective_model: str = ""
    objective_magnification: float | None = None
    objective_na: float | None = None
    detector_model: str = ""
    detector_binning: str = ""
    detector_gain: float | None = None
    pixel_size_x_um: float | None = None
    pixel_size_y_um: float | None = None
    z_step_um: float | None = None
    search_document: str = ""
    channel_summary: str = ""
    channels: tuple[SearchChannel, ...] = ()
    attributes: tuple[SearchAttribute, ...] = ()
    raw_metadata: dict[str, str] = field(default_factory=dict)


def _normalized_key(raw_key: str) -> str:
    lowered = str(raw_key or "").strip().lower()
    if lowered.startswith("bf_"):
        lowered = lowered[3:]
    return _NON_ALNUM_RE.sub(" ", lowered).strip()


def _normalized_text(value) -> str:
    if value is None:
        return ""
    return str(get_text(value)).strip()


def _parse_datetime(value) -> datetime | None:
    raw = _normalized_text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_float(value) -> float | None:
    raw = _normalized_text(value)
    if not raw:
        return None
    match = _FIRST_NUMBER_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _unit_factor_to_um(unit: str | None) -> float | None:
    normalized = str(unit or "").strip().lower()
    if normalized in {"", "um", "µm", "micrometer", "micrometers", "micron", "microns"}:
        return 1.0
    if normalized in {"nm", "nanometer", "nanometers"}:
        return 0.001
    if normalized in {"mm", "millimeter", "millimeters"}:
        return 1000.0
    return None


def _parse_length_to_um(value) -> float | None:
    if value is None:
        return None

    try:
        raw_value = value.getValue()
    except Exception:
        raw_value = value

    try:
        raw_unit = value.getSymbol()
    except Exception:
        raw_unit = None

    if raw_unit is not None:
        factor = _unit_factor_to_um(str(raw_unit))
        numeric = _parse_float(raw_value)
        if factor is not None and numeric is not None:
            return numeric * factor

    text_value = _normalized_text(raw_value)
    if not text_value:
        return None
    match = _NUMBER_WITH_UNIT_RE.search(text_value)
    if not match:
        return _parse_float(text_value)
    factor = _unit_factor_to_um(match.group("unit"))
    if factor is None:
        return None
    return float(match.group("value")) * factor


def _canonical_field_candidate(
    metadata_pairs: Iterable[tuple[str, str]],
    *,
    include_groups: tuple[tuple[str, ...], ...],
    exclude_terms: tuple[str, ...] = (),
) -> str:
    for raw_key, raw_value in metadata_pairs:
        normalized_key = _normalized_key(raw_key)
        if not normalized_key or not raw_value:
            continue
        if any(excluded in normalized_key for excluded in exclude_terms):
            continue
        if all(any(term in normalized_key for term in group) for group in include_groups):
            return _normalized_text(raw_value)
    return ""


def _canonical_numeric_candidate(
    metadata_pairs: Iterable[tuple[str, str]],
    *,
    include_groups: tuple[tuple[str, ...], ...],
    convert_um: bool = False,
    exclude_terms: tuple[str, ...] = (),
) -> float | None:
    raw_text = _canonical_field_candidate(
        metadata_pairs,
        include_groups=include_groups,
        exclude_terms=exclude_terms,
    )
    if not raw_text:
        return None
    if convert_um:
        return _parse_length_to_um(raw_text)
    return _parse_float(raw_text)


def _safe_channel_value(channel, attr_name: str):
    getter = getattr(channel, attr_name, None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        logger.debug("Channel getter %s failed.", attr_name, exc_info=True)
        return None


def _safe_details_value(obj, attr_name: str):
    getter = getattr(obj, attr_name, None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        logger.debug("Object getter %s failed.", attr_name, exc_info=True)
        return None


def _collect_original_metadata(image) -> dict[str, str]:
    try:
        payload = image.loadOriginalMetadata()
    except Exception:
        logger.debug("Original metadata loading failed.", exc_info=True)
        return {}

    if not payload:
        return {}

    global_metadata = []
    series_metadata = []
    try:
        if len(payload) > 1 and payload[1]:
            global_metadata = list(payload[1])
    except Exception:
        logger.debug("Original metadata global section failed.", exc_info=True)
    try:
        if len(payload) > 2 and payload[2]:
            series_metadata = list(payload[2])
    except Exception:
        logger.debug("Original metadata series section failed.", exc_info=True)

    metadata: dict[str, str] = {}
    for entry in list(global_metadata) + list(series_metadata):
        try:
            if len(entry) < 2:
                continue
            key = _normalized_text(entry[0])
            value = _normalized_text(entry[1])
        except Exception:
            logger.debug("Original metadata entry parsing failed.", exc_info=True)
            continue
        if key and value and key not in metadata:
            metadata[f"BF_{key}"] = value
    return metadata


def _collect_channels(image) -> tuple[SearchChannel, ...]:
    channels: list[SearchChannel] = []
    try:
        raw_channels = list(image.getChannels())
    except Exception:
        logger.debug("Channel collection failed.", exc_info=True)
        raw_channels = []

    for index, channel in enumerate(raw_channels):
        raw_idx = _safe_channel_value(channel, "getIndex")
        try:
            channel_index = int(get_text(raw_idx)) if raw_idx is not None else index
        except Exception:
            channel_index = index
        channels.append(
            SearchChannel(
                channel_index=channel_index,
                label=_normalized_text(_safe_channel_value(channel, "getLabel")),
                excitation_nm=_parse_float(
                    _safe_channel_value(channel, "getExcitationWave")
                ),
                emission_nm=_parse_float(_safe_channel_value(channel, "getEmissionWave")),
            )
        )
    return tuple(channels)


def _channel_summary(channels: Iterable[SearchChannel]) -> str:
    parts = []
    for channel in channels:
        channel_bits = []
        if channel.label:
            channel_bits.append(channel.label)
        if channel.excitation_nm is not None:
            channel_bits.append(f"Ex {channel.excitation_nm:g} nm")
        if channel.emission_nm is not None:
            channel_bits.append(f"Em {channel.emission_nm:g} nm")
        if channel_bits:
            parts.append(" / ".join(channel_bits))
    return "; ".join(parts)


def _extract_dataset_project_context(image) -> tuple[int | None, str, int | None, str]:
    dataset_id = None
    dataset_name = ""
    project_id = None
    project_name = ""

    try:
        parents = list(image.listParents())
    except Exception:
        logger.debug("Image parent listing failed.", exc_info=True)
        parents = []

    if parents:
        dataset = parents[0]
        dataset_id = get_id(dataset)
        dataset_name = _normalized_text(_safe_details_value(dataset, "getName"))
        try:
            project_parents = list(dataset.listParents())
        except Exception:
            logger.debug("Dataset parent listing failed.", exc_info=True)
            project_parents = []
        if project_parents:
            project = project_parents[0]
            project_id = get_id(project)
            project_name = _normalized_text(_safe_details_value(project, "getName"))

    try:
        return (
            int(dataset_id) if dataset_id is not None else None,
            dataset_name,
            int(project_id) if project_id is not None else None,
            project_name,
        )
    except Exception:
        return dataset_id, dataset_name, project_id, project_name


def _attribute_key(raw_key: str) -> str:
    normalized = _normalized_key(raw_key).replace(" ", "_").strip("_")
    return normalized[:_ATTRIBUTE_KEY_CAP]


def _append_attribute(
    bucket: dict[str, SearchAttribute],
    attribute: SearchAttribute,
) -> None:
    if not attribute.attribute_key:
        return
    if (
        not attribute.attribute_text
        and attribute.attribute_numeric is None
    ):
        return
    bucket.setdefault(attribute.attribute_key, attribute)


def _metadata_attributes(original_metadata: dict[str, str]) -> tuple[SearchAttribute, ...]:
    attributes: list[SearchAttribute] = []
    seen: set[str] = set()
    for raw_key, raw_value in original_metadata.items():
        attribute_key = _attribute_key(raw_key)
        if not attribute_key or attribute_key in seen:
            continue
        seen.add(attribute_key)
        text_value = _normalized_text(raw_value)[:_ATTRIBUTE_TEXT_CAP]
        if not text_value:
            continue
        attributes.append(
            SearchAttribute(
                attribute_key=attribute_key,
                attribute_text=text_value,
                attribute_numeric=_parse_float(text_value),
            )
        )
        if len(attributes) >= _METADATA_ATTRIBUTE_CAP:
            break
    return tuple(attributes)


def _build_search_text(parts: Iterable[str]) -> str:
    text = " ".join(part for part in parts if part).strip()
    if len(text) <= _SEARCH_TEXT_CAP:
        return text
    return text[:_SEARCH_TEXT_CAP].rsplit(" ", 1)[0].strip()


def extract_search_document(image) -> tuple[SearchDocument, dict[str, int | str | None]]:
    original_metadata = _collect_original_metadata(image)
    metadata_pairs = tuple(original_metadata.items())
    channels = _collect_channels(image)

    acquisition_date = None
    try:
        acquisition_date = _parse_datetime(image.getAcquisitionDate())
    except Exception:
        logger.debug("Acquisition date extraction failed.", exc_info=True)

    objective_settings = None
    try:
        objective_settings = image.getObjectiveSettings()
    except Exception:
        logger.debug("Objective settings extraction failed.", exc_info=True)

    detector_settings = []
    try:
        detector_settings = list(image.getDetectorSettings() or [])
    except Exception:
        logger.debug("Detector settings extraction failed.", exc_info=True)

    objective_collar = None
    objective_id = None
    if objective_settings is not None:
        objective_collar = _parse_float(
            _safe_details_value(objective_settings, "getCorrectionCollar")
        )
        objective_id = _normalized_text(_safe_details_value(objective_settings, "getID"))

    detector_binning = ""
    detector_gain = None
    if detector_settings:
        detector_binning = _normalized_text(
            _safe_details_value(detector_settings[0], "getBinning")
        )
        detector_gain = _parse_float(_safe_details_value(detector_settings[0], "getGain"))

    pixel_size_x_um = None
    pixel_size_y_um = None
    pixel_size_z_um = None
    for axis_name, attr_name in (
        ("x", "getPixelSizeX"),
        ("y", "getPixelSizeY"),
        ("z", "getPixelSizeZ"),
    ):
        getter = getattr(image, attr_name, None)
        if not callable(getter):
            continue
        try:
            value = getter(units=True)
        except TypeError:
            try:
                value = getter()
            except Exception:
                logger.debug("Pixel size getter %s failed.", attr_name, exc_info=True)
                continue
        except Exception:
            logger.debug("Pixel size getter %s failed.", attr_name, exc_info=True)
            continue
        converted = _parse_length_to_um(value)
        if axis_name == "x":
            pixel_size_x_um = converted
        elif axis_name == "y":
            pixel_size_y_um = converted
        else:
            pixel_size_z_um = converted

    instrument_manufacturer = _canonical_field_candidate(
        metadata_pairs,
        include_groups=(
            ("instrument", "microscope", "system"),
            ("manufacturer", "vendor", "make"),
        ),
    )
    instrument_model = _canonical_field_candidate(
        metadata_pairs,
        include_groups=(("instrument", "microscope", "system"), ("model",)),
    )
    objective_model = _canonical_field_candidate(
        metadata_pairs,
        include_groups=(("objective",), ("model", "name")),
        exclude_terms=("settings",),
    )
    objective_magnification = _canonical_numeric_candidate(
        metadata_pairs,
        include_groups=(
            ("objective",),
            ("magnification", "nominal mag", "nominal magnification", "mag"),
        ),
    )
    objective_na = _canonical_numeric_candidate(
        metadata_pairs,
        include_groups=(("objective",), ("na", "numerical aperture")),
    )
    detector_model = _canonical_field_candidate(
        metadata_pairs,
        include_groups=(("detector", "camera", "sensor"), ("model", "name")),
    )
    laser_line_nm = _canonical_numeric_candidate(
        metadata_pairs,
        include_groups=(("laser",), ("line", "wavelength")),
    )

    attribute_map: dict[str, SearchAttribute] = {}
    for attribute in _metadata_attributes(original_metadata):
        _append_attribute(attribute_map, attribute)
    for attribute in (
        SearchAttribute("objective_collar", attribute_numeric=objective_collar),
        SearchAttribute("objective_id", attribute_text=objective_id),
        SearchAttribute("detector_binning", attribute_text=detector_binning),
        SearchAttribute("detector_gain", attribute_numeric=detector_gain),
        SearchAttribute("laser_line_nm", attribute_numeric=laser_line_nm),
    ):
        _append_attribute(attribute_map, attribute)
    attributes = tuple(attribute_map.values())

    scope_context = _extract_dataset_project_context(image)
    search_text_parts = [
        _normalized_text(_safe_details_value(image, "getName")),
        scope_context[1],
        scope_context[3],
        instrument_manufacturer,
        instrument_model,
        objective_model,
        detector_model,
        detector_binning,
        _channel_summary(channels),
    ]
    for attribute in attributes[:48]:
        search_text_parts.append(attribute.attribute_key.replace("_", " "))
        if attribute.attribute_text:
            search_text_parts.append(attribute.attribute_text)
        elif attribute.attribute_numeric is not None:
            search_text_parts.append(f"{attribute.attribute_numeric:g}")

    document = SearchDocument(
        acquisition_date=acquisition_date,
        instrument_manufacturer=instrument_manufacturer,
        instrument_model=instrument_model,
        objective_model=objective_model,
        objective_magnification=objective_magnification,
        objective_na=objective_na,
        detector_model=detector_model,
        detector_binning=detector_binning,
        detector_gain=detector_gain,
        pixel_size_x_um=pixel_size_x_um,
        pixel_size_y_um=pixel_size_y_um,
        z_step_um=pixel_size_z_um,
        search_document=_build_search_text(search_text_parts),
        channel_summary=_channel_summary(channels),
        channels=channels,
        attributes=attributes,
        raw_metadata=original_metadata,
    )
    return document, {
        "dataset_id": scope_context[0],
        "dataset_name": scope_context[1],
        "project_id": scope_context[2],
        "project_name": scope_context[3],
    }
