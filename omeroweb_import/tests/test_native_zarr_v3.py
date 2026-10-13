"""Exercise native normalization with real NGFF 0.5 arrays and codec pipelines."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
import zarr
from ome_zarr.format import FormatV05
from ome_zarr.writer import write_multiscale

from omeroweb_import.services import ome_zarr_support as support


def snapshot(root):
    """Inputs: a store root. Output: relative paths mapped to their exact bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def make_store(root, axes, *, z_downsample=False, sharded=False, later=False):
    """Write a real NGFF fixture with configurable pyramid and chunk layouts.

    Inputs: root, axes, downsampling/sharding controls. Output: pixels and metadata.
    """
    shape = tuple({"t": 2, "c": 2, "z": 4, "y": 16, "x": 24}[a] for a in axes)
    data = np.arange(np.prod(shape), dtype=np.uint16).reshape(shape)
    factors = tuple(
        2 if a in "yx" or (a == "z" and z_downsample and not later) else 1 for a in axes
    )
    slices = tuple(slice(None, None, f) for f in factors)
    levels = [data, data[slices]]
    scales = [[1.0] * len(axes), list(map(float, factors))]
    if later:
        factors = tuple(2 if a in "zyx" else 1 for a in axes)
        levels.append(levels[-1][tuple(slice(None, None, f) for f in factors)])
        scales.append([a * b for a, b in zip(scales[-1], factors)])
    chunks = tuple(4 if a in "yx" else 1 for a in axes)
    options = {"chunks": chunks}
    if sharded:
        options["shards"] = tuple(
            c * 2 if a in "yx" else c for a, c in zip(axes, chunks)
        )
    group = zarr.create_group(str(root), zarr_format=3)
    write_multiscale(
        levels,
        group,
        fmt=FormatV05(),
        axes=axes,
        scale=dict.fromkeys(axes, 1.0),
        storage_options=options,
    )
    ome = group.attrs["ome"]
    for dataset, scale in zip(ome["multiscales"][0]["datasets"], scales):
        dataset["coordinateTransformations"] = [
            {"type": "scale", "scale": scale},
            {"type": "translation", "translation": [3.0] * len(axes)},
        ]
    group.attrs["ome"] = ome
    group.attrs["application_metadata"] = {"retain": True}
    return data, group.attrs["ome"]["multiscales"][0]["datasets"]


@pytest.mark.parametrize("axes", ["yx", "zyx", "tczyx"])
@pytest.mark.parametrize("sharded", [False, True])
def test_v3_xy_pyramids_remain_byte_identical(tmp_path, axes, sharded):
    """Inputs: real XY-only stores. Output: byte and pixel preservation checks."""
    store = tmp_path / "image.ome.zarr"
    expected, datasets = make_store(store, axes, sharded=sharded)
    before = snapshot(store)
    assert support.inspect_ome_zarr_image(store).supported

    assert support.normalize_native_ome_zarr_copy(store) is None

    assert snapshot(store) == before
    np.testing.assert_array_equal(
        zarr.open_array(str(store / datasets[0]["path"]), mode="r")[:], expected
    )


