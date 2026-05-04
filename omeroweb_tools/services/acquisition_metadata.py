from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from inspect import signature
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
_SEARCH_TEXT_CAP = 64000
_ATTRIBUTE_KEY_CAP = 120


@dataclass(frozen=True)
class SearchChannel:
    """Represent search channel."""

    channel_index: int
    label: str = ""
    excitation_nm: float | None = None
    emission_nm: float | None = None


@dataclass(frozen=True)
class SearchAttribute:
    """Represent search attribute."""

    attribute_key: str
    attribute_text: str = ""
    attribute_numeric: float | None = None


@dataclass(frozen=True)
class SearchDocument:
    """Represent search document."""

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
    """Normalized key.

    Inputs: `raw_key`. Output: `str`.
    """
    lowered = str(raw_key or "").strip().lower()
    if lowered.startswith("bf_"):
        lowered = lowered[3:]
    return _NON_ALNUM_RE.sub(" ", lowered).strip()


def _metadata_key_is_indexable(raw_key: str) -> bool:
    """Metadata key is indexable.

    Inputs: `raw_key`. Output: `bool`.
    """
    return bool(_normalized_key(raw_key))


def _normalized_text(value) -> str:
    """Normalized text.

    Inputs: `value`. Output: `str`.
    """
    if value is None:
        return ""
    return str(get_text(value)).strip()


def _is_scalar_index_value(value) -> bool:
    """Return whether scalar index value.

    Inputs: `value`. Output: `bool`.
    """
    return isinstance(value, str | int | float | bool | datetime)


def _scalar_text(value) -> str:
    """Scalar text.

    Inputs: `value`. Output: `str`.
    """
    if value is None:
        return ""

    try:
        raw_value = value.getValue()
    except Exception:
        raw_value = value

    if hasattr(raw_value, "value") and _is_scalar_index_value(raw_value.value):
        raw_value = raw_value.value

    if not _is_scalar_index_value(raw_value):
        return ""

    text = _normalized_text(raw_value)
    if not text or text == "N/A":
        return ""

    try:
        symbol = value.getSymbol()
    except Exception:
        symbol = None
    if symbol:
        symbol_text = _normalized_text(symbol)
        if symbol_text and symbol_text not in text:
            text = f"{text} {symbol_text}"
    return text


def _parse_datetime(value) -> datetime | None:
    """Parse datetime.

    Inputs: `value`. Output: `datetime | None`.
    """
    raw = _normalized_text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_float(value) -> float | None:
    """Parse float.

    Inputs: `value`. Output: `float | None`.
    """
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
    """Unit factor to um.

    Inputs: `unit`. Output: `float | None`.
    """
    normalized = str(unit or "").strip().lower()
    if normalized in {"", "um", "µm", "micrometer", "micrometers", "micron", "microns"}:
        return 1.0
    if normalized in {"nm", "nanometer", "nanometers"}:
        return 0.001
    if normalized in {"mm", "millimeter", "millimeters"}:
        return 1000.0
    return None


def _parse_length_to_um(value) -> float | None:
    """Parse length to um.

    Inputs: `value`. Output: `float | None`.
    """
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
    """Canonical field candidate.

    Inputs: `metadata_pairs`, `include_groups`, `exclude_terms`. Output: `str`.
    """
    for raw_key, raw_value in metadata_pairs:
        normalized_key = _normalized_key(raw_key)
        if not normalized_key or not raw_value:
            continue
        if any(excluded in normalized_key for excluded in exclude_terms):
            continue
        if all(
            any(term in normalized_key for term in group) for group in include_groups
        ):
            return _normalized_text(raw_value)
    return ""


