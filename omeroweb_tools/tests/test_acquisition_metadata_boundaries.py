from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from omeroweb_tools.services import acquisition_metadata as metadata


class _GetterlessValue:
    """Represent getterless value."""

    def __str__(self):
        return "2 mm"


class _BrokenEntry:
    """Represent broken entry."""

    def __len__(self):
        raise RuntimeError("broken entry")


class _BrokenChannel:
    """Represent broken channel."""

    @staticmethod
    def getIndex():
        """Return get index."""
        raise RuntimeError("bad index")

    @staticmethod
    def getLabel():
        """Return get label."""
        raise RuntimeError("bad label")

    @staticmethod
    def getExcitationWave():
        """Return get excitation wave."""
        return "488 nm"

    @staticmethod
    def getEmissionWave():
        """Return get emission wave."""
        return "525 nm"


class _BadChannelIndex:
    """Represent bad channel index."""

    @staticmethod
    def getIndex():
        """Return get index."""
        return object()

    @staticmethod
    def getLabel():
        """Return get label."""
        return "GFP"

    @staticmethod
    def getExcitationWave():
        """Return get excitation wave."""
        return "488 nm"

    @staticmethod
    def getEmissionWave():
        """Return get emission wave."""
        return "525 nm"


class _LegacyPixelImage:
    """Represent legacy pixel image."""

    @staticmethod
    def loadOriginalMetadata():
        """Return load original metadata."""
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

    @staticmethod
    def getChannels():
        """Return get channels."""
        return [_BrokenChannel()]

    @staticmethod
    def getAcquisitionDate():
        """Return get acquisition date."""
        raise RuntimeError("missing date")

    @staticmethod
    def getObjectiveSettings():
        """Return get objective settings."""
        raise RuntimeError("missing objective")

    @staticmethod
    def getDetectorSettings():
        """Return get detector settings."""
        raise RuntimeError("missing detector")

    @staticmethod
    def getPixelSizeX(units=None):
        """Return get pixel size x."""
        if units is True:
            raise TypeError("legacy signature")
        return "250 nm"

    @staticmethod
    def getPixelSizeY(units=True):
        """Return get pixel size y."""
        raise RuntimeError("missing y")

    @staticmethod
    def listParents():
        """Return list parents."""
        raise RuntimeError("missing parents")


def test_metadata_helpers_cover_units_caps_and_empty_values():
    """Verify test metadata helpers cover units caps and em behavior."""
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
    assert len(capped) <= metadata._SEARCH_TEXT_CAP

    class _RaisingGetter:
        """Represent raising getter."""

        @staticmethod
        def getLabel():
            """Return get label."""
            raise RuntimeError("boom")

    assert metadata._safe_channel_value(object(), "missing") is None
    assert metadata._safe_details_value(object(), "missing") is None
    assert metadata._safe_channel_value(_RaisingGetter(), "getLabel") is None
    assert metadata._safe_details_value(_RaisingGetter(), "getLabel") is None


