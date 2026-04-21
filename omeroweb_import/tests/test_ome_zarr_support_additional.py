from __future__ import annotations

from iter_test_helpers import next_or_fail

import builtins
import json
import sys
from pathlib import Path

import numcodecs
import numpy as np
import pytest
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


def test_ome_zarr_support_tolerates_unparseable_array_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metadata_payload = {
        "multiscales": [
            {
                "version": "0.4",
                "axes": [{"name": "y"}, {"name": "x"}],
                "datasets": [{"path": "0"}],
            }
        ]
    }
    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda store_root: (metadata_payload, None),
    )
    monkeypatch.setattr(
        support,
        "_read_zarr_format_metadata",
        lambda store_root, metadata_payload: 2,
    )
    monkeypatch.setattr(
        support,
        "_extract_axes",
        lambda axes: (["y", "x"], [None, None], None),
    )
    monkeypatch.setattr(
        support,
        "_extract_physical_sizes",
        lambda axis_names, axis_units, transforms: ({}, None),
    )
    monkeypatch.setattr(
        support,
        "_read_array_metadata_payload",
        lambda store_root, dataset_path: ({"shape": ["bad"], "dtype": "uint16"}, None),
    )
    monkeypatch.setattr(
        support,
        "_extract_dataset_relative_paths",
        lambda metadata_payload: ["0"],
    )
    monkeypatch.setattr(support, "ome_zarr_package_version", lambda: "1.2.3")

    inspection = support.inspect_ome_zarr_image(tmp_path / "demo.ome.zarr")

    assert inspection.supported is True
    assert inspection.shape == ()
    monkeypatch.setattr(
        support,
        "_extract_axes",
        lambda axes: ([axis.get("name") for axis in axes], [None for _ in axes], None),
    )

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

    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda series_dir: (None, None),
    )
    missing_metadata = support._inspect_bioformats2raw_layout(store)
    assert missing_metadata.recognized is True
    assert "Series 0 did not expose OME-Zarr metadata" in (
        missing_metadata.support_error or ""
    )


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
        support, "inspect_ome_zarr_image", lambda _path: next_or_fail(inspections)
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
        support, "inspect_ome_zarr_image", lambda _path: next_or_fail(inspections)
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


def test_ome_zarr_support_helper_guards_cover_remaining_metadata_and_axis_edges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    support.ome_zarr_package_version.cache_clear()
    monkeypatch.setattr(
        support.importlib_metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(
            support.importlib_metadata.PackageNotFoundError()
        ),
    )
    assert support.ome_zarr_package_version() == ""
    support.ome_zarr_package_version.cache_clear()

    monkeypatch.setattr(
        support,
        "_extract_axes",
        lambda _axes: ([], {}, "axes are broken"),
    )
    inspection = support._inspect_single_ome_zarr_image(
        tmp_path,
        {"multiscales": [{"axes": [{"name": "x"}], "datasets": [{"path": "0"}]}]},
    )
    assert inspection.support_error == "axes are broken"

    bf2raw = tmp_path / "fallback.ome.zarr"
    bf2raw.mkdir()
    (bf2raw / "0").mkdir()
    monkeypatch.setattr(
        support,
        "_inspect_single_ome_zarr_image",
        lambda _path, _metadata: support.OMEZarrImageInspection(
            recognized=True,
            kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
            image_relative_paths=(),
        ),
    )
    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda _path: (
            {
                "multiscales": [
                    {
                        "axes": [{"name": "y"}, {"name": "x"}],
                        "datasets": [{"path": "0"}],
                    }
                ]
            },
            None,
        ),
    )
    monkeypatch.setattr(
        support,
        "ome_zarr_package_version",
        lambda: "1.0",
    )
    inspection = support._inspect_bioformats2raw_layout(bf2raw)
    assert inspection.image_relative_paths == ("0",)

    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda _path: (
            None,
            support.OMEZarrImageInspection(
                recognized=True,
                kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
                image_relative_paths=(),
            ),
        ),
    )

    format_store = tmp_path / "format-store"
    format_store.mkdir()
    (format_store / ".zgroup").write_text("{broken", encoding="utf-8")
    _write_json(format_store / "zarr.json", {"zarr_format": 3})
    assert support._read_zarr_format_metadata(format_store, {}) == 3

    broken_array_dir = tmp_path / "array-store" / "0"
    broken_array_dir.mkdir(parents=True)
    (broken_array_dir / ".zarray").write_text("{broken", encoding="utf-8")
    payload, error = support._read_array_metadata_payload(
        tmp_path / "array-store",
        "0",
    )
    assert payload is None
    assert "Failed to read OME-Zarr array metadata" in (error or "")

    sizes, error = support._extract_physical_sizes(
        ["y", "x"],
        {},
        ["bad-transform"],
    )
    assert sizes == {}
    assert "malformed" in (error or "")

    sizes, error = support._extract_physical_sizes(
        ["y", "x"],
        {},
        [[{"type": "translation", "translation": [1, 2]}]],
    )
    assert sizes == {}
    assert "does not match the image axes" in (error or "")


