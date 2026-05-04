"""Tests for the native OME-Zarr normalization contract.

Supported native OME-Zarr stores must keep their logical image layout intact,
but the ephemeral managed-repository copy may normalize image-array codecs when
the installed OMERO render stack cannot reliably thumbnail the original chunk
encoding.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import django
import numpy as np
from django.conf import settings
from numcodecs import Blosc

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key",
        DEFAULT_CHARSET="utf-8",
        ALLOWED_HOSTS=["testserver", "localhost"],
        USE_I18N=False,
        USE_TZ=True,
        INSTALLED_APPS=[],
    )
    django.setup()

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from omeroweb_import.views.core_functions import (  # noqa: E402
    _prepare_native_zarr_copy,
    _validate_native_ome_ngff_zarr,
)


def _write_text(path: Path, payload: dict) -> None:
    """Write text.

    Inputs: `path`, `payload`. Output: None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_chunk(path: Path, payload: bytes = b"\x00") -> None:
    """Write chunk.

    Inputs: `path`, `payload`. Output: None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_blosc_chunk(
    path: Path, shape: tuple[int, ...], dtype: str = "uint16"
) -> None:
    """Write blosc chunk.

    Inputs: `path`, `shape`, `dtype`. Output: None.
    """
    raw = np.zeros(shape, dtype=np.dtype(dtype)).tobytes(order="C")
    codec = Blosc(cname="lz4", clevel=5, shuffle=1)
    _write_chunk(path, codec.encode(raw))


def _make_multiscale_ome_zarr(zarr_dir: Path, dataset_paths: list[str]) -> Path:
    """Multiscale ome Zarr.

    Inputs: `zarr_dir`, `dataset_paths`. Output: `Path`.
    """
    _write_text(
        zarr_dir / ".zattrs",
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
                            "path": dataset_path,
                            "coordinateTransformations": [
                                {"type": "scale", "scale": [1.0, 1.0]},
                            ],
                        }
                        for dataset_path in dataset_paths
                    ],
                }
            ],
        },
    )
    _write_text(zarr_dir / ".zgroup", {"zarr_format": 2})
    for dataset_path in dataset_paths:
        _write_text(
            zarr_dir / dataset_path / ".zarray",
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
        _write_chunk(zarr_dir / dataset_path / "0" / "0")
    return zarr_dir


def _make_bioformats2raw_layout(zarr_dir: Path, series_names: list[str]) -> Path:
    """Bioformats2raw layout.

    Inputs: `zarr_dir`, `series_names`. Output: `Path`.
    """
    _write_text(zarr_dir / ".zattrs", {"bioformats2raw.layout": 3})
    _write_text(zarr_dir / ".zgroup", {"zarr_format": 2})
    for series_name in series_names:
        _make_multiscale_ome_zarr(zarr_dir / series_name, ["0"])
    return zarr_dir


def _make_large_blosc_image_store(zarr_dir: Path) -> Path:
    """Large blosc image store.

    Inputs: `zarr_dir`. Output: `Path`.
    """
    _write_text(
        zarr_dir / ".zattrs",
        {
            "multiscales": [
                {
                    "version": "0.4",
                    "axes": [
                        {"name": "c", "type": "channel"},
                        {"name": "z", "type": "space", "unit": "micrometer"},
                        {"name": "y", "type": "space", "unit": "micrometer"},
                        {"name": "x", "type": "space", "unit": "micrometer"},
                    ],
                    "datasets": [
                        {
                            "path": "0",
                            "coordinateTransformations": [
                                {
                                    "type": "scale",
                                    "scale": [
                                        1.0,
                                        1.0,
                                        0.11656635164576248,
                                        0.11656635164576248,
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "omero": {
                "channels": [
                    {
                        "active": True,
                        "color": "FFFFFF",
                        "label": "C00",
                        "window": {
                            "start": 12.0,
                            "end": 1330.0,
                            "min": 0.0,
                            "max": 65535.0,
                        },
                    }
                ]
            },
        },
    )
    _write_text(zarr_dir / ".zgroup", {"zarr_format": 2})
    _write_text(
        zarr_dir / "0" / ".zarray",
        {
            "zarr_format": 2,
            "shape": [1, 1, 4096, 4096],
            "chunks": [1, 1, 4096, 4096],
            "dtype": "<u2",
            "compressor": {
                "id": "blosc",
                "cname": "lz4",
                "clevel": 5,
                "shuffle": 1,
                "blocksize": 0,
            },
            "fill_value": 0,
            "filters": None,
            "order": "C",
            "dimension_separator": "/",
        },
    )
    _write_blosc_chunk(zarr_dir / "0" / "0" / "0" / "0" / "0", (1, 1, 4096, 4096))
    return zarr_dir


class TestNativeZarrNormalization:
    """Represent test native Zarr normalization."""

    @staticmethod
    def test_prepare_native_zarr_copy_accepts_multiscale_ome_zarr_without_rewriting(
        tmp_path,
    ):
        """Verify prepare native Zarr copy accepts multiscale ome Zarr without rewriting.

        Inputs: `tmp_path`. Output: None.
        """
        zarr_dir = _make_multiscale_ome_zarr(
            tmp_path / "image.ome.zarr", ["s0", "s1", "s2"]
        )

        error = _prepare_native_zarr_copy(zarr_dir)

        assert error is None
        with open(zarr_dir / ".zattrs", encoding="utf-8") as handle:
            attrs = json.load(handle)
        assert [entry["path"] for entry in attrs["multiscales"][0]["datasets"]] == [
            "s0",
            "s1",
            "s2",
        ]
        assert (zarr_dir / "s1").is_dir()
        assert (zarr_dir / "s2").is_dir()

    @staticmethod
    def test_prepare_native_zarr_copy_rewrites_large_blosc_image_arrays_to_gzip(
        tmp_path,
    ):
        """Verify prepare native Zarr copy rewrites large blosc image arrays to gzip.

        Inputs: `tmp_path`. Output: None.
        """
        zarr_dir = _make_large_blosc_image_store(tmp_path / "image.ome.zarr")

        error = _prepare_native_zarr_copy(zarr_dir)

        assert error is None
        with open(zarr_dir / "0" / ".zarray", encoding="utf-8") as handle:
            attrs = json.load(handle)
        assert attrs["compressor"] == {"id": "gzip", "level": 1}
        assert (zarr_dir / "0" / "0" / "0" / "0" / "0").is_file()

    @staticmethod
    def test_prepare_native_zarr_copy_rewrites_only_referenced_image_arrays(tmp_path):
        """Verify prepare native Zarr copy rewrites only referenced image arrays.

        Inputs: `tmp_path`. Output: None.
        """
        zarr_dir = _make_large_blosc_image_store(tmp_path / "image.ome.zarr")
        _write_text(
            zarr_dir / "tables" / "measurements" / ".zarray",
            {
                "zarr_format": 2,
                "shape": [4],
                "chunks": [4],
                "dtype": "|u1",
                "compressor": {
                    "id": "blosc",
                    "cname": "lz4",
                    "clevel": 5,
                    "shuffle": 1,
                    "blocksize": 0,
                },
                "fill_value": 0,
                "filters": None,
                "order": "C",
            },
        )
        _write_blosc_chunk(
            zarr_dir / "tables" / "measurements" / "0", (4,), dtype="uint8"
        )

        error = _prepare_native_zarr_copy(zarr_dir)

        assert error is None
        with open(zarr_dir / "0" / ".zarray", encoding="utf-8") as handle:
            image_attrs = json.load(handle)
        with open(
            zarr_dir / "tables" / "measurements" / ".zarray", encoding="utf-8"
        ) as handle:
            table_attrs = json.load(handle)
        assert image_attrs["compressor"] == {"id": "gzip", "level": 1}
        assert table_attrs["compressor"]["id"] == "blosc"

    @staticmethod
    def test_prepare_native_zarr_copy_rewrites_supported_bioformats2raw_series_arrays(
        tmp_path,
    ):
        """Verify prepare native Zarr copy rewrites supported bioformats2raw series arrays.

        Inputs: `tmp_path`. Output: None.
        """
        zarr_dir = _make_bioformats2raw_layout(tmp_path / "bf2raw.ome.zarr", ["0", "1"])
        for series_name in ("0", "1"):
            _write_text(
                zarr_dir / series_name / "0" / ".zarray",
                {
                    "zarr_format": 2,
                    "shape": [1, 1],
                    "chunks": [1, 1],
                    "dtype": "<u2",
                    "compressor": {
                        "id": "blosc",
                        "cname": "lz4",
                        "clevel": 5,
                        "shuffle": 1,
                        "blocksize": 0,
                    },
                    "fill_value": 0,
                    "filters": None,
                    "order": "C",
                },
            )
            _write_blosc_chunk(zarr_dir / series_name / "0" / "0" / "0", (1, 1))

        error = _prepare_native_zarr_copy(zarr_dir)

        assert error is None
        for series_name in ("0", "1"):
            with open(
                zarr_dir / series_name / "0" / ".zarray", encoding="utf-8"
            ) as handle:
                attrs = json.load(handle)
            assert attrs["compressor"] == {"id": "gzip", "level": 1}

    @staticmethod
    def test_prepare_native_zarr_copy_rejects_sparse_bioformats2raw_layout(tmp_path):
        """Verify prepare native Zarr copy rejects sparse bioformats2raw layout.

        Inputs: `tmp_path`. Output: None.
        """
        zarr_dir = _make_bioformats2raw_layout(
            tmp_path / "bf2raw-gap.ome.zarr", ["0", "2"]
        )

        error = _prepare_native_zarr_copy(zarr_dir)

        assert error is not None
        assert "contiguous numeric series" in error.lower()

    @staticmethod
    def test_validate_native_ome_ngff_zarr_rejects_plate_layout(tmp_path):
        """Verify validate native ome NGFF Zarr rejects plate layout.

        Inputs: `tmp_path`. Output: None.
        """
        zarr_dir = tmp_path / "plate.ome.zarr"
        _write_text(
            zarr_dir / ".zattrs",
            {
                "plate": {
                    "version": "0.4",
                    "rows": [{"name": "A"}],
                    "columns": [{"name": "1"}],
                    "wells": [{"path": "A/1", "rowIndex": 0, "columnIndex": 0}],
                }
            },
        )
        _write_text(zarr_dir / ".zgroup", {"zarr_format": 2})

        error = _validate_native_ome_ngff_zarr(zarr_dir)

        assert error is not None
        assert "plate" in error.lower()