def test_metadata_helpers_cover_malformed_omero_scalar_annotation_and_iterable_edges():
    """Verify test metadata helpers cover malformed OMERO s behavior."""

    class _ValueWrapper:
        """Represent value wrapper."""

        value = "wrapped scalar"

    class _NonScalarWrapper:
        """Represent non scalar wrapper."""

        value = ["not", "indexable"]

    class _BrokenValue:
        """Represent broken value."""

        @staticmethod
        def getValue():
            """Return get value."""
            raise RuntimeError("broken value")

        def __str__(self):
            return "2.5"

    class _LegacyPlaneQuantity:
        """Represent legacy plane quantity."""

        @staticmethod
        def getDeltaT(units=None):
            """Return get delta t."""
            if units is not None:
                raise TypeError("legacy getter does not accept units")
            return SimpleNamespace(getValue=lambda: "1.25")

    class _BrokenLegacyPlaneQuantity:
        """Represent broken legacy plane quantity."""

        @staticmethod
        def getDeltaT(units=None):
            """Return get delta t."""
            if units is not None:
                raise TypeError("legacy getter does not accept units")
            raise RuntimeError("broken legacy getter")

    class _BrokenPlaneQuantity:
        """Represent broken plane quantity."""

        @staticmethod
        def getDeltaT(units=None):
            """Return get delta t."""
            raise RuntimeError("broken getter")

    class _AxisGetter:
        """Represent axis getter."""

        @staticmethod
        def getTheC():
            """Return get the c."""
            return "2"

    class _BrokenAxisGetter:
        """Represent broken axis getter."""

        @staticmethod
        def getTheC():
            """Return get the c."""
            raise RuntimeError("broken axis getter")

    class _FallbackMapAnnotation:
        """Represent fallback map annotation."""

        OMERO_CLASS = "MapAnnotation"

        @staticmethod
        def getValue():
            """Return get value."""
            raise RuntimeError("primary map getter failed")

        @staticmethod
        def getMapValue():
            """Return get map value."""
            return [
                SimpleNamespace(getName=lambda: "Treatment", getValue=lambda: "DMSO"),
                SimpleNamespace(
                    getName=lambda: (_ for _ in ()).throw(RuntimeError("bad name")),
                    getValue=lambda: (_ for _ in ()).throw(RuntimeError("bad value")),
                ),
            ]

    class _FallbackTextAnnotation:
        """Represent fallback text annotation."""

        OMERO_CLASS = "TextAnnotation"

        @staticmethod
        def getTextValue():
            """Return get text value."""
            raise RuntimeError("text missing")

        @staticmethod
        def getDescription():
            """Return get description."""
            return "QC passed"

    class _NonIterableValue:
        """Represent non iterable value."""

        @staticmethod
        def listValues():
            """Return list values."""
            return object()

    class _BrokenIterable:
        """Represent broken iterable."""

        def __iter__(self):
            raise RuntimeError("broken iteration")

    assert metadata._scalar_text(_ValueWrapper()) == "wrapped scalar"
    assert metadata._scalar_text(_NonScalarWrapper()) == ""
    assert metadata._merge_index_text("alpha", "beta") == "alpha; beta"
    assert metadata._merge_index_text("alpha; beta", "") == "alpha; beta"
    assert metadata._merge_index_text("alpha; beta", "beta") == "alpha; beta"
    assert metadata._metadata_attributes({"!!!": "not indexed"}) == ()
    assert metadata._quantity_to_float(_BrokenValue()) == 2.5
    assert (
        metadata._plane_quantity(_LegacyPlaneQuantity(), "getDeltaT", units="SECOND")
        == 1.25
    )
    assert (
        metadata._plane_quantity(
            _BrokenLegacyPlaneQuantity(), "getDeltaT", units="SECOND"
        )
        is None
    )
    assert (
        metadata._plane_quantity(_BrokenPlaneQuantity(), "getDeltaT", units="SECOND")
        is None
    )
    assert metadata._plane_axis_index(_AxisGetter(), "theC") == 2
    assert metadata._plane_axis_index(_BrokenAxisGetter(), "theC") is None
    assert metadata._plane_axis_index(SimpleNamespace(theC=object()), "theC") is None
    assert metadata._callable_accepts_no_args(int) is True
    assert metadata._attribute_from_text("", "value") is None
    assert metadata._attribute_from_text("valid", " ") is None

    bucket: dict[str, metadata.SearchAttribute] = {}
    metadata._append_text_attribute(
        bucket, "!!!", "not indexed", trust_generated_key=False
    )
    assert bucket == {}

    assert tuple(metadata._annotation_value_pairs(_FallbackMapAnnotation())) == (
        ("annotation_map_Treatment", "DMSO"),
    )
    assert tuple(metadata._annotation_value_pairs(_FallbackTextAnnotation())) == (
        ("textannotation_description", "QC passed"),
    )
    scalar_iter_value = metadata._safe_iter_call(_NonIterableValue(), "listValues")
    assert len(scalar_iter_value) == 1
    assert (
        metadata._safe_iter_call(SimpleNamespace(listValues=lambda: None), "listValues")
        == ()
    )
    assert (
        metadata._safe_iter_call(
            SimpleNamespace(listValues=_BrokenIterable), "listValues"
        )
        == ()
    )
    assert (
        metadata._pixel_axis_size(
            SimpleNamespace(getSizeZ=lambda: "not-an-int"), "getSizeZ", 7
        )
        == 7
    )

    class _ImageWithBrokenRawChannels:
        """Represent image with broken raw channels."""

        @staticmethod
        def getChannels():
            """Return get channels."""
            raise RuntimeError("channel load failed")

    assert (
        metadata._collect_universal_metadata_attributes(
            _ImageWithBrokenRawChannels(),
            (),
            {"dataset_name": "", "project_name": ""},
        )
        == ()
    )
    capped = metadata._build_search_text(["word"] * 20000)
    assert len(capped) <= metadata._SEARCH_TEXT_CAP
    assert capped.endswith("word")