def test_ome_zarr_support_downscale_and_codec_edges_cover_remaining_branches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inspection = support.OMEZarrImageInspection(
        recognized=True,
        kind=support.OME_ZARR_IMPORT_KIND_IMAGE,
        image_relative_paths=("0",),
    )
    store = tmp_path / "normalize.ome.zarr"
    (store / "0").mkdir(parents=True)
    _write_json(
        store / "0" / ".zarray",
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
    (store / "0" / "0").write_bytes(b"abc")

    original_import = builtins.__import__

    def _failing_numcodecs_import(
        name, global_vars=None, local_vars=None, fromlist=(), level=0
    ):
        if name == "numcodecs":
            raise ImportError("numcodecs missing")
        return original_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_numcodecs_import)
    assert "Failed to load numcodecs" in (
        support._rewrite_problematic_native_image_arrays(store, inspection) or ""
    )
    monkeypatch.setattr(builtins, "__import__", original_import)

    original_get_codec = numcodecs.get_codec
    monkeypatch.setattr(
        numcodecs,
        "get_codec",
        lambda _spec: type(
            "_Codec",
            (),
            {
                "decode": staticmethod(
                    lambda _payload: (_ for _ in ()).throw(
                        RuntimeError("decode failed")
                    )
                )
            },
        )(),
    )
    assert "Failed to normalize OME-Zarr chunk" in (
        support._rewrite_problematic_native_image_arrays(store, inspection) or ""
    )
    monkeypatch.setattr(numcodecs, "get_codec", original_get_codec)

    pyramid = tmp_path / "pyramid.ome.zarr"
    (pyramid / "s0").mkdir(parents=True)
    (pyramid / "s1").mkdir(parents=True)
    assert support._has_3d_pyramid_downsampling(pyramid) is None

    monkeypatch.setattr(
        support,
        "_load_root_ome_zarr_metadata",
        lambda _root: (
            {
                "multiscales": [
                    {
                        "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}],
                        "datasets": [{"path": "s0"}, {"path": "s1"}],
                    }
                ]
            },
            None,
        ),
    )
    (pyramid / "s0" / ".zarray").write_text("{broken", encoding="utf-8")
    _write_json(pyramid / "s1" / ".zarray", {"shape": [1, 1, 1]})
    assert support._has_3d_pyramid_downsampling(pyramid) is None

    _write_json(pyramid / "s0" / ".zarray", {"shape": [2, 4]})
    _write_json(pyramid / "s1" / ".zarray", {"shape": [1, 2, 2]})
    assert support._has_3d_pyramid_downsampling(pyramid) is None

    with pytest.raises(ValueError, match="data rank"):
        support._downscale_local_mean_fallback(np.ones((2, 2)), (2,))

    reduced = support._downscale_local_mean_fallback(
        np.array([[1.0, 2.0, 3.0]]),
        (1, 2),
    )
    assert reduced.shape == (1, 2)
    assert np.allclose(reduced, np.array([[1.5, 3.0]]))

    fake_transform = type(sys)("skimage.transform")
    fake_transform.downscale_local_mean = lambda data, factors: (
        np.asarray(data) + sum(factors)
    )
    monkeypatch.setitem(sys.modules, "skimage.transform", fake_transform)
    assert np.array_equal(
        support._downscale_local_mean(np.array([[1]]), (2, 3)),
        np.array([[6]]),
    )

    codec_store = tmp_path / "codec-array"
    codec_store.mkdir()
    metadata = {
        "shape": [1],
        "chunks": [1],
        "dtype": "|u1",
        "compressor": {"id": "gzip", "level": 1},
        "filters": None,
        "dimension_separator": "/",
    }
    codec = numcodecs.GZip(level=1)
    (codec_store / "0").write_bytes(
        codec.encode(np.array([9], dtype=np.uint8).tobytes())
    )
    loaded = support._read_zarr_v2_array(codec_store, metadata)
    assert loaded.tolist() == [9]

    with pytest.raises(RuntimeError, match="filters are not supported"):
        support._read_zarr_v2_array(
            codec_store,
            {
                "shape": [1],
                "chunks": [1],
                "dtype": "|u1",
                "filters": [{"id": "delta"}],
            },
        )