def _canonical_numeric_candidate(
    metadata_pairs: Iterable[tuple[str, str]],
    *,
    include_groups: tuple[tuple[str, ...], ...],
    convert_um: bool = False,
    exclude_terms: tuple[str, ...] = (),
) -> float | None:
    """Canonical numeric candidate.

    Inputs: `metadata_pairs`, `include_groups`, `convert_um`, `exclude_terms`. Output:
    `float | None`.
    """
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
    """Return safe channel value.

    Inputs: `channel`, `attr_name`. Output: `getter` result or None.
    """
    getter = getattr(channel, attr_name, None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        logger.debug("Channel getter %s failed.", attr_name, exc_info=True)
        return None


def _safe_details_value(obj, attr_name: str):
    """Return safe details value.

    Inputs: `obj`, `attr_name`. Output: `getter` result or None.
    """
    getter = getattr(obj, attr_name, None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        logger.debug("Object getter %s failed.", attr_name, exc_info=True)
        return None


def _collect_original_metadata(image) -> dict[str, str]:
    """Collect original metadata.

    Inputs: `image`. Output: `dict[str, str]`.
    """
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
        if key and value and _metadata_key_is_indexable(key):
            metadata_key = f"BF_{key}"
            metadata[metadata_key] = _merge_index_text(
                metadata.get(metadata_key, ""),
                value,
            )
    return metadata


def _collect_channels(image) -> tuple[SearchChannel, ...]:
    """Collect channels.

    Inputs: `image`. Output: `tuple[SearchChannel, ...]`.
    """
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
                emission_nm=_parse_float(
                    _safe_channel_value(channel, "getEmissionWave")
                ),
            )
        )
    return tuple(channels)


def _channel_summary(channels: Iterable[SearchChannel]) -> str:
    """Channel summary.

    Inputs: `channels`. Output: `str`.
    """
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
    """Extract dataset project context.

    Inputs: `image`. Output: `tuple[int | None, str, int | None, str]`.
    """
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
    """Attribute key.

    Inputs: `raw_key`. Output: `str`.
    """
    normalized = _normalized_key(raw_key).replace(" ", "_").strip("_")
    return normalized[:_ATTRIBUTE_KEY_CAP]


def _merge_index_text(existing: str, incoming: str) -> str:
    """Merge index text.

    Inputs: `existing`, `incoming`. Output: `str`.
    """
    existing_text = _normalized_text(existing)
    incoming_text = _normalized_text(incoming)
    if not existing_text:
        return incoming_text
    if not incoming_text or incoming_text in existing_text.split("; "):
        return existing_text
    return f"{existing_text}; {incoming_text}"


def _append_attribute(
    bucket: dict[str, SearchAttribute],
    attribute: SearchAttribute,
) -> None:
    """Append attribute.

    Inputs: `bucket`, `attribute`. Output: None.
    """
    if not attribute.attribute_key:
        return
    if not attribute.attribute_text and attribute.attribute_numeric is None:
        return
    existing = bucket.get(attribute.attribute_key)
    if existing is None:
        bucket[attribute.attribute_key] = attribute
        return
    merged_text = _merge_index_text(existing.attribute_text, attribute.attribute_text)
    bucket[attribute.attribute_key] = SearchAttribute(
        attribute_key=existing.attribute_key,
        attribute_text=merged_text,
        attribute_numeric=(
            existing.attribute_numeric
            if existing.attribute_numeric is not None
            else attribute.attribute_numeric
        ),
    )


def _metadata_attributes(
    original_metadata: dict[str, str],
) -> tuple[SearchAttribute, ...]:
    """Metadata attributes.

    Inputs: `original_metadata`. Output: `tuple[SearchAttribute, ...]`.
    """
    attributes: list[SearchAttribute] = []
    seen: set[str] = set()
    for raw_key, raw_value in original_metadata.items():
        if not _metadata_key_is_indexable(raw_key):
            continue
        attribute_key = _attribute_key(raw_key)
        if not attribute_key or attribute_key in seen:
            continue
        seen.add(attribute_key)
        text_value = _normalized_text(raw_value)
        if not text_value:
            continue
        attributes.append(
            SearchAttribute(
                attribute_key=attribute_key,
                attribute_text=text_value,
                attribute_numeric=_parse_float(text_value),
            )
        )
    return tuple(attributes)