def test_plane_info_collection_keeps_legacy_targeted_copy_plane_info_path():
    """Verify test plane info collection keeps legacy targe behavior."""

    class _Value:
        """Represent value."""

        def __init__(self, value):
            self._raw_value = value

        def getValue(self):
            """Return get value."""
            return self._raw_value

    class _PlaneInfo:
        """Represent plane info."""

        theT = 0

        @staticmethod
        def getDeltaT(units="SECOND"):
            """Return get delta t."""
            assert units == "SECOND"
            return _Value(3.5)

    class _Pixels:
        """Represent pixels."""

        def __init__(self):
            self.copy_plane_info_calls = []

        @staticmethod
        def getSizeZ():
            """Return get size z."""
            return 1

        @staticmethod
        def getSizeC():
            """Return get size c."""
            return 1

        def copyPlaneInfo(self, theC, theZ):
            """Handle copy plane info."""
            self.copy_plane_info_calls.append((theC, theZ))
            return [_PlaneInfo()]

    pixels = _Pixels()

    attributes = metadata._collect_all_plane_info_attributes(
        SimpleNamespace(getPrimaryPixels=lambda: pixels),
        (metadata.SearchChannel(channel_index=4),),
    )

    assert pixels.copy_plane_info_calls == [(0, 0)]
    assert attributes == (
        metadata.SearchAttribute(
            attribute_key="channel_4_z1_delta_t_seconds",
            attribute_text="t1 3.5 seconds",
            attribute_numeric=None,
        ),
    )


