from __future__ import annotations

import json
from pathlib import Path

from omeroweb_import.services.ome_zarr_support import (
    OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW,
    OME_ZARR_IMPORT_KIND_IMAGE,
    inspect_ome_zarr_image,
    ome_zarr_package_version,
)


def _write_text(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_chunk(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")


def test_inspect_ome_zarr_image_reads_metadata_and_physical_sizes(
    tmp_path: Path,
) -> None:
    store = tmp_path / "image.ome.zarr"
    _write_text(
        store / ".zattrs",
        {
            "multiscales": [
                {
                    "version": "0.4",
                    "axes": [
                        {"name": "z", "type": "space", "unit": "nm"},
                        {"name": "y", "type": "space", "unit": "nm"},
                        {"name": "x", "type": "space", "unit": "nm"},
                    ],
                    "datasets": [
                        {
                            "path": "s0",
                            "coordinateTransformations": [
                                {"type": "scale", "scale": [10.0, 20.0, 30.0]},
                            ],
                        },
                        {
                            "path": "s1",
                            "coordinateTransformations": [
                                {"type": "scale", "scale": [20.0, 40.0, 60.0]},
                            ],
                        },
                    ],
                }
            ]
        },
    )
    _write_text(store / ".zgroup", {"zarr_format": 2})
    _write_text(
        store / "s0" / ".zarray",
        {
            "zarr_format": 2,
            "shape": [5, 10, 20],
            "chunks": [1, 10, 10],
            "dtype": "|u1",
            "compressor": None,
            "fill_value": 0,
            "filters": None,
            "order": "C",
        },
    )
    _write_text(
        store / "s1" / ".zarray",
        {
            "zarr_format": 2,
            "shape": [3, 5, 10],
            "chunks": [1, 5, 5],
            "dtype": "|u1",
            "compressor": None,
            "fill_value": 0,
            "filters": None,
            "order": "C",
        },
    )
    _write_chunk(store / "s0" / "0" / "0" / "0")
    _write_chunk(store / "s1" / "0" / "0" / "0")

    inspection = inspect_ome_zarr_image(store)

    assert inspection.recognized is True
    assert inspection.supported is True
    assert inspection.kind == OME_ZARR_IMPORT_KIND_IMAGE
    assert inspection.support_error is None
    assert inspection.format_version == "0.4"
    assert inspection.zarr_format == 2
    assert inspection.shape == (5, 10, 20)
    assert inspection.dtype_name == "uint8"
    assert inspection.physical_sizes == {
        "z": (10.0, "nm"),
        "y": (20.0, "nm"),
        "x": (30.0, "nm"),
    }
    assert ome_zarr_package_version()


def test_inspect_ome_zarr_image_rejects_plate_layout(tmp_path: Path) -> None:
    store = tmp_path / "plate.ome.zarr"
    _write_text(
        store / ".zattrs",
        {
            "plate": {
                "version": "0.4",
                "rows": [{"name": "A"}],
                "columns": [{"name": "1"}],
                "wells": [{"path": "A/1", "rowIndex": 0, "columnIndex": 0}],
            }
        },
    )
    _write_text(store / ".zgroup", {"zarr_format": 2})

    inspection = inspect_ome_zarr_image(store)

    assert inspection.recognized is True
    assert inspection.supported is False
    assert "plate" in (inspection.support_error or "").lower()


def test_inspect_ome_zarr_image_accepts_bioformats2raw_layout(tmp_path: Path) -> None:
    store = tmp_path / "bf2raw.ome.zarr"
    _write_text(store / ".zattrs", {"bioformats2raw.layout": 3})
    _write_text(store / ".zgroup", {"zarr_format": 2})

    for series_name in ("0", "1"):
        _write_text(
            store / series_name / ".zattrs",
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "y", "type": "space", "unit": "nm"},
                            {"name": "x", "type": "space", "unit": "nm"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [10.0, 10.0]},
                                ],
                            }
                        ],
                    }
                ]
            },
        )
        _write_text(store / series_name / ".zgroup", {"zarr_format": 2})
        _write_text(
            store / series_name / "0" / ".zarray",
            {
                "zarr_format": 2,
                "shape": [5, 10],
                "chunks": [1, 10],
                "dtype": "|u1",
                "compressor": None,
                "fill_value": 0,
                "filters": None,
                "order": "C",
            },
        )
        _write_chunk(store / series_name / "0" / "0" / "0")

    inspection = inspect_ome_zarr_image(store)

    assert inspection.recognized is True
    assert inspection.supported is True
    assert inspection.kind == OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW
    assert inspection.verify_lsid_prefix is True
    assert inspection.image_relative_paths == ("0/0", "1/0")


def test_inspect_ome_zarr_image_rejects_sparse_bioformats2raw_layout(
    tmp_path: Path,
) -> None:
    store = tmp_path / "bf2raw-gap.ome.zarr"
    _write_text(store / ".zattrs", {"bioformats2raw.layout": 3})
    _write_text(store / ".zgroup", {"zarr_format": 2})

    for series_name in ("0", "2"):
        _write_text(
            store / series_name / ".zattrs",
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "y", "type": "space", "unit": "nm"},
                            {"name": "x", "type": "space", "unit": "nm"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, 1.0]},
                                ],
                            }
                        ],
                    }
                ]
            },
        )
        _write_text(store / series_name / ".zgroup", {"zarr_format": 2})
        _write_text(
            store / series_name / "0" / ".zarray",
            {
                "zarr_format": 2,
                "shape": [1, 1],
                "chunks": [1, 1],
                "dtype": "|u1",
                "compressor": None,
                "fill_value": 0,
                "filters": None,
                "order": "C",
            },
        )
        _write_chunk(store / series_name / "0" / "0")

    inspection = inspect_ome_zarr_image(store)

    assert inspection.recognized is True
    assert inspection.supported is False
    assert "contiguous numeric series" in (inspection.support_error or "").lower()


def test_inspect_ome_zarr_image_ignores_non_ome_zarr_directory(tmp_path: Path) -> None:
    store = tmp_path / "plain-folder.zarr"
    store.mkdir(parents=True, exist_ok=True)
    (store / "notes.txt").write_text("not a zarr store", encoding="utf-8")

    inspection = inspect_ome_zarr_image(store)

    assert inspection.recognized is False
    assert inspection.supported is False
    assert inspection.support_error is None
