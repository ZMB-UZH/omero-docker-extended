from pathlib import Path

import numpy as np
import pytest

from omero_web_zarr.utils import open_compat_array


def test_open_compat_array_writes_v2_metadata_under_zarr3(tmp_path):
    open_compat_array(
        tmp_path,
        mode="w",
        shape=(2, 3, 4),
        chunks=(1, 3, 4),
        dtype=np.uint16,
    )

    assert (tmp_path / ".zarray").exists()
    assert (tmp_path / ".zattrs").exists()
    assert not (tmp_path / "zarr.json").exists()


def test_open_compat_array_retries_without_zarr_format_when_unsupported(tmp_path, monkeypatch):
    calls = []

    def fake_open_array(path, **kwargs):
        calls.append(kwargs.copy())
        if "zarr_format" in kwargs:
            raise TypeError("open_array() got an unexpected keyword argument 'zarr_format'")
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / ".zarray").write_text("{}", encoding="utf-8")
        return object()

    monkeypatch.setattr("omero_web_zarr.utils.zarr.open_array", fake_open_array)

    open_compat_array(
        tmp_path,
        mode="w",
        shape=(1,),
        chunks=(1,),
        dtype=np.uint8,
    )

    assert calls[0]["zarr_format"] == 2
    assert "zarr_format" not in calls[1]


def test_open_compat_array_does_not_hide_other_type_errors(tmp_path, monkeypatch):
    def fake_open_array(path, **kwargs):
        raise TypeError("different failure")

    monkeypatch.setattr("omero_web_zarr.utils.zarr.open_array", fake_open_array)

    with pytest.raises(TypeError, match="different failure"):
        open_compat_array(
            tmp_path,
            mode="w",
            shape=(1,),
            chunks=(1,),
            dtype=np.uint8,
        )
