from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from omeroweb_tools.services import acquisition_metadata as metadata


class _GetterlessValue:
    def __str__(self):
        return "2 mm"


class _BrokenEntry:
    def __len__(self):
        raise RuntimeError("broken entry")


class _BrokenChannel:
    def getIndex(self):
        raise RuntimeError("bad index")

    def getLabel(self):
        raise RuntimeError("bad label")

    def getExcitationWave(self):
        return "488 nm"

    def getEmissionWave(self):
        return "525 nm"


class _BadChannelIndex:
    def getIndex(self):
        return object()

    def getLabel(self):
        return "GFP"

    def getExcitationWave(self):
        return "488 nm"

    def getEmissionWave(self):
        return "525 nm"


class _FallbackPixelImage:
    def loadOriginalMetadata(self):
        long_value = "Zeiss " + ("alpha " * 2500)
        return (
            None,
            [
                ("Instrument Manufacturer", "Zeiss"),
                ("Objective Settings Model", "should skip"),
                ("Long Text", long_value),
            ],
            [("Laser Line", "488 nm"), _BrokenEntry()],
        )

    def getChannels(self):
        return [_BrokenChannel()]

    def getAcquisitionDate(self):
        raise RuntimeError("missing date")

    def getObjectiveSettings(self):
        raise RuntimeError("missing objective")

    def getDetectorSettings(self):
        raise RuntimeError("missing detector")

    def getPixelSizeX(self, units=None):
        if units is True:
            raise TypeError("legacy signature")
        return "250 nm"

    def getPixelSizeY(self, units=True):
        raise RuntimeError("missing y")

    def listParents(self):
        raise RuntimeError("missing parents")


def test_metadata_helpers_cover_units_caps_and_empty_values():
    assert metadata._normalized_key(" BF_Objective NA ") == "objective na"
    assert metadata._normalized_text(None) == ""
    assert metadata._parse_datetime(None) is None
    assert metadata._parse_datetime("   ") is None
    assert metadata._parse_datetime("2026-04-12T10:15:00Z") == datetime.fromisoformat(
        "2026-04-12T10:15:00+00:00"
    )
    assert metadata._parse_datetime("not-a-date") is None
    assert metadata._parse_float(None) is None
    assert metadata._parse_float("   ") is None
    assert metadata._parse_float("gain=1.5x") == 1.5
    assert metadata._parse_float("no number here") is None
    assert metadata._unit_factor_to_um("mm") == 1000.0
    assert metadata._unit_factor_to_um("unsupported") is None
    assert metadata._parse_length_to_um(None) is None
    assert metadata._parse_length_to_um("") is None
    assert metadata._parse_length_to_um("500 nm") == 0.5
    assert metadata._parse_length_to_um("1.5 parsecs") == 1.5
    assert metadata._parse_length_to_um("5") == 5.0
    assert metadata._parse_length_to_um(_GetterlessValue()) == 2000.0
    assert metadata._parse_length_to_um("words only") is None
    fake_match = SimpleNamespace(
        group=lambda name: {"value": "10", "unit": "parsec"}[name]
    )
    assert metadata._unit_factor_to_um("parsec") is None
    original_number_with_unit = metadata._NUMBER_WITH_UNIT_RE
    metadata._NUMBER_WITH_UNIT_RE = SimpleNamespace(search=lambda value: fake_match)
    try:
        assert metadata._parse_length_to_um("10 parsec") is None
    finally:
        metadata._NUMBER_WITH_UNIT_RE = original_number_with_unit
    original_first_number = metadata._FIRST_NUMBER_RE
    metadata._FIRST_NUMBER_RE = SimpleNamespace(
        search=lambda value: SimpleNamespace(group=lambda index: "not-a-float")
    )
    try:
        assert metadata._parse_float("bad") is None
    finally:
        metadata._FIRST_NUMBER_RE = original_first_number
    assert (
        metadata._canonical_field_candidate(
            [("Objective Settings Model", "skip"), ("Objective Model", "Plan-Apo")],
            include_groups=(("objective",), ("model",)),
            exclude_terms=("settings",),
        )
        == "Plan-Apo"
    )
    assert (
        metadata._canonical_field_candidate(
            [("Objective Model", "")],
            include_groups=(("objective",), ("model",)),
        )
        == ""
    )
    assert (
        metadata._canonical_numeric_candidate(
            [("Pixel Size X", "250 nm")],
            include_groups=(("pixel",), ("x",)),
            convert_um=True,
        )
        == 0.25
    )
    assert (
        metadata._canonical_numeric_candidate(
            [("Pixel Size X", "")],
            include_groups=(("pixel",), ("x",)),
            convert_um=True,
        )
        is None
    )
    capped = metadata._build_search_text(["alpha"] * 5000)
    assert len(capped) <= 8000

    class _RaisingGetter:
        def getLabel(self):
            raise RuntimeError("boom")

    assert metadata._safe_channel_value(object(), "missing") is None
    assert metadata._safe_details_value(object(), "missing") is None
    assert metadata._safe_channel_value(_RaisingGetter(), "getLabel") is None
    assert metadata._safe_details_value(_RaisingGetter(), "getLabel") is None


