from __future__ import annotations

import logging

from omeroweb_import.views import core_functions


def test_native_zarr_plan_roundtrip_preserves_routing_metadata() -> None:
    plan = core_functions._NativeZarrImportPlan(
        kind=core_functions._NATIVE_ZARR_KIND_BIOFORMATS2RAW,
        recognized_zarr=True,
        validation_error="unsupported plate layout",
        verify_lsid_prefix=True,
        compatibility_details="detected by ome-zarr",
    )

    payload = core_functions._serialize_native_zarr_plan(plan)
    restored = core_functions._deserialize_native_zarr_plan(payload)

    assert payload == {
        "kind": core_functions._NATIVE_ZARR_KIND_BIOFORMATS2RAW,
        "recognized_zarr": True,
        "validation_error": "unsupported plate layout",
        "verify_lsid_prefix": True,
        "compatibility_details": "detected by ome-zarr",
    }
    assert restored == plan


def test_serialize_native_zarr_plan_omits_empty_or_invalid_payloads() -> None:
    assert core_functions._serialize_native_zarr_plan(core_functions._NativeZarrImportPlan()) is None

    restored = core_functions._deserialize_native_zarr_plan(["not", "a", "dict"])
    assert restored == core_functions._NativeZarrImportPlan()


def test_cleanup_shared_zarr_transfer_removes_child_within_transfer_root(tmp_path, monkeypatch) -> None:
    transfer_root = tmp_path / "managed-zarr-transfer"
    protected_sibling = transfer_root / "sibling"
    target = transfer_root / "token"
    (target / "store.zarr").mkdir(parents=True)
    protected_sibling.mkdir(parents=True)
    monkeypatch.setattr(core_functions, "_shared_zarr_transfer_root", lambda: transfer_root)

    core_functions._cleanup_shared_zarr_transfer(target)

    assert not target.exists()
    assert protected_sibling.exists()


def test_cleanup_shared_zarr_transfer_refuses_root_and_outside_paths(tmp_path, monkeypatch, caplog) -> None:
    transfer_root = tmp_path / "managed-zarr-transfer"
    transfer_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(core_functions, "_shared_zarr_transfer_root", lambda: transfer_root)

    with caplog.at_level(logging.WARNING, logger=core_functions.logger.name):
        core_functions._cleanup_shared_zarr_transfer(transfer_root)
        core_functions._cleanup_shared_zarr_transfer(outside)

    assert transfer_root.exists()
    assert outside.exists()
    assert "Refusing to remove shared Zarr transfer root directly" in caplog.text
    assert "Refusing to remove shared Zarr transfer path outside" in caplog.text
