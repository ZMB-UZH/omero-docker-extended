from __future__ import annotations

import builtins
import json
from pathlib import Path

import numcodecs
import numpy as np
import zarr

from omeroweb_import.services import ome_zarr_support as support


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_ome_zarr_support_covers_additional_root_and_single_image_validation_paths(
    tmp_path: Path,
) -> None:
    not_a_directory = tmp_path / "not-a-directory"
    not_a_directory.write_text("payload", encoding="utf-8")
    payload, inspection = support._load_root_ome_zarr_metadata(not_a_directory)
    assert payload is None
    assert inspection.recognized is False

    invalid = tmp_path / "invalid.ome.zarr"
    _write_json(invalid / ".zattrs", ["bad-payload"])
    payload, inspection = support._load_root_ome_zarr_metadata(invalid)
    assert payload is None
    assert "Invalid OME-Zarr metadata payload" in (inspection.support_error or "")

    well_layout = tmp_path / "well.ome.zarr"
    _write_json(well_layout / ".zattrs", {"well": {"path": "A/1"}})
    payload, inspection = support._load_root_ome_zarr_metadata(well_layout)
    assert payload is None
    assert "well layouts are not supported" in (inspection.support_error or "")

    assert "no multiscale image definition" in (
        support._inspect_single_ome_zarr_image(tmp_path, {}).support_error or ""
    )
    assert "multiple image nodes" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {
                        "axes": [{"name": "x"}, {"name": "y"}],
                        "datasets": [{"path": "0"}],
                    },
                    {
                        "axes": [{"name": "x"}, {"name": "y"}],
                        "datasets": [{"path": "1"}],
                    },
                ]
            },
        ).support_error
        or ""
    )
    assert "malformed" in (
        support._inspect_single_ome_zarr_image(
            tmp_path, {"multiscales": ["bad-multiscale"]}
        ).support_error
        or ""
    )
    assert "include x and y" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": "z"}],
                        "datasets": [{"path": "0"}],
                    }
                ]
            },
        ).support_error
        or ""
    )
    assert "missing multiscale dataset entries" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {"version": "0.4", "axes": [{"name": "y"}, {"name": "x"}]}
                ]
            },
        ).support_error
        or ""
    )
    assert "primary dataset metadata is malformed" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": "y"}, {"name": "x"}],
                        "datasets": ["bad-dataset"],
                    }
                ]
            },
        ).support_error
        or ""
    )
    assert "missing a readable dataset path" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": "y"}, {"name": "x"}],
                        "datasets": [{"path": "  "}],
                    }
                ]
            },
        ).support_error
        or ""
    )


def test_inspect_bioformats2raw_layout_covers_empty_and_invalid_series_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    empty_store = tmp_path / "bf2raw-empty.ome.zarr"
    empty_store.mkdir()
    inspection = support._inspect_bioformats2raw_layout(empty_store)
    assert "does not contain any numeric series directories" in (
        inspection.support_error or ""
    )

    store = tmp_path / "bf2raw-invalid.ome.zarr"
    store.mkdir()
    (store / "0").mkdir()
    (store / "1").mkdir()
    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda series_dir: (
            None,
            support.OMEZarrImageInspection(
                recognized=True,
                support_error=f"{series_dir.name}-not-supported",
            ),
        ),
    )
    invalid = support._inspect_bioformats2raw_layout(store)
    assert invalid.recognized is True
    assert "Series 0 is not a supported OME-Zarr image" in (invalid.support_error or "")


def test_rewrite_problematic_native_image_arrays_covers_additional_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inspection = support.OMEZarrImageInspection(
        recognized=True,
        kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
        image_relative_paths=("0",),
    )

    missing_metadata = tmp_path / "missing.ome.zarr"
    missing_metadata.mkdir()
    assert "missing its .zarray metadata" in (
        support._rewrite_problematic_native_image_arrays(missing_metadata, inspection)
        or ""
    )

    invalid_metadata = tmp_path / "invalid.ome.zarr"
    (invalid_metadata / "0").mkdir(parents=True)
    (invalid_metadata / "0" / ".zarray").write_text("{broken", encoding="utf-8")
    assert "Failed to read OME-Zarr array metadata" in (
        support._rewrite_problematic_native_image_arrays(invalid_metadata, inspection)
        or ""
    )

    bad_codec_store = tmp_path / "bad-codec.ome.zarr"
    (bad_codec_store / "0").mkdir(parents=True)
    _write_json(
        bad_codec_store / "0" / ".zarray",
        {
            "zarr_format": 2,
            "shape": [1],
            "chunks": [1],
            "dtype": "|u1",
            "compressor": {"id": "blosc"},
            "fill_value": 0,
            "filters": None,
            "order": "C",
        },
    )
    monkeypatch.setattr(
        numcodecs,
        "get_codec",
        lambda _spec: (_ for _ in ()).throw(RuntimeError("codec exploded")),
    )
    assert "Failed to load OME-Zarr compressor" in (
        support._rewrite_problematic_native_image_arrays(bad_codec_store, inspection)
        or ""
    )


