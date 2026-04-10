from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from omeroweb_import.views import core_functions


class _FakeValue:
    def __init__(self, value):
        self.val = value

    def getValue(self):
        return self.val


class _FakeLength:
    def __init__(self, value, unit):
        self._value = value
        self._unit = unit

    def getValue(self):
        return self._value

    def getUnit(self):
        return self._unit


class _FakeUnit:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


def test_job_gate_helpers_cover_pending_compatibility_and_plan_build(monkeypatch):
    monkeypatch.setenv(core_functions.UPLOAD_BATCH_FILES_ENV, "25")

    assert core_functions._normalize_job_batch_size("0", 5) == 1
    assert core_functions._normalize_job_batch_size("17", 5) == 10
    assert core_functions._normalize_sem_edx_settings(None) == dict(
        core_functions.SEM_EDX_SETTINGS_DEFAULTS
    )
    assert core_functions._normalize_sem_edx_settings(
        {"create_tables": 0, "create_figures_attachments": "yes"}
    )["create_figures_attachments"]
    assert core_functions._resolve_job_batch_size({}) == 10

    pending_job = {
        "files": [{"status": "pending"}, {"status": "uploaded"}],
        "compatibility_enabled": True,
    }
    assert core_functions._has_pending_uploads(pending_job) is True
    assert core_functions._should_start_compatibility_check(pending_job) is False
    assert core_functions._refresh_job_status(pending_job)["status"] == "uploading"

    compatibility_job = {
        "files": [
            {"status": "uploaded"},
            {"status": "uploaded", "compatibility": True},
            {"status": "uploaded", "compatibility_skip": True},
        ],
        "compatibility_enabled": True,
    }
    assert core_functions._compatibility_pending_entries(compatibility_job) == [
        {"status": "uploaded"}
    ]
    assert core_functions._should_start_compatibility_check(compatibility_job) is True

    monkeypatch.setattr(
        core_functions,
        "_planned_import_units_for_request",
        lambda job_dict: [],
    )
    import_plan_job = {
        "compatibility_enabled": False,
        "compatibility_thread_active": False,
        "status": "queued",
        "files": [
            {"status": "uploaded", "relative_path": "demo.ome.tif"},
            {"status": "uploaded", "import_skip": True},
        ],
    }
    assert core_functions._should_start_import_plan_build(import_plan_job) is True

    incompatible_job = {"files": [], "compatibility_status": "incompatible"}
    assert (
        core_functions._refresh_job_status(incompatible_job)["status"]
        == "awaiting_confirmation"
    )
    error_job = {"files": [], "compatibility_status": "error"}
    assert core_functions._refresh_job_status(error_job)["status"] == "ready"

    skipped_job = {
        "files": [{"status": "uploaded", "compatibility_skip": True}],
        "compatibility_status": "checking",
    }
    refreshed = core_functions._refresh_job_status(skipped_job)
    assert refreshed["compatibility_status"] == "compatible"
    assert refreshed["status"] == "ready"


def test_path_and_sem_edx_helpers_normalize_and_validate_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(
        core_functions, "MAX_UPLOAD_RELATIVE_PATH_BYTES", 12, raising=False
    )
    monkeypatch.setattr(
        core_functions, "MAX_UPLOAD_PATH_COMPONENT_BYTES", 6, raising=False
    )
    monkeypatch.setattr(
        core_functions, "MAX_UPLOAD_STAGED_TARGET_BYTES", 20, raising=False
    )

    assert core_functions._safe_relative_path(r"dir\file.txt") == "dir/file.txt"
    assert core_functions._safe_relative_path("/abs/path") is None
    assert core_functions._safe_relative_path("../escape") is None
    assert core_functions._safe_relative_path("") is None
    assert "too long" in core_functions._validate_relative_path_lengths("dir/toolong")
    assert core_functions._normalize_upload_relative_path("../escape")[0] is None

    resolved, error = core_functions._resolve_root_relative_path(tmp_path, "nest/f.txt")
    assert resolved == tmp_path / "nest" / "f.txt"
    assert error is None

    assert core_functions._resolve_root_relative_path(tmp_path, "../escape")[0] is None
    assert (
        core_functions._build_staged_relative_path("nested/file.txt")
        == "_staged/nested/file.txt"
    )
    assert core_functions._should_auto_skip_import(".DS_Store") is True
    assert core_functions._should_auto_skip_import("lost+found/data.bin") is True
    assert core_functions._should_auto_skip_import("dataset/metadata.xml") is False

    entries = [
        {
            "relative_path": "dataset/image.tif",
            "staged_path": "_staged/dataset/image.tif",
        },
        {
            "relative_path": "dataset/spectrum.txt",
            "staged_path": "_staged/dataset/spectrum.txt",
        },
        {"relative_path": "dataset/readme.md"},
    ]
    normalized = core_functions._normalize_sem_edx_associations(
        {
            "_staged/dataset/image.tif": [
                "_staged/dataset/spectrum.txt",
                "_staged/dataset/spectrum.txt",
                "dataset/readme.md",
            ],
            "dataset/spectrum.txt": ["dataset/spectrum.txt"],
        },
        entries,
    )
    assert normalized == {"_staged/dataset/image.tif": ["_staged/dataset/spectrum.txt"]}

    derived = core_functions._build_sem_edx_associations_from_entries(
        [
            {"relative_path": "group/image_b.tif"},
            {"relative_path": "group/image_a.tif"},
            {"relative_path": "group/spec-2.txt"},
            {"relative_path": "group/spec-1.txt"},
            {"relative_path": "other/orphan.txt"},
        ]
    )
    assert derived == {"group/image_a.tif": ["group/spec-1.txt", "group/spec-2.txt"]}