def test_metadata_collection_helpers_tolerate_broken_omero_objects():
    class _BrokenMetadataImage:
        def loadOriginalMetadata(self):
            raise RuntimeError("no metadata")

    class _WeirdMetadataImage:
        def __init__(self, payload=None):
            self._payload = payload

        def loadOriginalMetadata(self):
            return self._payload

        def getChannels(self):
            raise RuntimeError("no channels")

        def listParents(self):
            return []

    assert metadata._collect_original_metadata(_BrokenMetadataImage()) == {}
    assert metadata._collect_original_metadata(_WeirdMetadataImage(())) == {}
    weird_metadata = metadata._collect_original_metadata(
        _WeirdMetadataImage(
            (None, [("Instrument Model", "LSM 980"), ("only-key",)], [_BrokenEntry()])
        )
    )
    assert weird_metadata == {"BF_Instrument Model": "LSM 980"}

    class _BrokenSection:
        def __bool__(self):
            return True

        def __iter__(self):
            raise RuntimeError("broken section")

    broken_sections = metadata._collect_original_metadata(
        _WeirdMetadataImage((None, _BrokenSection(), _BrokenSection()))
    )
    assert broken_sections == {}
    assert metadata._collect_channels(_WeirdMetadataImage()) == ()
    assert metadata._collect_channels(
        SimpleNamespace(getChannels=lambda: [_BadChannelIndex()])
    ) == (
        metadata.SearchChannel(
            channel_index=0,
            label="GFP",
            excitation_nm=488.0,
            emission_nm=525.0,
        ),
    )
    assert metadata._extract_dataset_project_context(_WeirdMetadataImage()) == (
        None,
        "",
        None,
        "",
    )
    dataset = SimpleNamespace(
        _id="bad-dataset",
        getName=lambda: "Dataset A",
        listParents=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    image_with_bad_dataset = SimpleNamespace(listParents=lambda: [dataset])
    original_get_id = metadata.get_id
    metadata.get_id = lambda obj: getattr(obj, "_id", None)
    try:
        assert metadata._extract_dataset_project_context(image_with_bad_dataset) == (
            "bad-dataset",
            "Dataset A",
            None,
            "",
        )
    finally:
        metadata.get_id = original_get_id


def test_metadata_attributes_and_extract_search_document_cover_fallback_paths(
    monkeypatch,
):
    monkeypatch.setattr(
        metadata,
        "get_text",
        lambda value: value.getValue() if hasattr(value, "getValue") else value,
    )
    original_metadata = {
        f"Key {index}": f"value {index}"
        for index in range(metadata._METADATA_ATTRIBUTE_CAP + 10)
    }
    attributes = metadata._metadata_attributes(original_metadata)
    assert len(attributes) == metadata._METADATA_ATTRIBUTE_CAP
    original_attribute_key = metadata._attribute_key
    metadata._attribute_key = lambda raw_key: "duplicate-key"
    try:
        duplicate_attributes = metadata._metadata_attributes(
            {"first": "value", "second": "other", "blank": ""}
        )
    finally:
        metadata._attribute_key = original_attribute_key
    assert duplicate_attributes == (
        metadata.SearchAttribute(
            attribute_key="duplicate-key",
            attribute_text="value",
            attribute_numeric=None,
        ),
    )
    assert metadata._metadata_attributes({"blank": "   "}) == ()
    bucket = {}
    metadata._append_attribute(
        bucket,
        metadata.SearchAttribute(attribute_key="", attribute_text="skip"),
    )
    metadata._append_attribute(
        bucket,
        metadata.SearchAttribute(attribute_key="only_numeric", attribute_numeric=1.5),
    )
    metadata._append_attribute(
        bucket,
        metadata.SearchAttribute(attribute_key="only_numeric", attribute_numeric=2.0),
    )
    assert list(bucket) == ["only_numeric"]

    document, context = metadata.extract_search_document(_FallbackPixelImage())

    assert document.instrument_manufacturer == "Zeiss"
    assert document.objective_model == ""
    assert document.acquisition_date is None
    assert document.pixel_size_x_um == 0.25
    assert document.pixel_size_y_um is None
    assert document.z_step_um is None
    assert document.channels == (
        metadata.SearchChannel(
            channel_index=0,
            label="",
            excitation_nm=488.0,
            emission_nm=525.0,
        ),
    )
    assert document.channel_summary == "Ex 488 nm / Em 525 nm"
    assert len(document.search_document) <= 8000
    assert any(
        attribute.attribute_key == "laser_line_nm"
        and attribute.attribute_numeric == 488.0
        for attribute in document.attributes
    )
    assert context == {
        "dataset_id": None,
        "dataset_name": "",
        "project_id": None,
        "project_name": "",
    }

    class _FailingPixelImage(_FallbackPixelImage):
        def getPixelSizeX(self, units=None):
            if units is True:
                raise TypeError("legacy signature")
            raise RuntimeError("still broken")

    failing_document, _context = metadata.extract_search_document(_FailingPixelImage())
    assert failing_document.pixel_size_x_um is None
