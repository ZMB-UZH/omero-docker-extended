from __future__ import annotations

from types import SimpleNamespace

from omeroweb_omp_plugin.services.omero import image_service, metadata_service


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

    def __init__(self, dataset_id, name, images, *, owned=True):
        """Create `_Dataset` with `dataset_id`, `name`, and `images`.

        Inputs: `dataset_id`, `name`, `images`, `owned`. Output: None.
        """
        self.id = dataset_id
        self._name = name
        self._images = list(images)
        self.owned = owned

    def getId(self):
        """Return `_Dataset`'s fake OMERO identifier.

        Inputs: none. Output: `_Value` result.
        """
        return _Value(self.id)

    def getName(self):
        """Return `_Dataset`'s fake object name.

        Inputs: none. Output: `self._name`.
        """
        return self._name

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


def test_image_service_fetch_and_collectors_cover_bulk_and_fallback_paths(monkeypatch):
    """Verify image service fetch and collectors cover bulk and fallback paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image service fetch and collectors cover bulk and fallback paths.
    RuntimeError, TypeError when validation or the called operation fails.
    """

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
            return [_Image(1, "one.tif"), _Image("2", "two.tif")]

    image_map = image_service.fetch_images_by_ids(_BulkConn(), [1, 2])
    assert sorted(image_map) == [1, 2]

    class _FallbackConn:
        """Test double for fallback conn behavior in this module."""

        @staticmethod
        def getObjects(object_type, ids=None, obj_ids=None):
            """Return the objects for `_FallbackConn`.

            Inputs: `object_type`, `ids`, `obj_ids`. Output: None. Raises: RuntimeError
            when validation or the called operation fails.
            """
            raise RuntimeError("bulk load unavailable")

        @staticmethod
        def getObject(object_type, image_id):
            """Return the object for `_FallbackConn`.

            Inputs: `object_type`, `image_id` OMERO image ID. Output: get object result.
            """
            assert object_type == "Image"
            return _Image(image_id, f"image-{image_id}.tif") if image_id == 3 else None

    assert image_service.fetch_images_by_ids(_FallbackConn(), [3, 4]).keys() == {3}
    assert image_service.fetch_images_by_ids(_FallbackConn(), []) == {}

    ds_a = _Dataset(
        10,
        "Dataset A",
        [_Image(5, "late.tif"), _Image(2, "early.tif"), _Image(None, "none.tif")],
        owned=True,
    )
    ds_b = _Dataset(11, "Dataset B", [_Image(7, "skip.tif")], owned=False)
    ds_c = _Dataset(12, "Dataset C", [_Image(8, "keep.tif")], owned=True)
    project = _Project([ds_a, ds_b, ds_c])
    monkeypatch.setattr(
        image_service, "is_owned_by_user", lambda dataset, owner_id: dataset.owned
    )
    conn = SimpleNamespace(getObject=lambda object_type, project_id: project)

    sorted_rows = image_service.collect_images_by_dataset_sorted(
        conn, "5", limit=2, owner_id=77
    )
    assert [
        (ds.getId().getValue(), [img.getId().getValue() for img in images])
        for ds, images in sorted_rows
    ] == [(10, [2, 5])]

    selected_rows = image_service.collect_images_by_selected_datasets(
        conn,
        "5",
        ["bad", "12", "10"],
        limit=3,
        owner_id=77,
    )
    assert [
        (ds.getId().getValue(), [img.getId().getValue() for img in images])
        for ds, images in selected_rows
    ] == [(10, [2, 5, None])]

    flat_images = image_service.collect_images_in_project(conn, "5", limit=2)
    assert [img.getId().getValue() for img in flat_images] == [5, 2]
    assert (
        image_service.collect_images_in_project(
            SimpleNamespace(getObject=lambda *_args: None), "5"
        )
        == []
    )

    ds_owned = _Dataset(13, "Owned", [_Image(9, "owned.tif")], owned=True)
    ds_skipped = _Dataset(14, "Skipped", [_Image(10, "skip.tif")], owned=False)
    non_owned_rows = image_service.collect_images_by_dataset_sorted(
        SimpleNamespace(getObject=lambda *_args: _Project([ds_owned, ds_skipped])),
        "5",
        owner_id=77,
    )
    assert [dataset.getId().getValue() for dataset, _images in non_owned_rows] == [13]

    class _BrokenSelectedProject:
        """Test double for broken selected project behavior in this module."""

        @staticmethod
        def listChildren():
            """Return `_BrokenSelectedProject`'s fake child listing.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("selected datasets unavailable")

    assert (
        image_service.collect_images_by_selected_datasets(
            SimpleNamespace(getObject=lambda *_args: _BrokenSelectedProject()),
            7,
            ["13"],
            owner_id=77,
        )
        == []
    )


def test_collect_dataset_summaries_detects_formats_across_metadata_fallbacks(
    monkeypatch,
):
    """Verify collect dataset summaries detects formats across metadata fallbacks.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in collect dataset summaries detects formats across metadata fallbacks.
    Raises: RuntimeError when validation or the called operation fails.
    """

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

            Inputs: none. Output: `self._original_file`.
            """
            return self._original_file

    class _Fileset:
        """Test double for fileset behavior in this module."""

        def __init__(self, used_files):
            """Create `_Fileset` with `used_files`.

            Inputs: `used_files`. Output: None.
            """
            self._used_files = list(used_files)

        def copyUsedFiles(self):
            """Copy the used Files for `_Fileset`.

            Inputs: none. Output: `list`.
            """
            return list(self._used_files)

    image_from_format = _Image(
        1,
        "format-source.tif",
        fileset=_Fileset([_UsedFile(_OriginalFile(format_value="image/czi"))]),
    )
    image_from_fileset_name = _Image(
        2,
        "ignored.png",
        fileset=_Fileset(
            [_UsedFile(_OriginalFile(format_value="text/plain", name="sample.ome.tif"))]
        ),
    )
    image_from_image_name = _Image(
        3,
        _Value("fallback.dv"),
        fileset=lambda: (_ for _ in ()).throw(RuntimeError("fileset unavailable")),
    )
    dataset_with_formats = _Dataset(
        21,
        "Formats",
        [image_from_format, image_from_fileset_name, image_from_image_name],
    )

    class _BrokenDataset(_Dataset):
        """Test double for broken dataset behavior in this module."""

        def listChildren(self):
            """Return `_BrokenDataset`'s fake child listing.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("images unavailable")

    dataset_unknown = _BrokenDataset(22, "Unknown", [])
    project = _Project([dataset_with_formats, dataset_unknown])
    monkeypatch.setattr(image_service, "is_owned_by_user", lambda *_args: True)
    conn = SimpleNamespace(getObject=lambda object_type, project_id: project)

    summaries = image_service.collect_dataset_summaries(conn, "7", owner_id=99)

    assert summaries == [
        {
            "id": "21",
            "name": "Formats",
            "image_count": 3,
            "formats": "DV, OME-TIFF, Zeiss CZI",
        },
        {
            "id": "22",
            "name": "Unknown",
            "image_count": 0,
            "formats": "Unknown",
        },
    ]


def test_extract_acquisition_metadata_handles_partial_failures_without_long_values():
    """Verify extract acquisition metadata handles partial failures without long values.

    Inputs: OMP service fakes. Output: fails on regressions in extract acquisition metadata handles partial failures without long values.
    """

    class _Image:
        """Test double for image behavior in this module."""

        @staticmethod
        def getId():
            """Return `_Image`'s fake OMERO identifier.

            Inputs: none. Output: 7.
            """
            return 7

        @staticmethod
        def getAcquisitionDate():
            """Return `_Image`'s fake acquisition date.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing acquisition date")

        @staticmethod
        def getObjectiveSettings():
            """Return `_Image`'s fake objective settings.

            Inputs: none. Output: `SimpleNamespace` result.
            """
            return SimpleNamespace(
                getID=lambda: "objective-1",
                getCorrectionCollar=lambda: 0.15,
            )

        @staticmethod
        def getChannels():
            """Return the channels for `_Image`.

            Inputs: none. Output: `list`.
            """
            return [
                SimpleNamespace(
                    getIndex=lambda: (_ for _ in ()).throw(RuntimeError("no index")),
                    getLabel=lambda: (_ for _ in ()).throw(RuntimeError("no label")),
                    getEmissionWave=lambda: 525,
                    getExcitationWave=lambda: _Value(488),
                )
            ]

        @staticmethod
        def getDetectorSettings():
            """Return `_Image`'s fake detector settings.

            Inputs: none. Output: list.
            """
            return [
                SimpleNamespace(
                    getID=lambda: (_ for _ in ()).throw(RuntimeError("no id")),
                    getBinning=lambda: "2x2",
                    getGain=lambda: (_ for _ in ()).throw(RuntimeError("no gain")),
                )
            ]

        @staticmethod
        def loadOriginalMetadata():
            """Return `_Image`'s fake original-metadata payload.

            Inputs: none. Output: tuple.
            """
            return (
                1,
                [("Exposure", "100ms"), ("broken",), ("Title", "short note")],
                [("Series", "A")],
            )

    cleaned = metadata_service.extract_acquisition_metadata(_Image())

    assert cleaned == {
        "objective_id": "objective-1",
        "objective_collar": "0.15",
        "channel_unknown_emission": "525",
        "channel_unknown_excitation": "488",
        "detector_unknown_binning": "2x2",
        "BF_Exposure": "100ms",
        "BF_Title": "short note",
        "BF_Series": "A",
    }