def test_regenerate_xy_only_pyramid_covers_metadata_and_runtime_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = tmp_path / "pyramid.ome.zarr"
    store.mkdir()

    detection = {
        "metadata_payload": {
            "multiscales": [{"datasets": [{"path": "s0"}, {"path": "s1"}]}]
        },
        "multiscale": {"datasets": [{"path": "s0"}, {"path": "s1"}]},
        "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}],
        "datasets": [{"path": "s0"}, {"path": "s1"}],
        "z_axis_index": 0,
        "yx_indices": [1, 2],
        "s0_path": "s0",
    }
    monkeypatch.setattr(
        support,
        "_has_3d_pyramid_downsampling",
        lambda _store_root: detection,
    )

    assert "Failed to read s0 .zarray metadata" in (
        support._regenerate_xy_only_pyramid(store) or ""
    )

    _write_json(
        store / "s0" / ".zarray",
        {
            "chunks": [1, 2, 2],
            "dtype": "|u1",
            "compressor": None,
            "filters": None,
        },
    )
    assert "missing or malformed" in (support._regenerate_xy_only_pyramid(store) or "")

    _write_json(
        store / "s0" / ".zarray",
        {
            "chunks": [1, 2, 2],
            "dtype": "|u1",
            "compressor": None,
            "filters": None,
        },
    )
    detection["datasets"][0]["coordinateTransformations"] = [
        {"type": "scale", "scale": [1.0, 1.0, 1.0]}
    ]
    monkeypatch.setattr(
        zarr,
        "open_array",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("reader exploded")),
    )
    assert "Failed to read full-resolution data" in (
        support._regenerate_xy_only_pyramid(store) or ""
    )


def test_normalize_native_ome_zarr_copy_propagates_support_and_transform_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = tmp_path / "image.ome.zarr"
    unsupported = support.OMEZarrImageInspection(
        recognized=True,
        support_error="unsupported runtime",
    )
    normalized = support.OMEZarrImageInspection(
        recognized=True,
        kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
    )
    inspections = iter([unsupported, normalized, unsupported])
    monkeypatch.setattr(
        support, "inspect_ome_zarr_image", lambda _path: next(inspections)
    )
    assert support.normalize_native_ome_zarr_copy(store) == "unsupported runtime"

    monkeypatch.setattr(
        support,
        "inspect_ome_zarr_image",
        lambda _path: normalized,
    )
    monkeypatch.setattr(
        support,
        "_rewrite_problematic_native_image_arrays",
        lambda *_args: "rewrite exploded",
    )
    assert support.normalize_native_ome_zarr_copy(store) == "rewrite exploded"

    monkeypatch.setattr(
        support,
        "_rewrite_problematic_native_image_arrays",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        support,
        "_regenerate_xy_only_pyramid",
        lambda *_args: "pyramid exploded",
    )
    assert support.normalize_native_ome_zarr_copy(store) == "pyramid exploded"


def test_ome_zarr_support_additional_metadata_helpers_cover_edge_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda _path: (None, None),
    )
    inspection = support.inspect_ome_zarr_image(tmp_path / "missing.ome.zarr")
    assert inspection.recognized is False
    assert "unexpectedly None" in (inspection.support_error or "")

    assert support._read_zarr_format_metadata(tmp_path, {"zarr_format": 3}) == 3

    _write_json(tmp_path / "array" / "zarr.json", ["bad-array"])
    payload, error = support._read_array_metadata_payload(tmp_path, "array")
    assert payload is None
    assert "must be a JSON object" in (error or "")

    assert support._extract_axes(None) == (
        [],
        {},
        "OME-Zarr metadata is missing multiscale axes information.",
    )
    assert support._extract_axes(["bad-axis"])[2] == (
        "OME-Zarr axes must be described by metadata objects."
    )
    assert support._extract_dataset_relative_paths(
        {
            "multiscales": [
                "bad-multiscale",
                {"datasets": ["bad-dataset", {"path": "0"}, {"path": "0"}]},
            ]
        }
    ) == ("0",)

    class _BrokenDType:
        def __str__(self):
            return "custom-dtype"

    monkeypatch.setattr(
        np,
        "dtype",
        lambda raw_dtype: (_ for _ in ()).throw(TypeError("bad dtype")),
    )
    assert support._normalize_dtype_name(_BrokenDType()) == "custom-dtype"