def _quantity_to_float(value) -> float | None:
    """Quantity to float.

    Inputs: `value`. Output: `float | None`.
    """
    if value is None:
        return None
    try:
        raw_value = value.getValue()
    except Exception:
        raw_value = value
    return _parse_float(raw_value)


def _plane_quantity(
    plane_info, getter_name: str, *, units: str | None = None
) -> float | None:
    """Plane quantity.

    Inputs: `plane_info`, `getter_name`, `units`. Output: `float | None`.
    """
    getter = getattr(plane_info, getter_name, None)
    if not callable(getter):
        return None
    try:
        if units is None:
            return _quantity_to_float(getter())
        return _quantity_to_float(getter(units=units))
    except TypeError:
        try:
            return _quantity_to_float(getter())
        except Exception:
            logger.debug("PlaneInfo getter %s failed.", getter_name, exc_info=True)
            return None
    except Exception:
        logger.debug("PlaneInfo getter %s failed.", getter_name, exc_info=True)
        return None


def _plane_time_index(plane_info, sequence_index: int) -> int:
    """Plane time index.

    Inputs: `plane_info`, `sequence_index`. Output: `int`.
    """
    value = _plane_axis_index(plane_info, "theT")
    return sequence_index if value is None else value


def _plane_axis_index(plane_info, attr_name: str) -> int | None:
    """Plane axis index.

    Inputs: `plane_info`, `attr_name`. Output: `int | None`.
    """
    raw_value = getattr(plane_info, attr_name, None)
    if raw_value is None:
        getter = getattr(
            plane_info,
            f"get{attr_name[:1].upper()}{attr_name[1:]}",
            None,
        )
        if callable(getter):
            try:
                raw_value = getter()
            except Exception:
                raw_value = None
    try:
        return int(get_text(raw_value))
    except Exception:
        return None


def _callable_accepts_no_args(func) -> bool:
    """Callable accepts no args.

    Inputs: `func`. Output: `bool`.
    """
    try:
        signature(func).bind()
    except TypeError:
        return False
    except (ValueError, AttributeError):
        return True
    return True


def _seconds_text(value: float) -> str:
    """Seconds text.

    Inputs: `value`. Output: `str`.
    """
    return f"{value} seconds"


def _attribute_from_text(key: str, value: str) -> SearchAttribute | None:
    """Attribute from text.

    Inputs: `key`, `value`. Output: `SearchAttribute | None`.
    """
    attribute_key = _attribute_key(key)
    attribute_text = _normalized_text(value)
    if not attribute_key or not attribute_text:
        return None
    return SearchAttribute(
        attribute_key=attribute_key,
        attribute_text=attribute_text,
        attribute_numeric=_parse_float(attribute_text),
    )


def _append_text_attribute(
    bucket: dict[str, SearchAttribute],
    key: str,
    value,
    *,
    trust_generated_key: bool = True,
) -> None:
    """Append text attribute.

    Inputs: `bucket`, `key`, `value`, `trust_generated_key`. Output: None.
    """
    if not trust_generated_key and not _metadata_key_is_indexable(key):
        return
    text_value = _scalar_text(value)
    if not text_value:
        return
    attribute = _attribute_from_text(key, text_value)
    if attribute is not None:
        _append_attribute(bucket, attribute)


