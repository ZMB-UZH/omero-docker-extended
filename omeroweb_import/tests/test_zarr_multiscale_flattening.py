"""Tests for multi-resolution OME-NGFF zarr flattening.

OMERO's rendering engine (BfPixelBuffer) reads the wrong resolution level
from multi-resolution OME-NGFF zarrs, causing DimensionsOutOfBoundsException
at thumbnail time.  The import plugin strips lower resolution levels before
import so only the full-resolution data remains.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import django
from django.conf import settings

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

from omeroweb_import.views.core_functions import (
    _flatten_multiscale_zarr,
    _needs_multiscale_flattening,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_zattrs(zarr_dir: Path, attrs: dict) -> Path:
    """Write a .zattrs file into *zarr_dir* and return its path."""
    zarr_dir.mkdir(parents=True, exist_ok=True)
    zattrs = zarr_dir / ".zattrs"
    zattrs.write_text(json.dumps(attrs), encoding="utf-8")
    return zattrs


def _make_multiscale_zarr(zarr_dir: Path, dataset_paths: list[str]) -> Path:
    """Create a minimal OME-NGFF multiscale zarr with stub resolution dirs."""
    datasets = [{"path": p} for p in dataset_paths]
    attrs = {"multiscales": [{"datasets": datasets, "version": "0.4"}]}
    _write_zattrs(zarr_dir, attrs)
    for p in dataset_paths:
        sub = zarr_dir / p
        sub.mkdir(parents=True, exist_ok=True)
        (sub / ".zarray").write_text('{"shape":[1]}', encoding="utf-8")
        # Create a dummy chunk so the directory is non-empty.
        (sub / "0").write_text("chunk", encoding="utf-8")
    return zarr_dir


# ---------------------------------------------------------------------------
# _needs_multiscale_flattening
# ---------------------------------------------------------------------------

class TestNeedsMultiscaleFlattening:

    def test_returns_true_for_multiscale_with_multiple_datasets(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["s0", "s1", "s2"])
        assert _needs_multiscale_flattening(zarr) is True

    def test_returns_false_for_single_dataset(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["0"])
        assert _needs_multiscale_flattening(zarr) is False

    def test_returns_false_for_bioformats2raw_layout(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        datasets = [{"path": "0/0"}, {"path": "0/1"}, {"path": "0/2"}]
        attrs = {
            "bioformats2raw.layout": 3,
            "multiscales": [{"datasets": datasets}],
        }
        _write_zattrs(zarr_dir, attrs)
        assert _needs_multiscale_flattening(zarr_dir) is False

    def test_returns_false_for_missing_zattrs(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        zarr_dir.mkdir(parents=True)
        assert _needs_multiscale_flattening(zarr_dir) is False

    def test_returns_false_for_no_multiscales_key(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        _write_zattrs(zarr_dir, {"other": "data"})
        assert _needs_multiscale_flattening(zarr_dir) is False

    def test_returns_false_for_empty_datasets(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", [])
        assert _needs_multiscale_flattening(zarr) is False

    def test_returns_false_for_corrupt_json(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        zarr_dir.mkdir(parents=True)
        (zarr_dir / ".zattrs").write_text("{broken", encoding="utf-8")
        assert _needs_multiscale_flattening(zarr_dir) is False

    def test_handles_numeric_path_names(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["0", "1", "2", "3"])
        assert _needs_multiscale_flattening(zarr) is True

    def test_handles_arbitrary_path_names(self, tmp_path):
        zarr = _make_multiscale_zarr(
            tmp_path / "img.zarr", ["level0", "level1", "level2"]
        )
        assert _needs_multiscale_flattening(zarr) is True

    def test_handles_multiple_multiscales_entries(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        attrs = {
            "multiscales": [
                {"datasets": [{"path": "a0"}]},
                {"datasets": [{"path": "b0"}, {"path": "b1"}]},
            ]
        }
        _write_zattrs(zarr_dir, attrs)
        assert _needs_multiscale_flattening(zarr_dir) is True


# ---------------------------------------------------------------------------
# _flatten_multiscale_zarr
# ---------------------------------------------------------------------------

class TestFlattenMultiscaleZarr:

    def test_removes_lower_resolution_dirs(self, tmp_path):
        zarr = _make_multiscale_zarr(
            tmp_path / "img.zarr", ["s0", "s1", "s2", "s3"]
        )
        result = _flatten_multiscale_zarr(zarr)
        assert result is True
        assert (zarr / "s0").is_dir()
        assert not (zarr / "s1").exists()
        assert not (zarr / "s2").exists()
        assert not (zarr / "s3").exists()

    def test_updates_zattrs_metadata(self, tmp_path):
        zarr = _make_multiscale_zarr(
            tmp_path / "img.zarr", ["s0", "s1", "s2"]
        )
        _flatten_multiscale_zarr(zarr)
        with open(zarr / ".zattrs") as fh:
            attrs = json.load(fh)
        datasets = attrs["multiscales"][0]["datasets"]
        assert len(datasets) == 1
        assert datasets[0]["path"] == "s0"

    def test_preserves_full_resolution_data(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["s0", "s1"])
        # Write recognisable data into s0.
        (zarr / "s0" / "data.bin").write_text("full-res-data", encoding="utf-8")
        _flatten_multiscale_zarr(zarr)
        assert (zarr / "s0" / "data.bin").read_text(encoding="utf-8") == "full-res-data"

    def test_returns_false_for_single_dataset(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["0"])
        result = _flatten_multiscale_zarr(zarr)
        assert result is False
        assert (zarr / "0").is_dir()

    def test_returns_false_for_missing_zattrs(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        zarr_dir.mkdir(parents=True)
        assert _flatten_multiscale_zarr(zarr_dir) is False

    def test_handles_numeric_paths(self, tmp_path):
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["0", "1", "2"])
        _flatten_multiscale_zarr(zarr)
        assert (zarr / "0").is_dir()
        assert not (zarr / "1").exists()
        assert not (zarr / "2").exists()

    def test_handles_nested_resolution_paths(self, tmp_path):
        """Resolution paths can be nested (e.g. ``data/s0``)."""
        zarr_dir = tmp_path / "img.zarr"
        datasets = [{"path": "data/s0"}, {"path": "data/s1"}]
        attrs = {"multiscales": [{"datasets": datasets, "version": "0.4"}]}
        _write_zattrs(zarr_dir, attrs)
        for d in datasets:
            p = zarr_dir / d["path"]
            p.mkdir(parents=True)
            (p / "chunk").write_text("x", encoding="utf-8")
        _flatten_multiscale_zarr(zarr_dir)
        assert (zarr_dir / "data" / "s0").is_dir()
        assert not (zarr_dir / "data" / "s1").exists()

    def test_preserves_other_zattrs_keys(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        attrs = {
            "multiscales": [
                {"datasets": [{"path": "s0"}, {"path": "s1"}], "version": "0.4"}
            ],
            "omero": {"channels": []},
        }
        _write_zattrs(zarr_dir, attrs)
        for p in ("s0", "s1"):
            (zarr_dir / p).mkdir(parents=True)
        _flatten_multiscale_zarr(zarr_dir)
        with open(zarr_dir / ".zattrs") as fh:
            result = json.load(fh)
        assert result["omero"] == {"channels": []}
        assert len(result["multiscales"][0]["datasets"]) == 1

    def test_handles_multiple_multiscales_entries(self, tmp_path):
        zarr_dir = tmp_path / "img.zarr"
        attrs = {
            "multiscales": [
                {"datasets": [{"path": "a0"}, {"path": "a1"}]},
                {"datasets": [{"path": "b0"}, {"path": "b1"}, {"path": "b2"}]},
            ]
        }
        _write_zattrs(zarr_dir, attrs)
        for p in ("a0", "a1", "b0", "b1", "b2"):
            (zarr_dir / p).mkdir(parents=True)
        _flatten_multiscale_zarr(zarr_dir)
        assert (zarr_dir / "a0").is_dir()
        assert not (zarr_dir / "a1").exists()
        assert (zarr_dir / "b0").is_dir()
        assert not (zarr_dir / "b1").exists()
        assert not (zarr_dir / "b2").exists()

    def test_handles_missing_path_in_dataset_entry(self, tmp_path):
        """Dataset entries without a ``path`` key are skipped gracefully."""
        zarr_dir = tmp_path / "img.zarr"
        attrs = {
            "multiscales": [
                {"datasets": [{"path": "s0"}, {}, {"path": "s2"}]}
            ]
        }
        _write_zattrs(zarr_dir, attrs)
        for p in ("s0", "s2"):
            (zarr_dir / p).mkdir(parents=True)
        result = _flatten_multiscale_zarr(zarr_dir)
        assert result is True
        assert (zarr_dir / "s0").is_dir()
        assert not (zarr_dir / "s2").exists()

    def test_does_not_flatten_bioformats2raw_layout(self, tmp_path):
        """bioformats2raw zarrs must never be flattened, even if called directly."""
        zarr_dir = tmp_path / "img.zarr"
        attrs = {
            "bioformats2raw.layout": 3,
            "multiscales": [
                {"datasets": [{"path": "0/0"}, {"path": "0/1"}, {"path": "0/2"}]}
            ],
        }
        _write_zattrs(zarr_dir, attrs)
        for p in ("0/0", "0/1", "0/2"):
            (zarr_dir / p).mkdir(parents=True)
        result = _flatten_multiscale_zarr(zarr_dir)
        assert result is False
        assert (zarr_dir / "0" / "0").is_dir()
        assert (zarr_dir / "0" / "1").is_dir()
        assert (zarr_dir / "0" / "2").is_dir()

    def test_idempotent_on_already_flat_zarr(self, tmp_path):
        """Running on an already-flattened zarr is a no-op."""
        zarr = _make_multiscale_zarr(tmp_path / "img.zarr", ["s0", "s1"])
        _flatten_multiscale_zarr(zarr)
        # Run again — should return False (nothing to do).
        result = _flatten_multiscale_zarr(zarr)
        assert result is False
        assert (zarr / "s0").is_dir()
