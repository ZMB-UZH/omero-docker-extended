from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from omeroweb_import.services.ome_zarr_support import (
    DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL,
    OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW,
    OME_ZARR_IMPORT_KIND_IMAGE,
    OME_ZARR_NATIVE_GZIP_LEVEL_ENV,
    OMEZarrImageInspection,
    _extract_axes,
    _extract_physical_sizes,
    _has_3d_pyramid_downsampling,
    _native_ome_zarr_gzip_level,
    _ome_zarr_runtime,
    _read_array_metadata_payload,
    _read_store_metadata_payload,
    _read_zarr_format_metadata,
    _regenerate_xy_only_pyramid,
    _rewrite_problematic_native_image_arrays,
    _write_zarr_v2_level,
    inspect_ome_zarr_image,
    ome_zarr_package_version,
)


def _write_text(path: Path, payload: dict) -> None:
    """Write the text.

    Inputs: `path` (Path) path, `payload` (dict) payload. Output: None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_chunk(path: Path) -> None:
    """Write the chunk.

    Inputs: `path` (Path) path. Output: None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")


def _read_json(path: Path) -> dict:
    """Read the JSON.

    Inputs: `path` (Path) path. Output: `dict`.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _open_zarr_v2_array(store: Path, **kwargs):
    """Open the Zarr v2 array.

    Inputs: `store` (Path), `**kwargs` keyword arguments. Output: `_ArrayWriter` result.
    Raises: AssertionError, RuntimeError when validation or the called operation fails.
    """

    class _ArrayWriter:
        """Test double for array writer behavior in this module."""

        def __init__(self, store_path: Path, *, chunks, dtype):
            """Create `_ArrayWriter` with `store_path`.

            Inputs: `store_path`, `chunks`, `dtype`. Output: None.
            """
            self._store_path = store_path
            self._chunks = list(chunks)
            self._dtype = np.dtype(dtype)

        def __setitem__(self, key, value):
            """Record the setitem call on `_ArrayWriter` for later assertions.

            Inputs: `key` lookup key, `value` input value. Output: None. Raises:
            AssertionError, RuntimeError when validation or the called operation fails.
            """
            if key != slice(None):
                raise AssertionError(f"Unsupported write selection: {key!r}")
            payload = np.asarray(value, dtype=self._dtype)
            error = _write_zarr_v2_level(
                self._store_path,
                payload,
                self._chunks,
                None,
                None,
                None,
            )
            if error is not None:
                raise RuntimeError(error)

    return _ArrayWriter(
        store,
        chunks=kwargs["chunks"],
        dtype=kwargs["dtype"],
    )


def test_inspect_ome_zarr_image_reads_metadata_and_physical_sizes(
    tmp_path: Path,
) -> None:
    """Verify inspect ome Zarr image reads metadata and physical sizes.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in inspect ome Zarr image reads metadata and physical sizes.
    """
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
    """Confirm inspect ome Zarr image rejects plate layout is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in inspect ome Zarr image rejects plate layout.
    """
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
    """Verify inspect ome Zarr image accepts bioformats2raw layout.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in inspect ome Zarr image accepts bioformats2raw layout.
    """
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
    """Confirm inspect ome Zarr image rejects sparse bioformats2raw layout is rejected at the boundary.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in inspect ome Zarr image rejects sparse bioformats2raw layout.
    """
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
    """Verify inspect ome Zarr image ignores non ome Zarr directory.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in inspect ome Zarr image ignores non ome Zarr directory.
    """
    store = tmp_path / "plain-folder.zarr"
    store.mkdir(parents=True, exist_ok=True)
    (store / "notes.txt").write_text("not a zarr store", encoding="utf-8")

    inspection = inspect_ome_zarr_image(store)

    assert inspection.recognized is False
    assert inspection.supported is False
    assert inspection.support_error is None


def test_metadata_helpers_report_missing_and_invalid_payloads(tmp_path: Path) -> None:
    """Verify metadata helpers report missing and invalid payloads.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in metadata helpers report missing and invalid payloads.
    """
    store = tmp_path / "broken.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)

    assert _read_store_metadata_payload(store) == (None, None)

    (store / ".zattrs").write_text("{broken", encoding="utf-8")
    payload, error = _read_store_metadata_payload(store)
    assert payload is None
    assert "Failed to read OME-Zarr metadata" in (error or "")

    (store / ".zattrs").write_text(json.dumps({"multiscales": []}), encoding="utf-8")
    (store / "zarr.json").write_text(json.dumps({"zarr_format": 3}), encoding="utf-8")
    assert _read_zarr_format_metadata(store, {"multiscales": []}) == 3

    array_payload, array_error = _read_array_metadata_payload(store, "0")
    assert array_payload is None
    assert "missing its array metadata" in (array_error or "")

    axis_names, axis_units, axis_error = _extract_axes([{"name": "z", "unit": "nm"}])
    assert axis_names == ["z"]
    assert axis_units == {"z": "nm"}
    assert axis_error is None

    _, _, axis_error = _extract_axes([{"unit": "nm"}])
    assert "non-empty axis names" in (axis_error or "")

    sizes, size_error = _extract_physical_sizes(
        ["z", "y", "x"],
        {"z": "nm", "y": "nm", "x": "nm"},
        [[{"type": "scale", "scale": [10.0, 20.0, 30.0]}]],
    )
    assert sizes == {
        "z": (10.0, "nm"),
        "y": (20.0, "nm"),
        "x": (30.0, "nm"),
    }
    assert size_error is None

    _, size_error = _extract_physical_sizes(
        ["z", "y", "x"],
        {},
        [[{"type": "scale", "scale": [10.0, "bad", 30.0]}]],
    )
    assert "not numeric" in (size_error or "")

    _, size_error = _extract_physical_sizes(
        ["z", "y", "x"],
        {},
        [[{"type": "scale", "scale": [10.0, -1.0, 30.0]}]],
    )
    assert "must be positive" in (size_error or "")


def test_native_gzip_level_helper_and_runtime_contract(monkeypatch) -> None:
    """Verify native gzip level helper and runtime contract.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in native gzip level helper and runtime contract.
    """
    monkeypatch.delenv(OME_ZARR_NATIVE_GZIP_LEVEL_ENV, raising=False)
    assert _native_ome_zarr_gzip_level() == DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL

    monkeypatch.setenv(OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "invalid")
    assert _native_ome_zarr_gzip_level() == DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL

    monkeypatch.setenv(OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "-5")
    assert _native_ome_zarr_gzip_level() == DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL

    monkeypatch.setenv(OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "4")
    assert _native_ome_zarr_gzip_level() == 4

    runtime, error = _ome_zarr_runtime()
    assert error is None
    assert sorted(runtime.keys()) == [
        "CurrentFormat",
        "Reader",
        "detect_format",
        "parse_url",
    ]


def test_rewrite_problematic_native_image_arrays_recompresses_blosc_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify rewrite problematic native image arrays recompresses blosc chunks.

    Inputs: pytest provides `tmp_path`, `monkeypatch`. Output: fails on regressions in rewrite problematic native image arrays recompresses blosc chunks.
    """
    import numcodecs

    store = tmp_path / "image.ome.zarr"
    array_dir = store / "0"
    array_dir.mkdir(parents=True, exist_ok=True)
    compressor_spec = {"id": "blosc", "cname": "zstd", "clevel": 1, "shuffle": 0}
    (array_dir / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": [4],
                "chunks": [4],
                "dtype": "|u1",
                "compressor": compressor_spec,
                "fill_value": 0,
                "filters": None,
                "order": "C",
            }
        ),
        encoding="utf-8",
    )
    (array_dir / "0").write_bytes(
        numcodecs.get_codec(compressor_spec).encode(b"\x01\x02\x03\x04")
    )
    inspection = OMEZarrImageInspection(
        recognized=True,
        kind=OME_ZARR_IMPORT_KIND_IMAGE,
        image_relative_paths=("0",),
    )

    monkeypatch.setenv(OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "5")
    error = _rewrite_problematic_native_image_arrays(store, inspection)

    assert error is None
    assert _read_json(array_dir / ".zarray")["compressor"] == {"id": "gzip", "level": 5}
    assert numcodecs.GZip(level=5).decode((array_dir / "0").read_bytes()) == (
        b"\x01\x02\x03\x04"
    )


