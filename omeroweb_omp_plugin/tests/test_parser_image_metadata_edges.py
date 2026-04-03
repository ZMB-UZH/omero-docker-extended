from __future__ import annotations

from types import SimpleNamespace

import pytest

from omeroweb_omp_plugin.services.omero import image_service, metadata_service
from omeroweb_omp_plugin.services.parsing import filename_parser


class _Value:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _Image:
    def __init__(self, image_id, name, *, fileset=None):
        self.id = image_id
        self._name = name
        self._fileset = fileset

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return self._name

    def getFileset(self):
        if callable(self._fileset):
            return self._fileset()
        return self._fileset


class _Dataset:
    def __init__(self, dataset_id, name, images, *, owner_id=7):
        self.id = dataset_id
        self.owner_id = owner_id
        self._name = name
        self._images = list(images)

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return _Value(self._name)

    def listChildren(self):
        return list(self._images)


class _Project:
    def __init__(self, datasets):
        self._datasets = list(datasets)

    def listChildren(self):
        return list(self._datasets)


def test_filename_parser_covers_group_class_whitespace_and_validation_edges():
    assert filename_parser._parse_separator_fragment(r"\s") == ("", True)
    assert filename_parser._parse_separator_fragment(r"\.") == (".", False)
    assert filename_parser._extract_separator_fragments(r"[\.-]+") == ((".", "-"), False)
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
        def getObjects(self, object_type, ids=None, obj_ids=None):
            assert object_type == "Image"
            if ids is not None:
                raise TypeError("legacy signature")
            assert obj_ids == [1, 2]
            return [skipped_image, external_image]

    bulk_fetched = image_service.fetch_images_by_ids(_BulkConn(), [1, 2])
    assert bulk_fetched == {"external-id": external_image}

    class _FallbackConn:
        def getObjects(self, object_type, ids=None, obj_ids=None):
            raise RuntimeError("bulk fetch unavailable")

        def getObject(self, object_type, image_id):
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
        def listChildren(self):
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
        def __init__(self, *, format_value=None, name=None):
            self._format_value = format_value
            self._name = name

        def getFormat(self):
            return None if self._format_value is None else _Value(self._format_value)

        def getName(self):
            return self._name

    class _UsedFile:
        def __init__(self, original_file):
            self._original_file = original_file

        def getOriginalFile(self):
            if isinstance(self._original_file, Exception):
                raise self._original_file
            return self._original_file

    class _Fileset:
        def __init__(self, used_files=None, *, explode=False):
            self._used_files = list(used_files or [])
            self._explode = explode

        def copyUsedFiles(self):
            if self._explode:
                raise RuntimeError("copy failed")
            return list(self._used_files)

    class _RaisingName:
        def getValue(self):
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
    class _ObjectiveSettings:
        def getID(self):
            raise RuntimeError("missing objective id")

        def getCorrectionCollar(self):
            raise RuntimeError("missing collar")

    class _Channel:
        def getIndex(self):
            raise RuntimeError("missing index")

        def getLabel(self):
            raise RuntimeError("missing label")

        def getEmissionWave(self):
            raise RuntimeError("missing emission")

        def getExcitationWave(self):
            return "405"

    class _Detector:
        def getID(self):
            raise RuntimeError("missing detector id")

        def getBinning(self):
            raise RuntimeError("missing binning")

        def getGain(self):
            return "1.5"

    class _BrokenMetadata:
        def __len__(self):
            raise RuntimeError("len failed")

    class _ImageWithInnerFailures:
        def getId(self):
            return 7

        def getAcquisitionDate(self):
            return "2026-03-31T12:00:00"

        def getObjectiveSettings(self):
            return _ObjectiveSettings()

        def getChannels(self):
            return [_Channel()]

        def getDetectorSettings(self):
            return [_Detector()]

        def loadOriginalMetadata(self):
            return _BrokenMetadata()

    cleaned = metadata_service.extract_acquisition_metadata(_ImageWithInnerFailures())
    assert cleaned == {
        "acquisition_date": "2026-03-31T12:00:00",
        "channel_unknown_excitation": "405",
        "detector_unknown_gain": "1.5",
    }

    class _ImageWithOuterFailures:
        def getId(self):
            raise RuntimeError("missing id")

        def getAcquisitionDate(self):
            raise RuntimeError("no acquisition date")

        def getObjectiveSettings(self):
            raise RuntimeError("no objective")

        def getChannels(self):
            raise RuntimeError("no channels")

        def getDetectorSettings(self):
            raise RuntimeError("no detectors")

        def loadOriginalMetadata(self):
            raise RuntimeError("no metadata")

    assert (
        metadata_service.extract_acquisition_metadata(_ImageWithOuterFailures()) == {}
    )


def test_extract_acquisition_metadata_persists_long_values_despite_store_close_failure(
    monkeypatch,
):
    class _OriginalFileStub:
        def __init__(self):
            self._id = _Value(321)

        def setName(self, value):
            self.name = value

        def setPath(self, value):
            self.path = value

        def setSize(self, value):
            self.size = value

        def setMimetype(self, value):
            self.mimetype = value

        def getId(self):
            return self._id

    class _FileAnnotationStub:
        def setNs(self, value):
            self.ns = value

        def setFile(self, value):
            self.file = value

    class _ImageAnnotationLinkStub:
        def setParent(self, value):
            self.parent = value

        def setChild(self, value):
            self.child = value

    class _RawStore:
        def __init__(self):
            self.file_id = None
            self.saved_payload = None
            self.saved = False

        def setFileId(self, value):
            self.file_id = value

        def write(self, payload, offset, length):
            self.saved_payload = payload

        def save(self):
            self.saved = True

        def close(self):
            raise RuntimeError("close failed")

    class _UpdateService:
        def __init__(self):
            self.saved_objects = []

        def saveAndReturnObject(self, obj):
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
    monkeypatch.setattr(metadata_service, "rstring", lambda value: value)
    monkeypatch.setattr(metadata_service, "rlong", lambda value: value)

    class _ImageWithLongMetadata:
        _obj = "image-object"
        _conn = SimpleNamespace(
            getUpdateService=lambda: update_service,
            c=SimpleNamespace(sf=SimpleNamespace(createRawFileStore=lambda: raw_store)),
        )

        def getId(self):
            return 7

        def getAcquisitionDate(self):
            return _Value("x" * 260)

        def getObjectiveSettings(self):
            return None

        def getChannels(self):
            return []

        def getDetectorSettings(self):
            return []

        def loadOriginalMetadata(self):
            return None

    cleaned = metadata_service.extract_acquisition_metadata(_ImageWithLongMetadata())

    assert cleaned == {
        "acquisition_date": "[LONG_VALUE_STORED_IN_FILEANNOTATION key=acquisition_date]",
        "full_metadata_file": "FileAnnotation:321",
    }
    assert raw_store.file_id == 321
    assert raw_store.saved is True
    assert raw_store.saved_payload.startswith(b"acquisition_date = ")
