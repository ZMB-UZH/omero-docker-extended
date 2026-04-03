from __future__ import annotations

from types import SimpleNamespace

from omeroweb_omp_plugin.services.omero import image_service, metadata_service


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
    def __init__(self, dataset_id, name, images, *, owned=True):
        self.id = dataset_id
        self._name = name
        self._images = list(images)
        self.owned = owned

    def getId(self):
        return _Value(self.id)

    def getName(self):
        return self._name

    def listChildren(self):
        return list(self._images)


class _Project:
    def __init__(self, datasets):
        self._datasets = list(datasets)

    def listChildren(self):
        return list(self._datasets)


def test_image_service_fetch_and_collectors_cover_bulk_and_fallback_paths(monkeypatch):
    class _BulkConn:
        def getObjects(self, object_type, ids=None, obj_ids=None):
            assert object_type == "Image"
            if ids is not None:
                raise TypeError("legacy signature")
            assert obj_ids == [1, 2]
            return [_Image(1, "one.tif"), _Image("2", "two.tif")]

    image_map = image_service.fetch_images_by_ids(_BulkConn(), [1, 2])
    assert sorted(image_map) == [1, 2]

    class _FallbackConn:
        def getObjects(self, object_type, ids=None, obj_ids=None):
            raise RuntimeError("bulk load unavailable")

        def getObject(self, object_type, image_id):
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
        def listChildren(self):
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
            return self._original_file

    class _Fileset:
        def __init__(self, used_files):
            self._used_files = list(used_files)

        def copyUsedFiles(self):
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
        def listChildren(self):
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
    class _Image:
        def getId(self):
            return 7

        def getAcquisitionDate(self):
            raise RuntimeError("missing acquisition date")

        def getObjectiveSettings(self):
            return SimpleNamespace(
                getID=lambda: "objective-1",
                getCorrectionCollar=lambda: 0.15,
            )

        def getChannels(self):
            return [
                SimpleNamespace(
                    getIndex=lambda: (_ for _ in ()).throw(RuntimeError("no index")),
                    getLabel=lambda: (_ for _ in ()).throw(RuntimeError("no label")),
                    getEmissionWave=lambda: 525,
                    getExcitationWave=lambda: _Value(488),
                )
            ]

        def getDetectorSettings(self):
            return [
                SimpleNamespace(
                    getID=lambda: (_ for _ in ()).throw(RuntimeError("no id")),
                    getBinning=lambda: "2x2",
                    getGain=lambda: (_ for _ in ()).throw(RuntimeError("no gain")),
                )
            ]

        def loadOriginalMetadata(self):
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
    class _BrokenMetadataTuple:
        def __len__(self):
            return 3

        def __getitem__(self, index):
            raise RuntimeError(f"bad index {index}")

        def __bool__(self):
            return True

    class _BrokenMetadataImage:
        def getId(self):
            raise RuntimeError("missing id")

        def getAcquisitionDate(self):
            return None

        def getObjectiveSettings(self):
            return None

        def getChannels(self):
            return []

        def getDetectorSettings(self):
            class _BrokenDetectorList:
                def __bool__(self):
                    raise RuntimeError("detectors unavailable")

            return _BrokenDetectorList()

        def loadOriginalMetadata(self):
            return _BrokenMetadataTuple()

    assert metadata_service.extract_acquisition_metadata(_BrokenMetadataImage()) == {}