def _annotation_value_pairs(annotation) -> Iterable[tuple[str, str]]:
    """Annotation value pairs.

    Inputs: `annotation`. Output: `Iterable[tuple[str, str]]`.
    """
    annotation_type = str(
        getattr(annotation, "OMERO_CLASS", annotation.__class__.__name__)
        or annotation.__class__.__name__
    )
    normalized_type = _attribute_key(annotation_type) or "annotation"

    if "map" in normalized_type:
        values = None
        for getter_name in ("getValue", "getMapValue"):
            getter = getattr(annotation, getter_name, None)
            if callable(getter):
                try:
                    values = getter()
                    break
                except Exception:
                    logger.debug("Map annotation value loading failed.", exc_info=True)
        for entry in values or ():
            key = getattr(entry, "name", None)
            value = getattr(entry, "value", None)
            if key is None:
                getter = getattr(entry, "getName", None)
                if callable(getter):
                    try:
                        key = getter()
                    except Exception:
                        key = None
            if value is None:
                getter = getattr(entry, "getValue", None)
                if callable(getter):
                    try:
                        value = getter()
                    except Exception:
                        value = None
            key_text = _scalar_text(key)
            value_text = _scalar_text(value)
            if key_text and value_text:
                yield f"annotation_map_{key_text}", value_text
        return

    for getter_name, label in (
        ("getTextValue", normalized_type),
        ("getDescription", f"{normalized_type}_description"),
        ("getFileName", f"{normalized_type}_file_name"),
        ("getFileSize", f"{normalized_type}_file_size"),
        ("getNs", f"{normalized_type}_namespace"),
    ):
        getter = getattr(annotation, getter_name, None)
        if not callable(getter):
            continue
        try:
            value_text = _scalar_text(getter())
        except Exception:
            logger.debug(
                "Annotation getter %s failed.",
                getter_name,
                exc_info=True,
            )
            continue
        if value_text:
            yield label, value_text


def _collect_annotation_attributes(image) -> tuple[SearchAttribute, ...]:
    """Collect annotation attributes.

    Inputs: `image`. Output: `tuple[SearchAttribute, ...]`.
    """
    try:
        annotations = list(image.listAnnotations())
    except Exception:
        logger.debug("Image annotation loading failed.", exc_info=True)
        return ()

    bucket: dict[str, SearchAttribute] = {}
    for annotation in annotations:
        for raw_key, raw_value in _annotation_value_pairs(annotation):
            _append_text_attribute(
                bucket,
                raw_key,
                raw_value,
                trust_generated_key=False,
            )
    return tuple(bucket.values())


def _safe_call(obj, getter_name: str, *args, **kwargs):
    """Return safe call.

    Inputs: `obj`, `getter_name`, `*args`, `**kwargs`. Output: `getter` result or None.
    """
    getter = getattr(obj, getter_name, None)
    if not callable(getter):
        return None
    try:
        return getter(*args, **kwargs)
    except Exception:
        logger.debug("OMERO metadata getter %s failed.", getter_name, exc_info=True)
        return None


def _safe_iter_call(obj, getter_name: str) -> tuple:
    """Return safe iter call.

    Inputs: `obj`, `getter_name`. Output: `tuple`.
    """
    value = _safe_call(obj, getter_name)
    if value is None:
        return ()
    try:
        return tuple(value)
    except TypeError:
        return (value,)
    except Exception:
        logger.debug("OMERO metadata iterator %s failed.", getter_name, exc_info=True)
        return ()


def _append_named_fields(
    bucket: dict[str, SearchAttribute],
    prefix: str,
    obj,
    field_names: tuple[str, ...],
) -> None:
    """Append named fields.

    Inputs: `bucket`, `prefix`, `obj`, `field_names`. Output: None.
    """
    for field_name in field_names:
        value = None
        try:
            value = getattr(obj, field_name)
        except Exception:
            value = None
        if value is None:
            getter_name = f"get{field_name[:1].upper()}{field_name[1:]}"
            value = _safe_call(obj, getter_name)
        _append_text_attribute(bucket, f"{prefix}_{field_name}", value)


def _append_getter_fields(
    bucket: dict[str, SearchAttribute],
    prefix: str,
    obj,
    getters: tuple[tuple[str, str], ...],
) -> None:
    """Append getter fields.

    Inputs: `bucket`, `prefix`, `obj`, `getters`. Output: None.
    """
    for getter_name, label in getters:
        value = _safe_call(obj, getter_name)
        _append_text_attribute(bucket, f"{prefix}_{label}", value)