def test_image_and_metadata_services_cover_remaining_runtime_failure_paths(monkeypatch):
    """Verify image and metadata services cover remaining runtime failure paths.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in image and metadata services cover remaining runtime failure paths.
    RuntimeError when validation or the called operation fails.
    """

    class _BrokenMetadataTuple:
        """Test double for broken metadata tuple behavior in this module."""

        def __len__(self):
            """Return the instance length.

            Inputs: none. Output: 3.
            """
            return 3

        def __getitem__(self, index):
            """Return the item for the requested key.

            Inputs: `index`. Output: None. Raises: IndexError when validation or
            external operations fail.
            """
            raise IndexError(index)

        def __bool__(self):
            """Return the truth value for the instance.

            Inputs: none. Output: bool.
            """
            return True

    class _BrokenDetectorList:
        """Test double for broken detector list behavior in this module."""

        def __bool__(self):
            """Return the truth value for the instance.

            Inputs: none. Output: bool.
            """
            return True

        def __iter__(self):
            """Return an iterator for the instance.

            Inputs: none. Output: `_BrokenDetectorIterator` result. Raises: RuntimeError
            when validation or the called operation fails.
            """

            class _BrokenDetectorIterator:
                """Test double for broken detector iterator behavior in this module."""

                def __init__(self):
                    """Create `_BrokenDetectorIterator` with its default state.

                    Inputs: constructor receives no public arguments. Output: initializes fake state.
                    """
                    self._message = "detectors unavailable"

                def __iter__(self):
                    """Return an iterator for the instance.

                    Inputs: none. Output: `self`.
                    """
                    return self

                def __next__(self):
                    """Return the next iterator value.

                    Inputs: caller provides no extra arguments. Output: returns the fake value described above.
                    external operations fail.
                    """
                    raise RuntimeError(self._message)

            return _BrokenDetectorIterator()

    class _BrokenMetadataImage:
        """Test double for broken metadata image behavior in this module."""

        @staticmethod
        def getId():
            """Return `_BrokenMetadataImage`'s fake OMERO identifier.

            Inputs: none. Output: 1.
            """
            return 1

        @staticmethod
        def getAcquisitionDate():
            """Return `_BrokenMetadataImage`'s fake acquisition date.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        @staticmethod
        def getObjectiveSettings():
            """Return `_BrokenMetadataImage`'s fake objective settings.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        @staticmethod
        def getChannels():
            """Return the channels for `_BrokenMetadataImage`.

            Inputs: none. Output: `list`.
            """
            return []

        @staticmethod
        def getDetectorSettings():
            """Return `_BrokenMetadataImage`'s fake detector settings.

            Inputs: none. Output: `_BrokenDetectorList` result.
            """
            return _BrokenDetectorList()

        @staticmethod
        def loadOriginalMetadata():
            """Return `_BrokenMetadataImage`'s fake original-metadata payload.

            Inputs: none. Output: `_BrokenMetadataTuple` result.
            """
            return _BrokenMetadataTuple()

    assert metadata_service.extract_acquisition_metadata(_BrokenMetadataImage()) == {}

    class _BrokenMetadataImageWithoutId(_BrokenMetadataImage):
        """Test double for broken metadata image without identifier behavior in this module."""

        def getId(self):
            """Return `_BrokenMetadataImageWithoutId`'s fake OMERO identifier.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            raise RuntimeError("missing id")

    assert (
        metadata_service.extract_acquisition_metadata(_BrokenMetadataImageWithoutId())
        == {}
    )