def test_plane_info_collection_covers_unavailable_bulk_and_targeted_failures():
    """Verify test plane info collection covers unavailable behavior."""

    class _Value:
        """Represent value."""

        def __init__(self, value):
            self._raw_value = value

        def getValue(self):
            """Return get value."""
            return self._raw_value

    class _PlaneInfo:
        """Represent plane info."""

        theC = 0
        theZ = 1
        theT = 0

        @staticmethod
        def getDeltaT(units="SECOND"):
            """Return get delta t."""
            return _Value(2.5)

    class _NoPlaneInfoPixels:
        """Represent no plane info pixels."""

        @staticmethod
        def getSizeZ():
            """Return get size z."""
            return 1

        @staticmethod
        def getSizeC():
            """Return get size c."""
            return 1

    class _BulkTypeErrorPixels:
        """Represent bulk type error pixels."""

        @staticmethod
        def getSizeZ():
            """Return get size z."""
            return 1

        @staticmethod
        def getSizeC():
            """Return get size c."""
            return 1

        @staticmethod
        def copyPlaneInfo(*args, **kwargs):
            """Handle copy plane info."""
            if not args and not kwargs:
                raise TypeError("bulk unsupported")
            return [_PlaneInfo()]

    class _BulkFailurePixels(_BulkTypeErrorPixels):
        """Represent bulk failure pixels."""

        def copyPlaneInfo(self, *args, **kwargs):
            """Handle copy plane info."""
            if not args and not kwargs:
                raise RuntimeError("bulk failed")
            return [_PlaneInfo()]

    class _BulkMissingAxisPixels(_BulkTypeErrorPixels):
        """Represent bulk missing axis pixels."""

        def copyPlaneInfo(self, *args, **kwargs):
            """Handle copy plane info."""
            return [SimpleNamespace(theC=None, theZ=0, theT=0)]

    class _TargetedFailurePixels:
        """Represent targeted failure pixels."""

        def __init__(self):
            self.calls = []

        @staticmethod
        def getSizeZ():
            """Return get size z."""
            return 2

        @staticmethod
        def getSizeC():
            """Return get size c."""
            return 1

        def copyPlaneInfo(self, theC, theZ):
            """Handle copy plane info."""
            self.calls.append((theC, theZ))
            if theZ == 0:
                raise RuntimeError("plane failed")
            return [_PlaneInfo()]

    assert (
        metadata._collect_all_plane_info_attributes(
            SimpleNamespace(getPrimaryPixels=_NoPlaneInfoPixels),
            (),
        )
        == ()
    )
    assert (
        metadata._collect_all_plane_info_attributes(
            SimpleNamespace(getPrimaryPixels=_BulkFailurePixels),
            (),
        )
        == ()
    )
    assert (
        metadata._collect_all_plane_info_attributes(
            SimpleNamespace(getPrimaryPixels=_BulkMissingAxisPixels),
            (),
        )
        == ()
    )

    fallback_attributes = metadata._collect_all_plane_info_attributes(
        SimpleNamespace(getPrimaryPixels=_BulkTypeErrorPixels),
        (metadata.SearchChannel(channel_index=3),),
    )
    assert fallback_attributes == (
        metadata.SearchAttribute(
            attribute_key="channel_3_z1_delta_t_seconds",
            attribute_text="t1 2.5 seconds",
            attribute_numeric=None,
        ),
    )

    targeted_pixels = _TargetedFailurePixels()
    targeted_attributes = metadata._collect_all_plane_info_attributes(
        SimpleNamespace(getPrimaryPixels=lambda: targeted_pixels),
        (metadata.SearchChannel(channel_index=3),),
    )
    assert targeted_pixels.calls == [(0, 0), (0, 1)]
    assert targeted_attributes == (
        metadata.SearchAttribute(
            attribute_key="channel_3_z2_delta_t_seconds",
            attribute_text="t1 2.5 seconds",
            attribute_numeric=None,
        ),
    )


def test_metadata_collection_helpers_tolerate_broken_omero_objects():
    """Verify test metadata collection helpers tolerate bro behavior."""

    class _BrokenMetadataImage:
        """Represent broken metadata image."""

        @staticmethod
        def loadOriginalMetadata():
            """Return load original metadata."""
            raise RuntimeError("no metadata")

    class _WeirdMetadataImage:
        """Represent weird metadata image."""

        def __init__(self, payload=None):
            self._payload = payload

        def loadOriginalMetadata(self):
            """Return load original metadata."""
            return self._payload

        @staticmethod
        def getChannels():
            """Return get channels."""
            raise RuntimeError("no channels")

        @staticmethod
        def listParents():
            """Return list parents."""
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
        """Represent broken section."""

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


def test_metadata_attributes_and_extract_search_document_cover_legacy_omero_shapes(
    monkeypatch,
):
    """Verify test metadata attributes and extract search d behavior."""
    monkeypatch.setattr(
        metadata,
        "get_text",
        lambda value: value.getValue() if hasattr(value, "getValue") else value,
    )
    original_metadata = {f"Key {index}": f"value {index}" for index in range(150)}
    attributes = metadata._metadata_attributes(original_metadata)
    assert len(attributes) == len(original_metadata)
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

    document, context = metadata.extract_search_document(_LegacyPixelImage())

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
    assert len(document.search_document) <= metadata._SEARCH_TEXT_CAP
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

    class _FailingPixelImage(_LegacyPixelImage):
        """Represent failing pixel image."""

        def getPixelSizeX(self, units=None):
            """Return get pixel size x."""
            if units is True:
                raise TypeError("legacy signature")
            raise RuntimeError("still broken")

    failing_document, _context = metadata.extract_search_document(_FailingPixelImage())
    assert failing_document.pixel_size_x_um is None