def _append_fileset_attributes(
    bucket: dict[str, SearchAttribute],
    image,
) -> None:
    """Append fileset attributes.

    Inputs: `bucket`, `image`. Output: None.
    """
    fileset = _safe_call(image, "getFileset")
    if fileset is None:
        return
    for index, used_file in enumerate(_safe_iter_call(fileset, "copyUsedFiles")):
        original_file = _safe_call(used_file, "getOriginalFile") or used_file
        prefix = f"original_file_{index + 1}"
        _append_getter_fields(
            bucket,
            prefix,
            original_file,
            (
                ("getName", "name"),
                ("getMimetype", "mimetype"),
                ("getSize", "size"),
            ),
        )


def _pixel_axis_size(pixels, getter_name: str, default_size: int) -> int:
    """Pixel axis size.

    Inputs: `pixels`, `getter_name`, `default_size`. Output: `int`.
    """
    value = _safe_call(pixels, getter_name)
    try:
        return max(1, int(get_text(value)))
    except Exception:
        return default_size


def _collect_universal_metadata_attributes(
    image,
    channels: tuple[SearchChannel, ...],
    context: dict[str, int | str | None],
) -> tuple[SearchAttribute, ...]:
    """Collect universal metadata attributes.

    Inputs: `image`, `channels`, `context`. Output: `tuple[SearchAttribute, ...]`.
    """
    bucket: dict[str, SearchAttribute] = {}
    _append_text_attribute(bucket, "image_name", _safe_details_value(image, "getName"))
    _append_text_attribute(
        bucket,
        "image_description",
        _safe_details_value(image, "getDescription"),
    )
    _append_text_attribute(
        bucket,
        "image_acquisition_date",
        _safe_details_value(image, "getAcquisitionDate"),
    )
    _append_text_attribute(bucket, "dataset_name", context.get("dataset_name"))
    _append_text_attribute(bucket, "project_name", context.get("project_name"))

    pixels = _safe_call(image, "getPrimaryPixels")
    if pixels is not None:
        _append_getter_fields(
            bucket,
            "pixels",
            pixels,
            (
                ("getSizeX", "size_x"),
                ("getSizeY", "size_y"),
                ("getSizeZ", "size_z"),
                ("getSizeC", "size_c"),
                ("getSizeT", "size_t"),
                ("getPhysicalSizeX", "physical_size_x"),
                ("getPhysicalSizeY", "physical_size_y"),
                ("getPhysicalSizeZ", "physical_size_z"),
            ),
        )

    objective_settings = _safe_call(image, "getObjectiveSettings")
    if objective_settings is not None:
        _append_named_fields(
            bucket,
            "objective_settings",
            objective_settings,
            ("correctionCollar", "refractiveIndex"),
        )
        _append_getter_fields(
            bucket,
            "objective_settings",
            objective_settings,
            (("getMedium", "medium"),),
        )
        objective = _safe_call(objective_settings, "getObjective")
        if objective is not None:
            _append_named_fields(
                bucket,
                "objective_settings_objective",
                objective,
                (
                    "manufacturer",
                    "model",
                    "serialNumber",
                    "lotNumber",
                    "nominalMagnification",
                    "calibratedMagnification",
                    "lensNA",
                    "workingDistance",
                ),
            )
            _append_getter_fields(
                bucket,
                "objective_settings_objective",
                objective,
                (
                    ("getImmersion", "immersion"),
                    ("getCorrection", "correction"),
                ),
            )

    environment = _safe_call(image, "getImagingEnvironment")
    if environment is not None:
        _append_named_fields(
            bucket,
            "imaging_environment",
            environment,
            ("temperature", "airPressure", "humidity", "co2percent"),
        )

    stage_label = _safe_call(image, "getStageLabel")
    if stage_label is not None:
        _append_named_fields(
            bucket, "stage_label", stage_label, ("name", "x", "y", "z")
        )

    instrument = _safe_call(image, "getInstrument")
    if instrument is not None:
        microscope = _safe_call(instrument, "getMicroscope")
        if microscope is not None:
            _append_named_fields(
                bucket,
                "microscope",
                microscope,
                ("manufacturer", "model", "serialNumber", "lotNumber"),
            )
            _append_getter_fields(
                bucket,
                "microscope",
                microscope,
                (("getMicroscopeType", "type"),),
            )
        for name, collection_getter_name, fields in (
            (
                "instrument_objective",
                "getObjectives",
                (
                    "manufacturer",
                    "model",
                    "serialNumber",
                    "lotNumber",
                    "nominalMagnification",
                    "calibratedMagnification",
                    "lensNA",
                    "workingDistance",
                ),
            ),
            (
                "instrument_filter",
                "getFilters",
                ("manufacturer", "model", "serialNumber", "lotNumber"),
            ),
            (
                "instrument_dichroic",
                "getDichroics",
                ("manufacturer", "model", "serialNumber", "lotNumber"),
            ),
            (
                "instrument_detector",
                "getDetectors",
                (
                    "manufacturer",
                    "model",
                    "serialNumber",
                    "lotNumber",
                    "gain",
                    "voltage",
                    "offsetValue",
                    "zoom",
                    "amplificationGain",
                ),
            ),
            (
                "instrument_light_source",
                "getLightSources",
                ("manufacturer", "model", "serialNumber", "lotNumber", "power"),
            ),
        ):
            for index, obj in enumerate(
                _safe_iter_call(instrument, collection_getter_name)
            ):
                _append_named_fields(bucket, f"{name}_{index + 1}", obj, fields)

    try:
        raw_channels = list(image.getChannels())
    except Exception:
        raw_channels = []
    for channel_position, raw_channel in enumerate(raw_channels):
        channel_index = (
            channels[channel_position].channel_index
            if channel_position < len(channels)
            else channel_position
        )
        channel_prefix = f"channel_{channel_index}"
        logical_channel = _safe_call(raw_channel, "getLogicalChannel")
        if logical_channel is not None:
            _append_named_fields(
                bucket,
                channel_prefix,
                logical_channel,
                (
                    "name",
                    "fluor",
                    "ndFilter",
                    "pinHoleSize",
                    "pockelCellSetting",
                ),
            )
            _append_getter_fields(
                bucket,
                channel_prefix,
                logical_channel,
                (
                    ("getIllumination", "illumination"),
                    ("getContrastMethod", "contrast_method"),
                    ("getMode", "mode"),
                ),
            )
            detector_settings = _safe_call(logical_channel, "getDetectorSettings")
            if detector_settings is not None:
                _append_named_fields(
                    bucket,
                    f"{channel_prefix}_detector_settings",
                    detector_settings,
                    ("gain", "offsetValue", "readOutRate", "voltage", "zoom"),
                )
                _append_getter_fields(
                    bucket,
                    f"{channel_prefix}_detector_settings",
                    detector_settings,
                    (("getBinning", "binning"),),
                )
                detector = _safe_call(detector_settings, "getDetector")
                if detector is not None:
                    _append_named_fields(
                        bucket,
                        f"{channel_prefix}_detector",
                        detector,
                        ("manufacturer", "model", "serialNumber", "lotNumber"),
                    )
            light_source_settings = _safe_call(
                logical_channel, "getLightSourceSettings"
            )
            if light_source_settings is not None:
                _append_named_fields(
                    bucket,
                    f"{channel_prefix}_light_source_settings",
                    light_source_settings,
                    ("attenuation", "wavelength"),
                )
                light_source = _safe_call(light_source_settings, "getLightSource")
                if light_source is not None:
                    _append_named_fields(
                        bucket,
                        f"{channel_prefix}_light_source",
                        light_source,
                        ("manufacturer", "model", "serialNumber", "lotNumber"),
                    )
            light_path = _safe_call(logical_channel, "getLightPath")
            if light_path is not None:
                dichroic = _safe_call(light_path, "getDichroic")
                if dichroic is not None:
                    _append_named_fields(
                        bucket,
                        f"{channel_prefix}_dichroic",
                        dichroic,
                        ("manufacturer", "model", "serialNumber", "lotNumber"),
                    )
                for filter_label, filter_getter_name in (
                    ("emission_filter", "getEmissionFilters"),
                    ("excitation_filter", "getExcitationFilters"),
                ):
                    for filter_index, filter_obj in enumerate(
                        _safe_iter_call(light_path, filter_getter_name)
                    ):
                        _append_named_fields(
                            bucket,
                            f"{channel_prefix}_{filter_label}_{filter_index + 1}",
                            filter_obj,
                            ("manufacturer", "model", "serialNumber", "lotNumber"),
                        )
    _append_fileset_attributes(bucket, image)

    for attribute in _collect_annotation_attributes(image):
        _append_attribute(bucket, attribute)
    return tuple(bucket.values())