def test_detects_and_regenerates_xy_only_pyramid(tmp_path: Path) -> None:
    """Verify detects and regenerates xy only pyramid.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in detects and regenerates xy only pyramid.
    """
    store = tmp_path / "pyramid.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "z", "type": "space"},
                            {"name": "y", "type": "space"},
                            {"name": "x", "type": "space"},
                        ],
                        "datasets": [
                            {
                                "path": "s0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, 1.0, 1.0]}
                                ],
                            },
                            {
                                "path": "s1",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [2.0, 2.0, 2.0]}
                                ],
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _open_zarr_v2_array(
        store / "s0",
        mode="w",
        shape=(4, 8, 8),
        chunks=(2, 4, 4),
        dtype=np.uint16,
    )[:] = np.arange(4 * 8 * 8, dtype=np.uint16).reshape(4, 8, 8)
    _open_zarr_v2_array(
        store / "s1",
        mode="w",
        shape=(2, 4, 4),
        chunks=(2, 4, 4),
        dtype=np.uint16,
    )[:] = np.zeros((2, 4, 4), dtype=np.uint16)

    detection = _has_3d_pyramid_downsampling(store)
    assert detection is not None
    assert detection["z_axis_index"] == 0
    assert detection["s0_path"] == "s0"

    error = _regenerate_xy_only_pyramid(store)

    assert error is None
    assert _read_json(store / "s1" / ".zarray")["shape"] == [4, 4, 4]
    assert _read_json(store / ".zattrs")["multiscales"][0]["datasets"][1][
        "coordinateTransformations"
    ][0]["scale"] == [1.0, 2.0, 2.0]


def test_write_zarr_v2_level_writes_metadata_and_padded_chunks(tmp_path: Path) -> None:
    """Verify write Zarr v2 level writes metadata and padded chunks.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in write Zarr v2 level writes metadata and padded chunks.
    """
    output_dir = tmp_path / "s1"
    data = np.arange(9, dtype=np.uint8).reshape(3, 3)

    error = _write_zarr_v2_level(
        output_dir,
        data,
        chunks=[2, 2],
        compressor_spec=None,
        filters_spec=None,
        codec=None,
    )

    assert error is None
    assert _read_json(output_dir / ".zarray")["shape"] == [3, 3]
    assert (output_dir / "0" / "0").read_bytes() == bytes([0, 1, 3, 4])
    assert (output_dir / "1" / "1").read_bytes() == bytes([8, 0, 0, 0])