@pytest.mark.parametrize("axes", ["zyx", "tczyx"])
@pytest.mark.parametrize("sharded", [False, True])
@pytest.mark.parametrize("later", [False, True])
def test_v3_regeneration_preserves_format_full_resolution_and_non_spatial_axes(
    tmp_path, axes, sharded, later
):
    """Inputs: real 3D pyramids. Output: independent pixel/metadata/idempotence checks."""
    store = tmp_path / "image.ome.zarr"
    expected, datasets = make_store(
        store, axes, z_downsample=True, sharded=sharded, later=later
    )
    full_root = store / datasets[0]["path"]
    full_before = snapshot(full_root)
    full_meta = json.loads((full_root / "zarr.json").read_text())

    assert support.normalize_native_ome_zarr_copy(store) is None

    assert snapshot(full_root) == full_before
    assert not list(store.rglob(".zarray")) and not (store / ".zattrs").exists()
    group = zarr.open_group(str(store), mode="r", use_consolidated=False)
    assert group.attrs["application_metadata"] == {"retain": True}
    assert group.attrs["ome"]["version"] == "0.5"
    updated = group.attrs["ome"]["multiscales"][0]["datasets"]
    assert len(updated) == len(datasets)
    current = expected
    for index, dataset in enumerate(updated):
        array = group[dataset["path"]]
        assert array.metadata.zarr_format == 3
        if index:
            # Independent even-sized 2x2 mean oracle; T/C/Z must never mix.
            height, width = current.shape[-2:]
            current = (
                current.reshape(*current.shape[:-2], height // 2, 2, width // 2, 2)
                .mean(axis=(-3, -1))
                .astype(expected.dtype)
            )
        np.testing.assert_array_equal(array[:], current)
        metadata = json.loads((store / dataset["path"] / "zarr.json").read_text())
        for key in ("codecs", "chunk_key_encoding", "chunk_grid", "dimension_names"):
            assert metadata[key] == full_meta[key]
        transforms = dataset["coordinateTransformations"]
        scale = next(t["scale"] for t in transforms if t["type"] == "scale")
        translation = next(
            t["translation"] for t in transforms if t["type"] == "translation"
        )
        assert scale == [float(2**index) if a in "yx" else 1.0 for a in axes]
        assert translation == [
            3.0 + (2**index - 1) / 2 if a in "yx" else 3.0 for a in axes
        ]
    assert support.inspect_ome_zarr_image(store).supported
    normalized = snapshot(store)
    assert support.normalize_native_ome_zarr_copy(store) is None
    assert snapshot(store) == normalized


@pytest.mark.parametrize(
    "limit,value",
    [
        (support.OME_ZARR_NATIVE_MAX_ARRAY_BYTES_ENV, "128"),
        (support.OME_ZARR_NATIVE_MAX_CHUNKS_ENV, "1"),
    ],
)
def test_v3_regeneration_bounds_fail_before_modifying_store(
    tmp_path, monkeypatch, limit, value
):
    """Inputs: bounded normalization fixtures. Output: rejection without mutation."""
    store = tmp_path / "image.ome.zarr"
    make_store(store, "zyx", z_downsample=True)
    before = snapshot(store)
    monkeypatch.setenv(limit, value)

    error = support.normalize_native_ome_zarr_copy(store)

    assert "exceeds configured limit" in error
    assert snapshot(store) == before


def test_v3_consolidated_metadata_is_not_left_stale(tmp_path):
    """Inputs: a consolidated 3D store. Output: fresh metadata and shape assertions."""
    store = tmp_path / "image.ome.zarr"
    make_store(store, "zyx", z_downsample=True)
    with pytest.warns(UserWarning, match="Consolidated metadata"):
        zarr.consolidate_metadata(str(store))
    assert "consolidated_metadata" in json.loads((store / "zarr.json").read_text())

    assert support.normalize_native_ome_zarr_copy(store) is None

    group = zarr.open_group(str(store), mode="r")
    paths = group.attrs["ome"]["multiscales"][0]["datasets"]
    assert all(group[entry["path"]].shape[0] == 4 for entry in paths)
    assert group.attrs["application_metadata"] == {"retain": True}


@pytest.mark.parametrize("path", ["s0", "s0/nested", ".", "../outside"])
def test_overlapping_or_escaping_paths_are_rejected_before_mutation(tmp_path, path):
    """Inputs: conflicting/escaping levels. Output: rejection and byte equality."""
    store = tmp_path / "image.ome.zarr"
    make_store(store, "zyx", z_downsample=True, later=True)
    group = zarr.open_group(str(store), mode="r+")
    ome = group.attrs["ome"]
    if path == "s0/nested":
        shutil.copytree(store / "s2", store / path)
    ome["multiscales"][0]["datasets"][2]["path"] = path
    group.attrs["ome"] = ome
    before = snapshot(store)

    error = support.normalize_native_ome_zarr_copy(store)

    assert error and "path" in error
    assert snapshot(store) == before


def test_v3_oversized_physical_chunk_fails_without_decoding(tmp_path, monkeypatch):
    """Inputs: oversized physical chunks. Output: bounded pre-decode rejection."""
    store = tmp_path / "image.ome.zarr"
    _, datasets = make_store(store, "zyx", z_downsample=True)
    path = store / datasets[0]["path"] / "zarr.json"
    metadata = json.loads(path.read_text())
    metadata["chunk_grid"]["configuration"]["chunk_shape"] = [4, 1024, 1024]
    path.write_text(json.dumps(metadata))
    monkeypatch.setenv(support.OME_ZARR_NATIVE_MAX_ARRAY_BYTES_ENV, "65536")
    before = snapshot(store)

    error = support.normalize_native_ome_zarr_copy(store)

    assert "chunk array size" in error and "exceeds configured limit" in error
    assert snapshot(store) == before


def test_v3_write_failure_preserves_full_resolution_and_returns_error(
    tmp_path, monkeypatch
):
    """Inputs: a failing pyramid writer. Output: an error with original pixels intact."""
    store = tmp_path / "image.ome.zarr"
    _, datasets = make_store(store, "zyx", z_downsample=True)
    full_root = store / datasets[0]["path"]
    before = snapshot(full_root)

    def fail_create(*_args, **_kwargs):
        """Inputs: array creation arguments. Output: a synthetic filesystem error."""
        raise OSError("Synthetic storage write failure")

    monkeypatch.setattr(zarr, "create", fail_create)
    error = support.normalize_native_ome_zarr_copy(store)

    assert "Synthetic storage write failure" in error
    assert snapshot(full_root) == before


@pytest.mark.parametrize("entry", [None, {"path": "../outside"}])
def test_pyramid_detection_rejects_malformed_later_levels(tmp_path, entry):
    """Inputs: malformed later levels. Output: safe rejection and no store mutation."""
    store = tmp_path / "image.ome.zarr"
    make_store(store, "zyx", z_downsample=True, later=True)
    group = zarr.open_group(str(store), mode="r+")
    ome = group.attrs["ome"]
    ome["multiscales"][0]["datasets"][2] = entry
    group.attrs["ome"] = ome
    before = snapshot(store)

    assert support._has_3d_pyramid_downsampling(store) is None
    assert snapshot(store) == before