def _collect_all_plane_info_attributes(
    image,
    channels: tuple[SearchChannel, ...],
) -> tuple[SearchAttribute, ...]:
    """Collect all plane info attributes.

    Inputs: `image`, `channels`. Output: `tuple[SearchAttribute, ...]`.
    """
    try:
        pixels = image.getPrimaryPixels()
    except Exception:
        logger.debug("Primary pixels lookup failed.", exc_info=True)
        return ()
    copy_plane_info = getattr(pixels, "copyPlaneInfo", None)
    if not callable(copy_plane_info):
        return ()

    size_z = _pixel_axis_size(pixels, "getSizeZ", 1)
    size_c = max(
        _pixel_axis_size(pixels, "getSizeC", len(channels) or 1),
        len(channels),
    )
    channel_indices = {
        position: (
            channels[position].channel_index if position < len(channels) else position
        )
        for position in range(size_c)
    }

    if not _callable_accepts_no_args(copy_plane_info):
        return _collect_plane_info_attributes_by_plane(
            copy_plane_info,
            channel_indices,
            size_z,
        )

    try:
        plane_infos = tuple(copy_plane_info())
    except TypeError:
        return _collect_plane_info_attributes_by_plane(
            copy_plane_info,
            channel_indices,
            size_z,
        )
    except Exception:
        logger.debug("Bulk PlaneInfo collection failed.", exc_info=True)
        return ()

    grouped: dict[tuple[int, int], list] = {}
    for plane_info in plane_infos:
        channel_position = _plane_axis_index(plane_info, "theC")
        z_index = _plane_axis_index(plane_info, "theZ")
        if channel_position is None or z_index is None:
            continue
        group_key = (channel_position, z_index)
        grouped.setdefault(group_key, []).append(plane_info)

    attributes: list[SearchAttribute] = []
    for channel_position, z_index in sorted(grouped):
        channel_index = channel_indices.get(channel_position, channel_position)
        prefix = f"channel_{channel_index}_z{z_index + 1}"
        attributes.extend(
            _plane_group_attributes(prefix, grouped[(channel_position, z_index)])
        )
    return tuple(attributes)