def test_resolve_root_relative_path_returns_safe_validation_errors(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        core_functions,
        "_managed_runtime_validation_error",
        lambda root, relative_parts, max_bytes=None: (
            core_functions.errors.invalid_filename("/".join(relative_parts))
        ),
    )

    resolved, error = core_functions._resolve_root_relative_path(tmp_path, "nest/f.txt")

    assert resolved is None
    assert error == core_functions.errors.invalid_filename("nest/f.txt")
    assert "secret" not in error


def test_external_info_units_and_dataset_helpers_cover_aliases_and_fallbacks(
    monkeypatch,
):
    assert (
        core_functions._get_text(SimpleNamespace(getValue=lambda: "value")) == "value"
    )
    assert core_functions._get_text(SimpleNamespace(val=None)) == ""
    assert (
        core_functions._external_info_text(
            SimpleNamespace(
                lsid=SimpleNamespace(val=""), getLsid=lambda: _FakeValue("file:/store")
            ),
            "lsid",
            "getLsid",
        )
        == "file:/store"
    )

    class _ParametersI:
        def addId(self, value):
            self.value = value
            return self

    monkeypatch.setattr(core_functions.omero.sys, "ParametersI", _ParametersI)
    projection_rows = [[_FakeValue("lsid://demo"), _FakeValue("ome.zarr")]]
    conn = SimpleNamespace(
        SERVICE_OPTS="opts",
        getQueryService=lambda: SimpleNamespace(
            projection=lambda query, params, opts: projection_rows
        ),
    )
    assert core_functions._query_image_external_info(conn, 12) == (
        "lsid://demo",
        "ome.zarr",
    )
    assert core_functions._query_image_external_info(None, 12) == ("", "")

    units = {
        name: _FakeUnit(name) for name in ("METER", "MICROMETER", "NANOMETER", "PIXEL")
    }

    class _FakeUnitsLength:
        _enumerators = {index: unit for index, unit in enumerate(units.values())}

    for name, unit in units.items():
        setattr(_FakeUnitsLength, name, unit)

    fake_enums_module = types.ModuleType("omero.model.enums")
    fake_enums_module.UnitsLength = _FakeUnitsLength
    monkeypatch.setitem(sys.modules, "omero.model.enums", fake_enums_module)
    monkeypatch.setattr(
        sys.modules["omero.model"], "LengthI", _FakeLength, raising=False
    )
    core_functions._units_length_for_name.cache_clear()
    core_functions._units_length_by_normalized_name.cache_clear()
    core_functions._units_length_symbol_aliases.cache_clear()

    assert core_functions._normalize_units_length_name("Micro-meters") == "micrometer"
    assert core_functions._units_length_for_name("µm").name == "MICROMETER"
    length = core_functions._native_zarr_length_from_value_unit(("2.5", "µm"))
    assert core_functions._native_zarr_length_signature(length) == (2.5, "micrometer")
    assert core_functions._native_zarr_length_from_value_unit(("bad", "µm")) is None
    assert (
        core_functions._native_zarr_image_relative_path_from_lsid(
            Path("/root/store"),
            "/root/store/0?version=1",
        )
        == "0"
    )
    assert (
        core_functions._native_zarr_image_relative_path_from_lsid(
            Path("/root/store"),
            "/root/store",
        )
        is None
    )
    with pytest.raises(ValueError):
        core_functions._native_zarr_image_relative_path_from_lsid(
            Path("/root/store"),
            "",
        )

    package_entry = {
        "relative_path": "plates/demo.ome.zarr",
        "dataset_relative_path": "plates/demo.ome.zarr",
        "covered_relative_paths": [
            "plates/demo.ome.zarr",
            "plates/demo.ome.zarr/0/.zarray",
        ],
    }
    assert (
        core_functions._dataset_name_for_upload_relative_path(
            "plates/demo.ome.zarr/0/.zarray"
        )
        == "plates\\demo.ome.zarr"
    )
    assert core_functions._logical_unit_is_directory_package_root(package_entry) is True
    assert (
        core_functions._dataset_name_for_import_entry(package_entry, "UploadRoot_TEST")
        == "plates\\demo.ome.zarr"
    )

    monkeypatch.setattr(
        core_functions, "_generate_orphan_dataset_name", lambda: "UploadRoot_TEST"
    )
    orphan_dataset, dataset_names = core_functions._plan_job_dataset_targets(
        {"orphan_dataset_name": None},
        [
            {
                "relative_path": "image.ome.tif",
                "covered_relative_paths": ["image.ome.tif"],
            },
            {
                "relative_path": "folder/demo.ome.tif",
                "dataset_relative_path": "folder/demo.ome.tif",
                "covered_relative_paths": ["folder/demo.ome.tif"],
            },
        ],
    )
    assert orphan_dataset == "UploadRoot_TEST"
    assert dataset_names == ["UploadRoot_TEST", "folder"]


