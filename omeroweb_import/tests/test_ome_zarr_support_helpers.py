from __future__ import annotations

import json

import numpy as np

from omeroweb_import.services import ome_zarr_support as support


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_read_store_metadata_payload_uses_zarr_json_fallback(tmp_path) -> None:
    store = tmp_path / "image.ome.zarr"
    expected = {"multiscales": [{"datasets": [{"path": "0"}]}]}
    _write_json(store / "zarr.json", expected)

    payload, error = support._read_store_metadata_payload(store)

    assert payload == expected
    assert error is None


def test_read_store_metadata_payload_reports_invalid_json_from_primary_metadata_file(tmp_path) -> None:
    store = tmp_path / "image.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)
    (store / ".zattrs").write_text("{not-json", encoding="utf-8")
    _write_json(store / "zarr.json", {"multiscales": []})

    payload, error = support._read_store_metadata_payload(store)

    assert payload is None
    assert error is not None
    assert ".zattrs" in error


def test_extract_axes_rejects_non_mapping_and_blank_axis_names() -> None:
    axis_names, axis_units, error = support._extract_axes(["x"])
    assert axis_names == []
    assert axis_units == {}
    assert "metadata objects" in error

    axis_names, axis_units, error = support._extract_axes([{"name": "   "}])
    assert axis_names == []
    assert axis_units == {}
    assert "non-empty axis names" in error


def test_extract_physical_sizes_rejects_malformed_non_numeric_and_negative_scales() -> None:
    axis_names = ["z", "y", "x"]
    axis_units = {"z": "nm", "y": "nm", "x": "nm"}

    physical_sizes, error = support._extract_physical_sizes(axis_names, axis_units, [])
    assert physical_sizes == {}
    assert "missing coordinate transformations" in error

    physical_sizes, error = support._extract_physical_sizes(
        axis_names,
        axis_units,
        [[{"type": "scale", "scale": [1.0, "bad", 3.0]}]],
    )
    assert physical_sizes == {}
    assert "not numeric" in error

    physical_sizes, error = support._extract_physical_sizes(
        axis_names,
        axis_units,
        [[{"type": "scale", "scale": [1.0, -2.0, 3.0]}]],
    )
    assert physical_sizes == {}
    assert "must be positive" in error


def test_has_3d_pyramid_downsampling_detects_z_axis_reduction(tmp_path) -> None:
    store = tmp_path / "image.ome.zarr"
    _write_json(
        store / ".zattrs",
        {
            "multiscales": [
                {
                    "axes": [
                        {"name": "z", "type": "space"},
                        {"name": "y", "type": "space"},
                        {"name": "x", "type": "space"},
                    ],
                    "datasets": [
                        {"path": "s0"},
                        {"path": "s1"},
                    ],
                }
            ]
        },
    )
    _write_json(store / "s0" / ".zarray", {"shape": [6, 12, 12]})
    _write_json(store / "s1" / ".zarray", {"shape": [3, 6, 6]})

    detection = support._has_3d_pyramid_downsampling(store)

    assert detection is not None
    assert detection["z_axis_index"] == 0
    assert detection["yx_indices"] == [1, 2]
    assert detection["s0_path"] == "s0"


def test_has_3d_pyramid_downsampling_ignores_yx_only_downsampling(tmp_path) -> None:
    store = tmp_path / "image.ome.zarr"
    _write_json(
        store / ".zattrs",
        {
            "multiscales": [
                {
                    "axes": [
                        {"name": "z", "type": "space"},
                        {"name": "y", "type": "space"},
                        {"name": "x", "type": "space"},
                    ],
                    "datasets": [
                        {"path": "s0"},
                        {"path": "s1"},
                    ],
                }
            ]
        },
    )
    _write_json(store / "s0" / ".zarray", {"shape": [6, 12, 12]})
    _write_json(store / "s1" / ".zarray", {"shape": [6, 6, 6]})

    assert support._has_3d_pyramid_downsampling(store) is None


def test_write_zarr_v2_level_writes_padded_edge_chunks(tmp_path) -> None:
    output_dir = tmp_path / "s1"
    data = np.arange(9, dtype=np.uint8).reshape(3, 3)

    error = support._write_zarr_v2_level(
        output_dir,
        data,
        chunks=[2, 2],
        compressor_spec=None,
        filters_spec=None,
        codec=None,
    )

    assert error is None
    metadata = json.loads((output_dir / ".zarray").read_text(encoding="utf-8"))
    assert metadata["dimension_separator"] == "/"
    assert (output_dir / "0" / "0").exists()
    assert (output_dir / "0" / "1").exists()
    assert (output_dir / "1" / "0").exists()
    assert (output_dir / "1" / "1").exists()

    edge_chunk = np.frombuffer((output_dir / "1" / "1").read_bytes(), dtype=np.uint8).reshape(2, 2)
    assert edge_chunk.tolist() == [[8, 0], [0, 0]]


def test_native_ome_zarr_gzip_level_uses_default_for_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv(support.OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "bad")
    assert support._native_ome_zarr_gzip_level() == support.DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL

    monkeypatch.setenv(support.OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "-5")
    assert support._native_ome_zarr_gzip_level() == support.DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL

    monkeypatch.setenv(support.OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "4")
    assert support._native_ome_zarr_gzip_level() == 4