def test_single_and_bioformats_inspection_cover_scale_array_and_series_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert "not numeric" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": "y"}, {"name": "x"}],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": ["bad", 1.0]}
                                ],
                            }
                        ],
                    }
                ]
            },
        ).support_error
        or ""
    )

    assert "missing its array metadata" in (
        support._inspect_single_ome_zarr_image(
            tmp_path,
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": "y"}, {"name": "x"}],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, 1.0]}
                                ],
                            }
                        ],
                    }
                ]
            },
        ).support_error
        or ""
    )

    store = tmp_path / "bf2raw-supported.ome.zarr"
    (store / "0").mkdir(parents=True)
    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda _path: ({}, None),
    )
    monkeypatch.setattr(
        support,
        "_inspect_single_ome_zarr_image",
        lambda _store_root, _metadata: support.OMEZarrImageInspection(
            recognized=True,
            support_error="series inspection failed",
        ),
    )
    inspection = support._inspect_bioformats2raw_layout(store)
    assert inspection.recognized is True
    assert "Series 0 is not a supported OME-Zarr image" in (
        inspection.support_error or ""
    )


def test_normalization_and_pyramid_helpers_cover_additional_runtime_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = tmp_path / "normalized.ome.zarr"
    original_rewrite = support._rewrite_problematic_native_image_arrays
    supported = support.OMEZarrImageInspection(
        recognized=True,
        kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
    )
    unsupported = support.OMEZarrImageInspection(
        recognized=True,
        support_error="normalized copy is unsupported",
    )
    inspections = iter([supported, unsupported])
    monkeypatch.setattr(
        support, "inspect_ome_zarr_image", lambda _path: next(inspections)
    )
    monkeypatch.setattr(
        support,
        "_rewrite_problematic_native_image_arrays",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        support,
        "_regenerate_xy_only_pyramid",
        lambda *_args: None,
    )
    assert support.normalize_native_ome_zarr_copy(store) == (
        "normalized copy is unsupported"
    )

    inspection = support.OMEZarrImageInspection(
        recognized=True, image_relative_paths=()
    )
    monkeypatch.setattr(
        support,
        "_rewrite_problematic_native_image_arrays",
        original_rewrite,
    )
    assert support._rewrite_problematic_native_image_arrays(store, inspection) is None

    gzip_store = tmp_path / "gzip.ome.zarr"
    (gzip_store / "0").mkdir(parents=True)
    _write_json(
        gzip_store / "0" / ".zarray",
        {
            "zarr_format": 2,
            "shape": [1],
            "chunks": [1],
            "dtype": "|u1",
            "compressor": {"id": "gzip", "level": 1},
            "fill_value": 0,
            "filters": None,
            "order": "C",
        },
    )
    assert (
        support._rewrite_problematic_native_image_arrays(
            gzip_store,
            support.OMEZarrImageInspection(
                recognized=True,
                kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
                image_relative_paths=("0",),
            ),
        )
        is None
    )

    failing_store = tmp_path / "rewrite-error.ome.zarr"
    (failing_store / "0").mkdir(parents=True)
    compressor_spec = {"id": "blosc", "cname": "zstd", "clevel": 1, "shuffle": 0}
    _write_json(
        failing_store / "0" / ".zarray",
        {
            "zarr_format": 2,
            "shape": [1],
            "chunks": [1],
            "dtype": "|u1",
            "compressor": compressor_spec,
            "fill_value": 0,
            "filters": None,
            "order": "C",
        },
    )
    (failing_store / "0" / "0").write_bytes(
        numcodecs.get_codec(compressor_spec).encode(b"\x01")
    )
    original_write_text = Path.write_text

    def _failing_write_text(self, text, encoding=None):
        if self == failing_store / "0" / ".zarray":
            raise OSError("metadata write exploded")
        return original_write_text(self, text, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", _failing_write_text)
    assert "Failed to update OME-Zarr compressor metadata" in (
        support._rewrite_problematic_native_image_arrays(
            failing_store,
            support.OMEZarrImageInspection(
                recognized=True,
                kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
                image_relative_paths=("0",),
            ),
        )
        or ""
    )


def test_pyramid_and_runtime_helpers_cover_more_regeneration_error_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    metadata_store = tmp_path / "detect.ome.zarr"
    metadata_store.mkdir()
    monkeypatch.setattr(
        support,
        "_read_store_metadata_payload",
        lambda _store_root: ("bad-payload", None),
    )
    assert support._has_3d_pyramid_downsampling(metadata_store) is None

    monkeypatch.setattr(
        support,
        "_read_store_metadata_payload",
        lambda _store_root: ({"multiscales": ["bad-multiscale"]}, None),
    )
    assert support._has_3d_pyramid_downsampling(metadata_store) is None

    monkeypatch.setattr(
        support,
        "_read_store_metadata_payload",
        lambda _store_root: (
            {
                "multiscales": [
                    {
                        "axes": ["bad-axis", {"name": "y"}, {"name": "x"}],
                        "datasets": [{"path": "s0"}, {"path": "s1"}],
                    }
                ]
            },
            None,
        ),
    )
    assert support._has_3d_pyramid_downsampling(metadata_store) is None

    pyramid_store = tmp_path / "pyramid-extra.ome.zarr"
    pyramid_store.mkdir()
    _write_json(
        pyramid_store / "s0" / ".zarray",
        {
            "shape": [1, 1, 1],
            "chunks": [1, 2, 2],
            "dtype": "|u1",
            "compressor": None,
            "filters": [],
        },
    )
    detection = {
        "metadata_payload": {"multiscales": [{"coordinateTransformations": []}]},
        "multiscale": {
            "datasets": [{"path": "s0"}, {"path": "s1"}],
            "coordinateTransformations": [],
        },
        "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}],
        "datasets": [
            {
                "path": "s0",
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, 1.0, 1.0]},
                    {"type": "translation", "translation": [0.0, 0.0, 0.0]},
                ],
            },
            {"path": "s1"},
        ],
        "yx_indices": [1, 2],
        "s0_path": "s0",
    }
    monkeypatch.setattr(
        support,
        "_has_3d_pyramid_downsampling",
        lambda _store_root: detection,
    )
    monkeypatch.setattr(zarr, "open_array", lambda *args, **kwargs: np.zeros((1, 1, 1)))
    original_write_text = Path.write_text

    def _conditional_write_text(self, text, encoding=None):
        if self == pyramid_store / "s0" / ".zarray":
            raise OSError("s0 write exploded")
        if self == pyramid_store / ".zattrs":
            raise OSError("zattrs write exploded")
        return original_write_text(self, text, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", _conditional_write_text)
    assert "Failed to write updated .zattrs" in (
        support._regenerate_xy_only_pyramid(pyramid_store) or ""
    )

    codec_store = tmp_path / "pyramid-codec.ome.zarr"
    codec_store.mkdir()
    _write_json(
        codec_store / "s0" / ".zarray",
        {
            "shape": [1, 4, 4],
            "chunks": [1, 2, 2],
            "dtype": "|u1",
            "compressor": {"id": "blosc"},
            "filters": None,
        },
    )
    codec_detection = dict(detection)
    codec_detection["multiscale"] = {"datasets": [{"path": "s0"}, {"path": "s1"}]}
    codec_detection["datasets"] = detection["datasets"]
    monkeypatch.setattr(
        support,
        "_has_3d_pyramid_downsampling",
        lambda _store_root: codec_detection,
    )
    monkeypatch.setattr(zarr, "open_array", lambda *args, **kwargs: np.zeros((1, 4, 4)))
    monkeypatch.setattr(
        numcodecs,
        "get_codec",
        lambda spec: (_ for _ in ()).throw(RuntimeError("codec exploded")),
    )
    assert "failed to load source compressor for pyramid regeneration" in (
        support._regenerate_xy_only_pyramid(codec_store) or ""
    )

    monkeypatch.setattr(numcodecs, "get_codec", lambda spec: None)
    monkeypatch.setattr(
        support,
        "_write_zarr_v2_level",
        lambda *args, **kwargs: "level write exploded",
    )
    assert "level write exploded" in (
        support._regenerate_xy_only_pyramid(codec_store) or ""
    )


def test_write_level_and_runtime_helpers_cover_additional_error_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "level"
    data = np.arange(4, dtype=np.uint8).reshape(2, 2)
    original_write_text = Path.write_text
    original_write_bytes = Path.write_bytes

    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, text, encoding=None: (_ for _ in ()).throw(
            OSError("zarray write exploded")
        ),
    )
    assert "Failed to write .zarray" in (
        support._write_zarr_v2_level(
            output_dir,
            data,
            chunks=[2, 2],
            compressor_spec=None,
            filters_spec=None,
            codec=None,
        )
        or ""
    )

    monkeypatch.setattr(Path, "write_text", original_write_text)

    def _failing_write_bytes(self, payload):
        if self.name == "0":
            raise OSError("chunk write exploded")
        return original_write_bytes(self, payload)

    monkeypatch.setattr(Path, "write_bytes", _failing_write_bytes)
    codec = type("Codec", (), {"encode": staticmethod(lambda payload: payload)})()
    assert "Failed to write chunk" in (
        support._write_zarr_v2_level(
            output_dir,
            data,
            chunks=[2, 2],
            compressor_spec={"id": "gzip"},
            filters_spec=None,
            codec=codec,
        )
        or ""
    )

    support._ome_zarr_runtime.cache_clear()
    original_import = builtins.__import__

    def _failing_import(name, *args, **kwargs):
        if name.startswith("ome_zarr"):
            raise ImportError("ome-zarr missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    runtime, error = support._ome_zarr_runtime()
    assert runtime is None
    assert "ome-zarr missing" in (error or "")
