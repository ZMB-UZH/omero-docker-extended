from __future__ import annotations

from types import SimpleNamespace

import pytest

from omeroweb_omp_plugin.services.omero import image_service, metadata_service
from omeroweb_omp_plugin.services.parsing import filename_parser


class _Value:
    """Represent value."""

    def __init__(self, value):
        """Initialize the instance.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return the fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _Image:
    """Represent image."""

    def __init__(self, image_id, name, *, fileset=None):
        """Initialize the instance.

        Inputs: `image_id`, `name`, `fileset`. Output: None.
        """
        self.id = image_id
        self._name = name
        self._fileset = fileset

    def getId(self):
        """Return the fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return the fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def getFileset(self):
        """Return Fileset.

        Inputs: none. Output: computed value.
        """
        if callable(self._fileset):
            return self._fileset()
        return self._fileset


class _Dataset:
    """Represent dataset."""

    def __init__(self, dataset_id, name, images, *, owner_id=7):
        """Initialize the instance.

        Inputs: `dataset_id`, `name`, `images`, `owner_id`. Output: None.
        """
        self.id = dataset_id
        self.owner_id = owner_id
        self._name = name
        self._images = list(images)

    def getId(self):
        """Return the fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return the fake object name.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._name)

    def listChildren(self):
        """Return list children.

        Inputs: none. Output: `list` result.
        """
        return list(self._images)


class _Project:
    """Represent project."""

    def __init__(self, datasets):
        """Initialize the instance.

        Inputs: `datasets`. Output: None.
        """
        self._datasets = list(datasets)

    def listChildren(self):
        """Return list children.

        Inputs: none. Output: `list` result.
        """
        return list(self._datasets)


def test_filename_parser_covers_group_class_whitespace_and_validation_edges():
    """Verify filename parser covers group class whitespace and validation edges.

    Inputs: none. Output: None. Raises on invalid or unavailable state.
    """
    assert filename_parser._parse_separator_fragment(r"\s") == ("", True)
    assert filename_parser._parse_separator_fragment(r"\.") == (".", False)
    assert filename_parser._extract_separator_fragments(r"[\.-]+") == (
        (".", "-"),
        False,
    )
    assert filename_parser._extract_separator_fragments(r"(?:_|\s|_)+") == (
        ("_",),
        True,
    )

    grouped, grouped_whitespace = filename_parser._extract_separator_fragments(
        r"(?:-|_|\s)+"
    )
    assert grouped == ("-", "_")
    assert grouped_whitespace is True

    class_based, class_whitespace = filename_parser._extract_separator_fragments(
        r"[_\s-]+"
    )
    assert class_based == ("_", "-")
    assert class_whitespace is True

    assert filename_parser._split_on_separator_fragments(
        "  alpha__  __beta",
        ("__",),
        True,
    ) == ["alpha", "beta"]
    assert filename_parser.parse_filename("folder alpha_beta.txt", "_") == [
        "alpha",
        "beta",
    ]
    assert filename_parser.parse_filename(
        "prefix [alpha__  __beta].ome.tif",
        r"(?:_|\s)+",
    ) == ["alpha", "beta"]

    assert filename_parser.is_supported_separator_pattern(r"[\s-]+") is True
    assert filename_parser.is_supported_separator_pattern(r"[^\s]") is False

    for invalid_pattern in (r"\ab", r"(?:|_)", r"[^\s]", "[\\]"):
        try:
            filename_parser._extract_separator_fragments(invalid_pattern)
        except ValueError as exc:
            assert "Invalid separator regex" in str(exc)
        else:
            raise AssertionError(f"Expected invalid separator regex: {invalid_pattern}")

    with pytest.raises(ValueError, match="Invalid separator regex"):
        filename_parser._extract_separator_fragments(r"(?:")
    with pytest.raises(ValueError, match="Invalid separator regex"):
        filename_parser._extract_separator_fragments(r"(?:)")


def test_image_service_covers_runtime_fallbacks_and_format_detection_edges(
    monkeypatch,
):
    """Verify image service covers runtime fallbacks and format detection edges.

    Inputs: `monkeypatch`. Output: computed value. Raises on invalid or unavailable
    state.

    state.
    """
    monkeypatch.setattr(
        image_service,
        "get_id",
        lambda obj: (
            obj.getId().getValue()
            if hasattr(obj, "getId")
            else getattr(obj, "id", None)
        ),
    )
    monkeypatch.setattr(
        image_service,
        "get_text",
        lambda value: value.getValue() if hasattr(value, "getValue") else str(value),
    )
    monkeypatch.setattr(
        image_service,
        "is_owned_by_user",
        lambda obj, owner_id: (
            owner_id is None or getattr(obj, "owner_id", None) == owner_id
        ),
    )

    external_image = _Image("external-id", "external.tif")
    skipped_image = _Image(None, "missing-id.tif")

    class _BulkConn:
        """Represent bulk conn."""

        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            """Return Objects.

            Inputs: `object_type`, `ids`, `obj_ids`. Output: list. Raises on invalid or
            unavailable state.
            """
            assert object_type == "Image"
            if ids is not None:
                raise TypeError("legacy signature")
            assert obj_ids == [1, 2]
            return [skipped_image, external_image]

    bulk_fetched = image_service.fetch_images_by_ids(_BulkConn(), [1, 2])
    assert bulk_fetched == {"external-id": external_image}

    class _FallbackConn:
        """Represent fallback conn."""

        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            """Return Objects.

            Inputs: `object_type`, `ids`, `obj_ids`. Output: None. Raises on invalid or
            unavailable state.
            """
            raise RuntimeError("bulk fetch unavailable")

        @staticmethod
        def getObject(object_type, image_id):
            """Return Object.

            Inputs: `object_type`, `image_id`. Output: `_Image` result. Raises on
            invalid or unavailable state.
            """
            assert object_type == "Image"
            if image_id == 1:
                raise RuntimeError("transient lookup failure")
            return _Image(image_id, f"image-{image_id}.tif")

    fallback_fetched = image_service.fetch_images_by_ids(_FallbackConn(), [1, 2])
    assert sorted(fallback_fetched) == [2]
    assert fallback_fetched[2].getName() == "image-2.tif"

    assert (
        image_service.collect_images_by_dataset_sorted(
            SimpleNamespace(getObject=lambda *_args: None),
            7,
            owner_id=7,
        )
        == []
    )

    class _BrokenProject:
        """Represent broken project."""

        @staticmethod
        def listChildren():
            """Return list children.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("broken project")

    assert (
        image_service.collect_images_by_dataset_sorted(
            SimpleNamespace(getObject=lambda *_args: _BrokenProject()),
            7,
            owner_id=7,
        )
        == []
    )

    assert (
        image_service.collect_images_by_selected_datasets(
            SimpleNamespace(getObject=lambda *_args: None),
            7,
            [],
            owner_id=7,
        )
        == []
    )
    assert (
        image_service.collect_images_by_selected_datasets(
            SimpleNamespace(getObject=lambda *_args: None),
            7,
            ["not-a-number"],
            owner_id=7,
        )
        == []
    )

    selected_project = _Project(
        [
            _Dataset(None, "No ID", [_Image(1, "ignored.tif")]),
            _Dataset("bad-id", "Bad ID", [_Image(2, "ignored.tif")]),
            _Dataset(
                9,
                "Target",
                [_Image(5, "late.tif"), _Image(1, "early.tif")],
            ),
        ]
    )
    selected_rows = image_service.collect_images_by_selected_datasets(
        SimpleNamespace(getObject=lambda *_args: selected_project),
        7,
        ["9"],
        limit=1,
        owner_id=7,
    )
    assert [
        (dataset.getId().getValue(), [image.getId().getValue() for image in images])
        for dataset, images in selected_rows
    ] == [(9, [1])]

    class _OriginalFile:
        """Represent original file."""

        def __init__(self, *, format_value=None, name=None):
            """Initialize the instance.

            Inputs: `format_value`, `name`. Output: None.
            """
            self._format_value = format_value
            self._name = name

        def getFormat(self):
            """Return Format.

            Inputs: none. Output: computed value.
            """
            return None if self._format_value is None else _Value(self._format_value)

        def getName(self):
            """Return the fake object name.

            Inputs: none. Output: `self._name`.
            """
            return self._name

    class _UsedFile:
        """Represent used file."""

        def __init__(self, original_file):
            """Initialize the instance.

            Inputs: `original_file`. Output: None.
            """
            self._original_file = original_file

        def getOriginalFile(self):
            """Return Original File.

            Inputs: none. Output: `self._original_file`. Raises on invalid or
            unavailable state.
            """
            if isinstance(self._original_file, Exception):
                raise self._original_file
            return self._original_file

    class _Fileset:
        """Represent fileset."""

        def __init__(self, used_files=None, *, explode=False):
            """Initialize the instance.

            Inputs: `used_files`, `explode`. Output: None.
            """
            self._used_files = list(used_files or [])
            self._explode = explode

        def copyUsedFiles(self):
            """Copy Used Files.

            Inputs: none. Output: `list` result. Raises on invalid or unavailable state.
            """
            if self._explode:
                raise RuntimeError("copy failed")
            return list(self._used_files)

    class _RaisingName:
        """Represent raising name."""

        @staticmethod
        def getValue():
            """Return the fake OMERO value.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("bad image name")

    image_from_fileset_extension = _Image(
        21,
        "ignored.bin",
        fileset=_Fileset(
            [
                _UsedFile(
                    _OriginalFile(format_value="text/plain", name=_Value("sample.lif"))
                )
            ]
        ),
    )
    image_from_name_fallback = _Image(
        22,
        _Value("scan.ome.tif"),
        fileset=_Fileset(explode=True),
    )
    image_with_broken_used_file = _Image(
        23,
        _RaisingName(),
        fileset=_Fileset([_UsedFile(RuntimeError("bad original file"))]),
    )
    image_from_image_name_extension = _Image(24, _Value("preview.bmp"))

    summary_project = _Project(
        [
            _Dataset(
                31,
                "Formats",
                [
                    image_from_fileset_extension,
                    image_from_name_fallback,
                    image_with_broken_used_file,
                    image_from_image_name_extension,
                ],
            )
        ]
    )
    summaries = image_service.collect_dataset_summaries(
        SimpleNamespace(getObject=lambda *_args: summary_project),
        7,
        owner_id=7,
    )
    assert summaries == [
        {
            "id": "31",
            "name": "Formats",
            "image_count": 4,
            "formats": "BMP, Leica LIF, OME-TIFF",
        }
    ]

    assert (
        image_service.collect_dataset_summaries(
            SimpleNamespace(getObject=lambda *_args: None),
            7,
            owner_id=7,
        )
        == []
    )
    assert (
        image_service.collect_dataset_summaries(
            SimpleNamespace(
                getObject=lambda *_args: (_ for _ in ()).throw(RuntimeError("boom"))
            ),
            7,
            owner_id=7,
        )
        == []
    )

    assert (
        image_service.collect_images_in_project(
            SimpleNamespace(getObject=lambda *_args: None),
            7,
            limit=1,
        )
        == []
    )
    assert (
        image_service.collect_images_in_project(
            SimpleNamespace(
                getObject=lambda *_args: (_ for _ in ()).throw(
                    RuntimeError("project boom")
                )
            ),
            7,
            limit=1,
        )
        == []
    )


def test_extract_acquisition_metadata_covers_inner_fallbacks_and_outer_error_logging():
    """Verify extract acquisition metadata covers inner fallbacks and outer error logging.

    Inputs: none. Output: computed value. Raises on invalid or unavailable state.
    """

    class _ObjectiveSettings:
        """Represent objective settings."""

        @staticmethod
        def getID():
            """Return ID.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing objective id")

        @staticmethod
        def getCorrectionCollar():
            """Return Correction Collar.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing collar")

    class _Channel:
        """Represent channel."""

        @staticmethod
        def getIndex():
            """Return Index.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing index")

        @staticmethod
        def getLabel():
            """Return Label.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing label")

        @staticmethod
        def getEmissionWave():
            """Return Emission Wave.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing emission")

        @staticmethod
        def getExcitationWave():
            """Return Excitation Wave.

            Inputs: none. Output: '405'.
            """
            return "405"

    class _Detector:
        """Represent detector."""

        @staticmethod
        def getID():
            """Return ID.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing detector id")

        @staticmethod
        def getBinning():
            """Return Binning.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing binning")

        @staticmethod
        def getGain():
            """Return Gain.

            Inputs: none. Output: '1.5'.
            """
            return "1.5"

    class _BrokenMetadata:
        """Represent broken metadata."""

        def __len__(self):
            """Return the instance length.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("len failed")

    class _ImageWithInnerFailures:
        """Represent image with inner failures."""

        @staticmethod
        def getId():
            """Return the fake OMERO identifier.

            Inputs: none. Output: 7.
            """
            return 7

        @staticmethod
        def getAcquisitionDate():
            """Return Acquisition Date.

            Inputs: none. Output: '2026-03-31T12:00:00'.
            """
            return "2026-03-31T12:00:00"

        @staticmethod
        def getObjectiveSettings():
            """Return Objective Settings.

            Inputs: none. Output: `_ObjectiveSettings` result.
            """
            return _ObjectiveSettings()

        @staticmethod
        def getChannels():
            """Return Channels.

            Inputs: none. Output: list.
            """
            return [_Channel()]

        @staticmethod
        def getDetectorSettings():
            """Return Detector Settings.

            Inputs: none. Output: list.
            """
            return [_Detector()]

        @staticmethod
        def loadOriginalMetadata():
            """Return load original metadata.

            Inputs: none. Output: `_BrokenMetadata` result.
            """
            return _BrokenMetadata()

    cleaned = metadata_service.extract_acquisition_metadata(_ImageWithInnerFailures())
    assert cleaned == {
        "acquisition_date": "2026-03-31T12:00:00",
        "channel_unknown_excitation": "405",
        "detector_unknown_gain": "1.5",
    }

    class _ImageWithOuterFailures:
        """Represent image with outer failures."""

        @staticmethod
        def getId():
            """Return the fake OMERO identifier.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("missing id")

        @staticmethod
        def getAcquisitionDate():
            """Return Acquisition Date.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("no acquisition date")

        @staticmethod
        def getObjectiveSettings():
            """Return Objective Settings.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("no objective")

        @staticmethod
        def getChannels():
            """Return Channels.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("no channels")

        @staticmethod
        def getDetectorSettings():
            """Return Detector Settings.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("no detectors")

        @staticmethod
        def loadOriginalMetadata():
            """Return load original metadata.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("no metadata")

    assert (
        metadata_service.extract_acquisition_metadata(_ImageWithOuterFailures()) == {}
    )


def test_extract_acquisition_metadata_persists_long_values_despite_store_close_failure(
    monkeypatch,
):
    """Verify extract acquisition metadata persists long values despite store close failure.

    Inputs: `monkeypatch`. Output: computed value or None. Raises on invalid or
    unavailable state.

    unavailable state.
    """

    class _OriginalFileStub:
        """Represent original file stub."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self._id = _Value(321)

        def setName(self, value):
            """Set Name.

            Inputs: `value`. Output: None.
            """
            self.name = value

        def setPath(self, value):
            """Set Path.

            Inputs: `value`. Output: None.
            """
            self.path = value

        def setSize(self, value):
            """Set Size.

            Inputs: `value`. Output: None.
            """
            self.size = value

        def setMimetype(self, value):
            """Set Mimetype.

            Inputs: `value`. Output: None.
            """
            self.mimetype = value

        def getId(self):
            """Return the fake OMERO identifier.

            Inputs: none. Output: `self._id`.
            """
            return self._id

    class _FileAnnotationStub:
        """Represent file annotation stub."""

        def setNs(self, value):
            """Set Ns.

            Inputs: `value`. Output: None.
            """
            self.ns = value

        def setFile(self, value):
            """Set File.

            Inputs: `value`. Output: None.
            """
            self.file = value

    class _ImageAnnotationLinkStub:
        """Represent image annotation link stub."""

        def setParent(self, value):
            """Set Parent.

            Inputs: `value`. Output: None.
            """
            self.parent = value

        def setChild(self, value):
            """Set Child.

            Inputs: `value`. Output: None.
            """
            self.child = value

    class _ImageStub:
        """Represent image stub."""

        def __init__(self, image_id, loaded):
            """Initialize the instance.

            Inputs: `image_id`, `loaded`. Output: None.
            """
            self.image_id = image_id
            self.loaded = loaded

    class _RawStore:
        """Represent raw store."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.file_id = None
            self.saved_payload = None
            self.saved = False

        def setFileId(self, value):
            """Set File ID.

            Inputs: `value`. Output: None.
            """
            self.file_id = value

        def write(self, payload, offset, length):
            """Write data to the resource.

            Inputs: `payload`, `offset`, `length`. Output: None.
            """
            self.saved_payload = payload

        def save(self):
            """Persist the object state.

            Inputs: none. Output: None.
            """
            self.saved = True

        @staticmethod
        def close():
            """Close the resource.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise RuntimeError("close failed")

    class _UpdateService:
        """Represent update service."""

        def __init__(self):
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.saved_objects = []

        def saveAndReturnObject(self, obj):
            """Save and return object.

            Inputs: `obj`. Output: `obj`.
            """
            self.saved_objects.append(obj)
            return obj

    raw_store = _RawStore()
    update_service = _UpdateService()

    monkeypatch.setattr(metadata_service, "OriginalFileI", _OriginalFileStub)
    monkeypatch.setattr(metadata_service, "FileAnnotationI", _FileAnnotationStub)
    monkeypatch.setattr(
        metadata_service,
        "ImageAnnotationLinkI",
        _ImageAnnotationLinkStub,
    )
    monkeypatch.setattr(metadata_service, "ImageI", _ImageStub)
    monkeypatch.setattr(metadata_service, "rstring", lambda value: value)
    monkeypatch.setattr(metadata_service, "rlong", lambda value: value)

    class _ImageWithLongMetadata:
        """Represent image with long metadata."""

        _obj = "image-object"
        _conn = SimpleNamespace(
            getUpdateService=lambda: update_service,
            c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
        )

        @staticmethod
        def getId():
            """Return the fake OMERO identifier.

            Inputs: none. Output: 7.
            """
            return 7

        @staticmethod
        def getAcquisitionDate():
            """Return Acquisition Date.

            Inputs: none. Output: `_Value` result.
            """
            return _Value("x" * 260)

        @staticmethod
        def getObjectiveSettings():
            """Return Objective Settings.

            Inputs: none. Output: None.
            """
            return None

        @staticmethod
        def getChannels():
            """Return Channels.

            Inputs: none. Output: list.
            """
            return []

        @staticmethod
        def getDetectorSettings():
            """Return Detector Settings.

            Inputs: none. Output: list.
            """
            return []

        @staticmethod
        def loadOriginalMetadata():
            """Return load original metadata.

            Inputs: none. Output: None.
            """
            return None

    cleaned = metadata_service.extract_acquisition_metadata(_ImageWithLongMetadata())

    assert cleaned == {
        "acquisition_date": "[LONG_VALUE_STORED_IN_FILEANNOTATION key=acquisition_date]",
        "full_metadata_file": "FileAnnotation:321",
    }
    assert raw_store.file_id == 321
    assert raw_store.saved is True
    assert raw_store.saved_payload.startswith(b"acquisition_date = ")
    assert update_service.saved_objects[-1].parent.image_id == 7
    assert update_service.saved_objects[-1].parent.loaded is False

    def _image_with_identifier(image_id, update_service, raw_store):
        """Image with identifier.

        Inputs: `image_id`, `update_service`, `raw_store`. Output: computed value or
        None.

        None.
        """

        class _ImageWithIdentifier:
            """Represent image with identifier."""

            _obj = "image-object"
            _conn = SimpleNamespace(
                getUpdateService=lambda: update_service,
                c=SimpleNamespace(
                    sf=SimpleNamespace(createRawFileStore=lambda: raw_store)
                ),
            )

            @staticmethod
            def getId():
                """Return the fake OMERO identifier.

                Inputs: none. Output: `image_id`.
                """
                return image_id

            @staticmethod
            def getAcquisitionDate():
                """Return Acquisition Date.

                Inputs: none. Output: `_Value` result.
                """
                return _Value("y" * 260)

            @staticmethod
            def getObjectiveSettings():
                """Return Objective Settings.

                Inputs: none. Output: None.
                """
                return None

            @staticmethod
            def getChannels():
                """Return Channels.

                Inputs: none. Output: list.
                """
                return []

            @staticmethod
            def getDetectorSettings():
                """Return Detector Settings.

                Inputs: none. Output: list.
                """
                return []

            @staticmethod
            def loadOriginalMetadata():
                """Return load original metadata.

                Inputs: none. Output: None.
                """
                return None

        return _ImageWithIdentifier()

    missing_id_update = _UpdateService()
    missing_id_cleaned = metadata_service.extract_acquisition_metadata(
        _image_with_identifier(None, missing_id_update, _RawStore())
    )
    assert missing_id_cleaned == {
        "acquisition_date": "[LONG_VALUE_NOT_STORED key=acquisition_date]",
    }
    assert missing_id_update.saved_objects == []

    invalid_id_update = _UpdateService()
    invalid_id_cleaned = metadata_service.extract_acquisition_metadata(
        _image_with_identifier("not-an-id", invalid_id_update, _RawStore())
    )
    assert invalid_id_cleaned == {
        "acquisition_date": "[LONG_VALUE_NOT_STORED key=acquisition_date]",
    }
    assert invalid_id_update.saved_objects == []

    class _ImageWithoutConnection:
        """Represent image without connection."""

        @staticmethod
        def getId():
            """Return the fake OMERO identifier.

            Inputs: none. Output: 11.
            """
            return 11

        @staticmethod
        def getAcquisitionDate():
            """Return Acquisition Date.

            Inputs: none. Output: `_Value` result.
            """
            return _Value("z" * 260)

        @staticmethod
        def getObjectiveSettings():
            """Return Objective Settings.

            Inputs: none. Output: None.
            """
            return None

        @staticmethod
        def getChannels():
            """Return Channels.

            Inputs: none. Output: list.
            """
            return []

        @staticmethod
        def getDetectorSettings():
            """Return Detector Settings.

            Inputs: none. Output: list.
            """
            return []

        @staticmethod
        def loadOriginalMetadata():
            """Return load original metadata.

            Inputs: none. Output: None.
            """
            return None

    no_connection_cleaned = metadata_service.extract_acquisition_metadata(
        _ImageWithoutConnection()
    )
    assert no_connection_cleaned == {
        "acquisition_date": "[LONG_VALUE_NOT_STORED key=acquisition_date]",
    }

    class _FailingRawStore(_RawStore):
        """Represent failing raw store."""

        def write(self, payload, offset, length):
            """Write data to the resource.

            Inputs: `payload`, `offset`, `length`. Output: None. Raises on invalid or
            unavailable state.
            """
            raise RuntimeError("write failed")

    failing_update = _UpdateService()
    failing_cleaned = metadata_service.extract_acquisition_metadata(
        _image_with_identifier(12, failing_update, _FailingRawStore())
    )
    assert failing_cleaned == {
        "acquisition_date": "[LONG_VALUE_NOT_STORED key=acquisition_date]",
    }
    assert len(failing_update.saved_objects) == 1
