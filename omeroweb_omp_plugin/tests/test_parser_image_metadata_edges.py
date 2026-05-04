from __future__ import annotations

from types import SimpleNamespace

import pytest

from omeroweb_omp_plugin.services.omero import image_service, metadata_service
from omeroweb_omp_plugin.services.parsing import filename_parser


class _Value:
    """Test double for value behavior in this module."""

    def __init__(self, value):
        """Create `_Value` with `value`.

        Inputs: `value`. Output: None.
        """
        self._raw_value = value

    def getValue(self):
        """Return `_Value`'s fake OMERO value.

        Inputs: none. Output: `self._raw_value`.
        """
        return self._raw_value


class _Image:
    """Test double for image behavior in this module."""

    def __init__(self, image_id, name, *, fileset=None):
        """Create `_Image` with `image_id` and `name`.

        Inputs: `image_id`, `name`, `fileset`. Output: None.
        """
        self.id = image_id
        self._name = name
        self._fileset = fileset

    def getId(self):
        """Return `_Image`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_Image`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

    def getFileset(self):
        """Return the fileset for `_Image`.

        Inputs: none. Output: `_fileset`.
        """
        if callable(self._fileset):
            return self._fileset()
        return self._fileset


class _Dataset:
    """Test double for dataset behavior in this module."""

    def __init__(self, dataset_id, name, images, *, owner_id=7):
        """Create `_Dataset` with `dataset_id`, `name`, and `images`.

        Inputs: `dataset_id`, `name`, `images`, `owner_id`. Output: None.
        """
        self.id = dataset_id
        self.owner_id = owner_id
        self._name = name
        self._images = list(images)

    def getId(self):
        """Return `_Dataset`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_Dataset`'s fake object name.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self._name)

    def listChildren(self):
        """Return `_Dataset`'s fake child listing.

        Inputs: none. Output: `list` result.
        """
        return list(self._images)


class _Project:
    """Test double for project behavior in this module."""

    def __init__(self, datasets):
        """Create `_Project` with `datasets`.

        Inputs: `datasets`. Output: None.
        """
        self._datasets = list(datasets)

    def listChildren(self):
        """Return `_Project`'s fake child listing.

        Inputs: none. Output: `list` result.
        """
        return list(self._datasets)


def test_filename_parser_covers_group_class_whitespace_and_validation_edges():
    """Check filename parser covers group class whitespace and validation edges parsing against the documented contract.

    Inputs: OMP service fakes. Output: fails on regressions in filename parser covers group class whitespace and validation edges.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image service covers runtime fallbacks and format detection edges.
    RuntimeError, TypeError, _original_file when validation or the called operation fails.
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
        """Test double for bulk conn behavior in this module."""

        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            """Return the objects for `_BulkConn`.

            Inputs: `object_type`, `ids`, `obj_ids`. Output: `list`. Raises: TypeError
            when validation or the called operation fails.
            """
            assert object_type == "Image"
            if ids is not None:
                raise TypeError("legacy signature")
            assert obj_ids == [1, 2]
            return [skipped_image, external_image]

    bulk_fetched = image_service.fetch_images_by_ids(_BulkConn(), [1, 2])
    assert bulk_fetched == {"external-id": external_image}

    class _FallbackConn:
        """Test double for fallback conn behavior in this module."""

        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            """Return the objects for `_FallbackConn`.

            Inputs: `object_type`, `ids`, `obj_ids`. Output: None. Raises: RuntimeError
            when validation or the called operation fails.
            """
            raise RuntimeError("bulk fetch unavailable")

        @staticmethod
        def getObject(object_type, image_id):
            """Return the object for `_FallbackConn`.

            Inputs: `object_type`, `image_id` OMERO image ID. Output: `_Image` result.
            Raises: RuntimeError when validation or the called operation fails.
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
        """Test double for broken project behavior in this module."""

        @staticmethod
        def listChildren():
            """Return `_BrokenProject`'s fake child listing.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
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
        """Test double for original file behavior in this module."""

        def __init__(self, *, format_value=None, name=None):
            """Create `_OriginalFile` with its default state.

            Inputs: `format_value`, `name`. Output: None.
            """
            self._format_value = format_value
            self._name = name

        def getFormat(self):
            """Return the format for `_OriginalFile`.

            Inputs: none. Output: get format result.
            """
            return None if self._format_value is None else _Value(self._format_value)

        def getName(self):
            """Return `_OriginalFile`'s fake object name.

            Inputs: none. Output: `self._name`.
            """
            return self._name

    class _UsedFile:
        """Test double for used file behavior in this module."""

        def __init__(self, original_file):
            """Create `_UsedFile` with `original_file`.

            Inputs: `original_file`. Output: None.
            """
            self._original_file = original_file

        def getOriginalFile(self):
            """Return `_UsedFile`'s fake original file.

            Inputs: none. Output: `_original_file`. Raises: _original_file when validation or the called operation fails.
            """
            if isinstance(self._original_file, Exception):
                raise self._original_file
            return self._original_file

    class _Fileset:
        """Test double for fileset behavior in this module."""

        def __init__(self, used_files=None, *, explode=False):
            """Create `_Fileset` with `used_files`.

            Inputs: `used_files`, `explode`. Output: None.
            """
            self._used_files = list(used_files or [])
            self._explode = explode

        def copyUsedFiles(self):
            """Copy the used Files for `_Fileset`.

            Inputs: none. Output: `list`. Raises: RuntimeError when validation or
            external operations fail.
            """
            if self._explode:
                raise RuntimeError("copy failed")
            return list(self._used_files)

    class _RaisingName:
        """Test double for raising name behavior in this module."""

        @staticmethod
        def getValue():
            """Return `_RaisingName`'s fake OMERO value.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
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
    """Confirm extract acquisition metadata covers inner fallbacks and outer error logging exposes the expected failure.

    Inputs: OMP service fakes. Output: fails on regressions when extract acquisition metadata covers inner fallbacks and outer error logging stops reporting the expected error.
    """

    class _ObjectiveSettings:
        """Test double for objective settings behavior in this module."""

        @staticmethod
        def getID():
            """Return the ID for `_ObjectiveSettings`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing objective id")

        @staticmethod
        def getCorrectionCollar():
            """Return the fake correction collar value used by this test double.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing collar")

    class _Channel:
        """Test double for channel behavior in this module."""

        @staticmethod
        def getIndex():
            """Return the index for `_Channel`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing index")

        @staticmethod
        def getLabel():
            """Return the label for `_Channel`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing label")

        @staticmethod
        def getEmissionWave():
            """Return the fake emission wave value used by this test double.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing emission")

        @staticmethod
        def getExcitationWave():
            """Return the fake excitation wave value used by this test double.

            Inputs: none. Output: '405'.
            """
            return "405"

    class _Detector:
        """Test double for detector behavior in this module."""

        @staticmethod
        def getID():
            """Return the ID for `_Detector`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing detector id")

        @staticmethod
        def getBinning():
            """Return the binning for `_Detector`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing binning")

        @staticmethod
        def getGain():
            """Return the gain for `_Detector`.

            Inputs: none. Output: `str`.
            """
            return "1.5"

    class _BrokenMetadata:
        """Test double for broken metadata behavior in this module."""

        def __len__(self):
            """Return the instance length.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("len failed")

    class _ImageWithInnerFailures:
        """Test double for image with inner failures behavior in this module."""

        @staticmethod
        def getId():
            """Return `_ImageWithInnerFailures`'s fake OMERO identifier.

            Inputs: none. Output: 7.
            """
            return 7

        @staticmethod
        def getAcquisitionDate():
            """Return `_ImageWithInnerFailures`'s fake acquisition date.

            Inputs: none. Output: '2026-03-31T12:00:00'.
            """
            return "2026-03-31T12:00:00"

        @staticmethod
        def getObjectiveSettings():
            """Return `_ImageWithInnerFailures`'s fake objective settings.

            Inputs: none. Output: `_ObjectiveSettings` result.
            """
            return _ObjectiveSettings()

        @staticmethod
        def getChannels():
            """Return the channels for `_ImageWithInnerFailures`.

            Inputs: none. Output: `list`.
            """
            return [_Channel()]

        @staticmethod
        def getDetectorSettings():
            """Return `_ImageWithInnerFailures`'s fake detector settings.

            Inputs: none. Output: list.
            """
            return [_Detector()]

        @staticmethod
        def loadOriginalMetadata():
            """Return `_ImageWithInnerFailures`'s fake original-metadata payload.

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
        """Test double for image with outer failures behavior in this module."""

        @staticmethod
        def getId():
            """Return `_ImageWithOuterFailures`'s fake OMERO identifier.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing id")

        @staticmethod
        def getAcquisitionDate():
            """Return `_ImageWithOuterFailures`'s fake acquisition date.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no acquisition date")

        @staticmethod
        def getObjectiveSettings():
            """Return `_ImageWithOuterFailures`'s fake objective settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no objective")

        @staticmethod
        def getChannels():
            """Return the channels for `_ImageWithOuterFailures`.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no channels")

        @staticmethod
        def getDetectorSettings():
            """Return `_ImageWithOuterFailures`'s fake detector settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no detectors")

        @staticmethod
        def loadOriginalMetadata():
            """Return `_ImageWithOuterFailures`'s fake original-metadata payload.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("no metadata")

    assert (
        metadata_service.extract_acquisition_metadata(_ImageWithOuterFailures()) == {}
    )


def test_extract_acquisition_metadata_persists_long_values_despite_store_close_failure(
    monkeypatch,
):
    """Verify extract acquisition metadata persists long values despite store close failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in extract acquisition metadata persists long values despite store close failure.
    Raises: RuntimeError when validation or the called operation fails.
    """

    class _OriginalFileStub:
        """Test double for original file stub behavior in this module."""

        def __init__(self):
            """Create `_OriginalFileStub` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self._id = _Value(321)

        def setName(self, value):
            """Set the name for `_OriginalFileStub`.

            Inputs: `value` input value. Output: None.
            """
            self.name = value

        def setPath(self, value):
            """Set the path for `_OriginalFileStub`.

            Inputs: `value` input value. Output: None.
            """
            self.path = value

        def setSize(self, value):
            """Set the size for `_OriginalFileStub`.

            Inputs: `value` input value. Output: None.
            """
            self.size = value

        def setMimetype(self, value):
            """Set the mimetype for `_OriginalFileStub`.

            Inputs: `value` input value. Output: None.
            """
            self.mimetype = value

        def getId(self):
            """Return `_OriginalFileStub`'s fake OMERO identifier.

            Inputs: none. Output: `self._id`.
            """
            return self._id

    class _FileAnnotationStub:
        """Test double for file annotation stub behavior in this module."""

        def setNs(self, value):
            """Set the ns for `_FileAnnotationStub`.

            Inputs: `value` input value. Output: None.
            """
            self.ns = value

        def setFile(self, value):
            """Set the file for `_FileAnnotationStub`.

            Inputs: `value` input value. Output: None.
            """
            self.file = value

    class _ImageAnnotationLinkStub:
        """Test double for image annotation link stub behavior in this module."""

        def setParent(self, value):
            """Set the parent for `_ImageAnnotationLinkStub`.

            Inputs: `value` input value. Output: None.
            """
            self.parent = value

        def setChild(self, value):
            """Set the child for `_ImageAnnotationLinkStub`.

            Inputs: `value` input value. Output: None.
            """
            self.child = value

    class _ImageStub:
        """Test double for image stub behavior in this module."""

        def __init__(self, image_id, loaded):
            """Create `_ImageStub` with `image_id` and `loaded`.

            Inputs: `image_id`, `loaded`. Output: None.
            """
            self.image_id = image_id
            self.loaded = loaded

    class _RawStore:
        """Test double for raw store behavior in this module."""

        def __init__(self):
            """Create `_RawStore` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.file_id = None
            self.saved_payload = None
            self.saved = False

        def setFileId(self, value):
            """Set the file ID for `_RawStore`.

            Inputs: `value` input value. Output: None.
            """
            self.file_id = value

        def write(self, payload, offset, length):
            """Write data to the resource.

            Inputs: `payload`, `offset`, `length`. Output: None.
            """
            self.saved_payload = payload

        def save(self):
            """Persist `_RawStore`'s fake object state.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            """
            self.saved = True

        @staticmethod
        def close():
            """Close `_RawStore`'s fake resource handle.

            Inputs: caller provides no extra arguments. Output: records the fake side effect.
            """
            raise RuntimeError("close failed")

    class _UpdateService:
        """Test double for update service behavior in this module."""

        def __init__(self):
            """Create `_UpdateService` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.saved_objects = []

        def saveAndReturnObject(self, obj):
            """Return the fake saved OMERO object from parser metadata tests.

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
        """Test double for image with long metadata behavior in this module."""

        _obj = "image-object"
        _conn = SimpleNamespace(
            getUpdateService=lambda: update_service,
            c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
        )

        @staticmethod
        def getId():
            """Return `_ImageWithLongMetadata`'s fake OMERO identifier.

            Inputs: none. Output: 7.
            """
            return 7

        @staticmethod
        def getAcquisitionDate():
            """Return `_ImageWithLongMetadata`'s fake acquisition date.

            Inputs: none. Output: `_Value` result.
            """
            return _Value("x" * 260)

        @staticmethod
        def getObjectiveSettings():
            """Return `_ImageWithLongMetadata`'s fake objective settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        @staticmethod
        def getChannels():
            """Return the channels for `_ImageWithLongMetadata`.

            Inputs: none. Output: `list`.
            """
            return []

        @staticmethod
        def getDetectorSettings():
            """Return `_ImageWithLongMetadata`'s fake detector settings.

            Inputs: none. Output: list.
            """
            return []

        @staticmethod
        def loadOriginalMetadata():
            """Return `_ImageWithLongMetadata`'s fake original-metadata payload.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
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
        """Return the image with identifier.

        Inputs: `image_id` OMERO image ID, `update_service`, `raw_store`. Output:
        `_ImageWithIdentifier` result.
        """

        class _ImageWithIdentifier:
            """Test double for image with identifier behavior in this module."""

            _obj = "image-object"
            _conn = SimpleNamespace(
                getUpdateService=lambda: update_service,
                c=SimpleNamespace(
                    sf=SimpleNamespace(createRawFileStore=lambda: raw_store)
                ),
            )

            @staticmethod
            def getId():
                """Return `_ImageWithIdentifier`'s fake OMERO identifier.

                Inputs: none. Output: `image_id`.
                """
                return image_id

            @staticmethod
            def getAcquisitionDate():
                """Return `_ImageWithIdentifier`'s fake acquisition date.

                Inputs: none. Output: `_Value` result.
                """
                return _Value("y" * 260)

            @staticmethod
            def getObjectiveSettings():
                """Return `_ImageWithIdentifier`'s fake objective settings.

                Inputs: caller provides no extra arguments. Output: returns the fake value described above.
                """
                return None

            @staticmethod
            def getChannels():
                """Return the channels for `_ImageWithIdentifier`.

                Inputs: none. Output: `list`.
                """
                return []

            @staticmethod
            def getDetectorSettings():
                """Return `_ImageWithIdentifier`'s fake detector settings.

                Inputs: none. Output: list.
                """
                return []

            @staticmethod
            def loadOriginalMetadata():
                """Return `_ImageWithIdentifier`'s fake original-metadata payload.

                Inputs: caller provides no extra arguments. Output: returns the fake value described above.
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
        """Test double for image without connection behavior in this module."""

        @staticmethod
        def getId():
            """Return `_ImageWithoutConnection`'s fake OMERO identifier.

            Inputs: none. Output: 11.
            """
            return 11

        @staticmethod
        def getAcquisitionDate():
            """Return `_ImageWithoutConnection`'s fake acquisition date.

            Inputs: none. Output: `_Value` result.
            """
            return _Value("z" * 260)

        @staticmethod
        def getObjectiveSettings():
            """Return `_ImageWithoutConnection`'s fake objective settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        @staticmethod
        def getChannels():
            """Return the channels for `_ImageWithoutConnection`.

            Inputs: none. Output: `list`.
            """
            return []

        @staticmethod
        def getDetectorSettings():
            """Return `_ImageWithoutConnection`'s fake detector settings.

            Inputs: none. Output: list.
            """
            return []

        @staticmethod
        def loadOriginalMetadata():
            """Return `_ImageWithoutConnection`'s fake original-metadata payload.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

    no_connection_cleaned = metadata_service.extract_acquisition_metadata(
        _ImageWithoutConnection()
    )
    assert no_connection_cleaned == {
        "acquisition_date": "[LONG_VALUE_NOT_STORED key=acquisition_date]",
    }

    class _FailingRawStore(_RawStore):
        """Test double for failing raw store behavior in this module."""

        def write(self, payload, offset, length):
            """Write data to the resource.

            Inputs: `payload` payload, `offset`, `length`. Output: None. Raises:
            RuntimeError when validation or the called operation fails.
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