def _collect_plane_info_attributes_by_plane(
    copy_plane_info,
    channel_indices: dict[int, int],
    size_z: int,
) -> tuple[SearchAttribute, ...]:
    """Collect plane info attributes by plane.

    Inputs: `copy_plane_info`, `channel_indices`, `size_z`. Output:
    `tuple[SearchAttribute, ...]`.
    """
    attributes: list[SearchAttribute] = []
    for channel_position, channel_index in channel_indices.items():
        for z_index in range(size_z):
            try:
                plane_infos = tuple(
                    copy_plane_info(theC=channel_position, theZ=z_index)
                )
            except Exception:
                logger.debug(
                    "PlaneInfo collection failed for channel %s z %s.",
                    channel_position,
                    z_index,
                    exc_info=True,
                )
                continue

            prefix = f"channel_{channel_index}_z{z_index + 1}"
            attributes.extend(_plane_group_attributes(prefix, plane_infos))
    return tuple(attributes)


def _plane_group_attributes(
    prefix: str,
    plane_infos: Iterable,
) -> list[SearchAttribute]:
    """Plane group attributes.

    Inputs: `prefix`, `plane_infos`. Output: `list[SearchAttribute]`.
    """
    values_by_suffix: dict[str, list[str]] = {}
    for sequence_t, plane_info in enumerate(plane_infos or ()):
        time_index = _plane_time_index(plane_info, sequence_t)
        delta_t = _plane_quantity(plane_info, "getDeltaT", units="SECOND")
        exposure_time = _plane_quantity(
            plane_info,
            "getExposureTime",
            units="SECOND",
        )
        position_x = _plane_quantity(plane_info, "getPositionX")
        position_y = _plane_quantity(plane_info, "getPositionY")
        position_z = _plane_quantity(plane_info, "getPositionZ")
        for suffix, value in (
            ("delta_t_seconds", delta_t),
            ("exposure_time_seconds", exposure_time),
            ("position_x", position_x),
            ("position_y", position_y),
            ("position_z", position_z),
        ):
            if value is None:
                continue
            value_text = (
                _seconds_text(value) if suffix.endswith("_seconds") else str(value)
            )
            values_by_suffix.setdefault(suffix, []).append(
                f"t{time_index + 1} {value_text}"
            )

    attributes: list[SearchAttribute] = []
    for suffix, values in values_by_suffix.items():
        if values:
            attributes.append(
                SearchAttribute(
                    attribute_key=f"{prefix}_{suffix}",
                    attribute_text="; ".join(values),
                    attribute_numeric=None,
                )
            )
    return attributes