def test_ome_zarr_support_covers_invalid_shape_and_native_pyramid_guard_paths(
    tmp_path: Path,
) -> None:
    store = tmp_path / "invalid-shape.ome.zarr"
    metadata_payload = {
        "multiscales": [
            {
                "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}],
                "datasets": [{"path": "0"}],
            }
        ]
    }
    _write_json(store / ".zattrs", metadata_payload)
    _write_json(store / "0" / ".zarray", {"shape": ["bad", None], "dtype": "|u1"})
    inspection = support._inspect_single_ome_zarr_image(store, metadata_payload)
    assert inspection.shape == ()

    pyramid_store = tmp_path / "pyramid.ome.zarr"
    _write_json(
        pyramid_store / ".zattrs",
        {
            "multiscales": [
                {
                    "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}],
                    "datasets": [{"path": "0"}, {"path": "1"}],
                }
            ]
        },
    )
    assert support._has_3d_pyramid_downsampling(pyramid_store) is None

    _write_json(pyramid_store / "0" / ".zarray", {"shape": [4, 16, 16]})
    (pyramid_store / "1").mkdir(parents=True)
    (pyramid_store / "1" / ".zarray").write_text("{broken", encoding="utf-8")
    assert support._has_3d_pyramid_downsampling(pyramid_store) is None

    _write_json(pyramid_store / "1" / ".zarray", {"shape": [4, 8]})
    assert support._has_3d_pyramid_downsampling(pyramid_store) is None


def test_regenerate_xy_only_pyramid_handles_numpy_dependency_and_translation_edges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = tmp_path / "translation.ome.zarr"
    store.mkdir()
    detection = {
        "metadata_payload": {
            "multiscales": [{"datasets": [{"path": "s0"}, {"path": "s1"}]}]
        },
        "multiscale": {"datasets": [{"path": "s0"}, {"path": "s1"}]},
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
        lambda _root: detection,
    )

    original_import = builtins.__import__

    def _failing_numpy_import(
        name, global_vars=None, local_vars=None, fromlist=(), level=0
    ):
        if name == "numpy":
            raise ImportError("numpy missing")
        return original_import(name, global_vars, local_vars, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_numpy_import)
    assert "Missing dependency for pyramid regeneration" in (
        support._regenerate_xy_only_pyramid(store) or ""
    )
    monkeypatch.setattr(builtins, "__import__", original_import)

    _write_json(
        store / "s0" / ".zarray",
        {
            "chunks": [1, 2, 2],
            "dtype": "|u1",
            "compressor": {"id": "blosc"},
            "filters": None,
        },
    )
    monkeypatch.setattr(
        support,
        "_read_zarr_v2_array",
        lambda *_args, **_kwargs: np.ones((2, 4, 4), dtype=np.uint8),
    )
    monkeypatch.setattr(
        numcodecs,
        "get_codec",
        lambda _spec: (_ for _ in ()).throw(RuntimeError("codec missing")),
    )
    assert "Failed to load compressor for pyramid regeneration" in (
        support._regenerate_xy_only_pyramid(store) or ""
    )

    written = {}
    monkeypatch.setattr(numcodecs, "get_codec", lambda _spec: object())
    monkeypatch.setattr(
        support,
        "_downscale_local_mean",
        lambda data, factors: data[:, ::2, ::2],
    )
    monkeypatch.setattr(
        support,
        "_write_zarr_v2_level",
        lambda level_dir, data, chunks, compressor, filters, codec: (
            written.setdefault(
                "call",
                {
                    "level_dir": level_dir,
                    "data_shape": tuple(data.shape),
                    "compressor": compressor,
                    "codec_is_present": codec is not None,
                },
            )
            and None
        ),
    )
    assert support._regenerate_xy_only_pyramid(store) is None
    updated = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
    transforms = updated["multiscales"][0]["datasets"][1]["coordinateTransformations"]
    assert transforms[1]["type"] == "translation"


def test_downscale_local_mean_falls_back_when_skimage_import_fails(
    monkeypatch,
) -> None:
    """_downscale_local_mean uses the fallback when skimage.transform import fails."""
    # Remove skimage.transform from sys.modules so the import inside the
    # function actually executes, then make it raise ImportError.
    monkeypatch.delitem(sys.modules, "skimage.transform", raising=False)
    monkeypatch.delitem(sys.modules, "skimage", raising=False)

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name in ("skimage.transform", "skimage"):
            raise ImportError("skimage blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    data = np.array([[1.0, 2.0, 3.0, 4.0]])
    result = support._downscale_local_mean(data, (1, 2))

    # The fallback averages adjacent pairs: (1+2)/2=1.5, (3+4)/2=3.5
    assert result.shape == (1, 2)
    assert np.allclose(result, np.array([[1.5, 3.5]]))
