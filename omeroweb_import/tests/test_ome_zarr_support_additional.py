from __future__ import annotations

import json
from pathlib import Path

import numcodecs
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