def _build_search_text(parts: Iterable[str]) -> str:
    """Search text.

    Inputs: `parts`. Output: `str`.
    """
    text = " ".join(part for part in parts if part).strip()
    if len(text) <= _SEARCH_TEXT_CAP:
        return text
    return text[:_SEARCH_TEXT_CAP].rsplit(" ", 1)[0].strip()


def extract_search_document(
    image,
) -> tuple[SearchDocument, dict[str, int | str | None]]:
    """Return extract search document.

    Inputs: `image`. Output: `tuple[SearchDocument, dict[str, int | str | None]]`.
    """
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
        objective_id = _normalized_text(
            _safe_details_value(objective_settings, "getID")
        )

    detector_binning = ""
    detector_gain = None
    if detector_settings:
        detector_binning = _normalized_text(
            _safe_details_value(detector_settings[0], "getBinning")
        )
        detector_gain = _parse_float(
            _safe_details_value(detector_settings[0], "getGain")
        )

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

    scope_context_tuple = _extract_dataset_project_context(image)
    scope_context = {
        "dataset_id": scope_context_tuple[0],
        "dataset_name": scope_context_tuple[1],
        "project_id": scope_context_tuple[2],
        "project_name": scope_context_tuple[3],
    }

    attribute_map: dict[str, SearchAttribute] = {}
    for attribute in (
        SearchAttribute("objective_collar", attribute_numeric=objective_collar),
        SearchAttribute("objective_id", attribute_text=objective_id or ""),
        SearchAttribute("detector_binning", attribute_text=detector_binning or ""),
        SearchAttribute("detector_gain", attribute_numeric=detector_gain),
        SearchAttribute("laser_line_nm", attribute_numeric=laser_line_nm),
    ):
        _append_attribute(attribute_map, attribute)
    for attribute in _collect_universal_metadata_attributes(
        image,
        channels,
        scope_context,
    ):
        _append_attribute(attribute_map, attribute)
    for attribute in _collect_all_plane_info_attributes(image, channels):
        _append_attribute(attribute_map, attribute)
    for attribute in _metadata_attributes(original_metadata):
        _append_attribute(attribute_map, attribute)
    attributes = tuple(attribute_map.values())

    search_text_parts = [
        _safe_details_value(image, "getName"),
        scope_context["dataset_name"],
        scope_context["project_name"],
        instrument_manufacturer,
        instrument_model,
        objective_model,
        detector_model,
        detector_binning,
        _channel_summary(channels),
    ]
    for attribute in attributes:
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
        "dataset_id": scope_context["dataset_id"],
        "dataset_name": scope_context["dataset_name"],
        "project_id": scope_context["project_id"],
        "project_name": scope_context["project_name"],
    }