def test_cli_and_shared_zarr_helpers_cover_env_and_safe_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv(core_functions.CLI_KEEPALIVE_SECONDS_ENV, "9999")
    monkeypatch.setenv(core_functions.LOCAL_IMPORT_SCAN_TIMEOUT_SECONDS_ENV, "1")
    monkeypatch.setenv(core_functions.SCRIPT_START_TIMEOUT_SECONDS_ENV, "0")
    monkeypatch.setenv(core_functions.SCRIPT_START_RETRY_SECONDS_ENV, "0")
    monkeypatch.setenv(core_functions.FAILED_IMPORT_RETENTION_SECONDS_ENV, "999999999")

    assert core_functions._build_omero_cli_command(
        ["import", "sample.tif"],
        "session-key",
        "omeroserver",
        4064,
    ) == [
        core_functions.OMERO_CLI,
        "-k",
        "session-key",
        "-s",
        "omeroserver",
        "-p",
        "4064",
        "import",
        "sample.tif",
    ]
    assert core_functions._get_cli_keepalive_seconds() == 3600
    assert core_functions._get_local_import_scan_timeout_seconds() == 30
    assert core_functions._get_script_start_timeout_seconds() == 1
    assert core_functions._get_script_start_retry_seconds() == 1
    assert core_functions._get_failed_import_retention_seconds() == 30 * 24 * 60 * 60
    assert "***" in core_functions._sanitize_cli_output_for_logging(
        "job=123e4567-e89b-12d3-a456-426614174000"
    )
    assert core_functions._extract_imported_object_ids(
        "Image:1\nFileset:2\nCreated Image 3\nImage:1"
    ) == ["1", "2", "3"]
    assert core_functions._extract_imported_image_ids_for_normalization(
        "Fileset:2\nPlate:4\n",
        ["7", "8", "7"],
    ) == [7, 8]
    assert (
        core_functions._extract_imported_image_ids_for_normalization(
            "Fileset:2\nPlate:4\n"
        )
        == []
    )
    assert core_functions._reports_no_processor_available("NoProcessorAvailable", "")
    assert core_functions._reports_no_processor_available("", "No processor available")
    assert core_functions._get_background_import_session_timeout_seconds(10) == (
        core_functions.BACKGROUND_IMPORT_SESSION_MIN_SECONDS
    )
    assert (
        core_functions._get_background_import_session_timeout_seconds(999999999)
        == core_functions.BACKGROUND_IMPORT_SESSION_MAX_SECONDS
    )

    cli_home = tmp_path / "cli-home"
    cli_home.mkdir()
    base_config = tmp_path / "base-ice.config"
    base_config.write_text("Ice.Default.Router=test-router\n", encoding="utf-8")
    merged_config = core_functions._write_cli_ice_config(cli_home, 45, str(base_config))
    assert merged_config is not None
    assert merged_config.read_text(encoding="utf-8") == (
        "Ice.Default.Router=test-router\nomero.keep_alive=45\n"
    )
    assert core_functions._write_cli_ice_config(cli_home, 0) is None
    assert (
        core_functions._parse_cli_id(
            "Created OriginalFile:123\nCreated FileAnnotation:456",
            "FileAnnotation",
        )
        == 456
    )

    size_root = tmp_path / "sizes"
    size_root.mkdir()
    (size_root / "a.bin").write_bytes(b"a")
    (size_root / "nested").mkdir()
    (size_root / "nested" / "b.bin").write_bytes(b"bc")
    assert core_functions._get_path_total_size(size_root) == 3

    transfer_root = tmp_path / "shared-transfer"
    transfer_root.mkdir()
    monkeypatch.setattr(
        core_functions, "get_plugin_tmp_dir", lambda name: transfer_root
    )
    monkeypatch.setattr(core_functions, "_prepare_native_zarr_copy", lambda path: None)

    source = tmp_path / "source.ome.zarr"
    (source / "0").mkdir(parents=True)
    (source / "0" / ".zarray").write_text("{}", encoding="utf-8")

    shared_source, parent_dir, error = (
        core_functions._prepare_server_readable_zarr_source(source)
    )
    assert error is None
    assert shared_source is not None
    assert parent_dir is not None
    assert shared_source.exists()
    assert shared_source.name == source.name

    outside = tmp_path / "outside"
    outside.mkdir()
    core_functions._cleanup_shared_zarr_transfer(outside)
    assert outside.exists()
    core_functions._cleanup_shared_zarr_transfer(transfer_root)
    assert transfer_root.exists()
    core_functions._cleanup_shared_zarr_transfer(parent_dir)
    assert not parent_dir.exists()
