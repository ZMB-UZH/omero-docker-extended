from __future__ import annotations

import os
import subprocess

import pytest

from omeroweb_import.views import core_functions


def test_append_job_messages_errors_and_txt_labels_trim_to_limit(monkeypatch) -> None:
    monkeypatch.setattr(core_functions, "MAX_IMPORT_LOG_LINES", 2)
    job = {}

    core_functions._append_job_message(job, "first")
    core_functions._append_job_message(job, "second")
    core_functions._append_job_message(job, "third")
    core_functions._append_job_error(job, "error-1")
    core_functions._append_job_error(job, "error-2")
    core_functions._append_job_error(job, "error-3")
    core_functions._append_txt_attachment_message(
        job, "report.txt", "image.ome.tif", True
    )

    assert job["messages"] == [
        "third",
        "Txt attachment success: report.txt into image.ome.tif",
    ]
    assert job["errors"] == ["error-2", "error-3"]


def test_job_id_and_managed_path_helpers_enforce_managed_roots(
    monkeypatch, tmp_path
) -> None:
    upload_root = tmp_path / "uploads"
    jobs_root = tmp_path / "jobs"
    upload_root.mkdir()
    jobs_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    assert core_functions._safe_job_id("a" * 32) is True
    assert core_functions._safe_job_id("../bad") is False
    assert core_functions._validated_job_id("A" * 32) == "a" * 32
    assert core_functions._job_lock_path("a" * 32) == jobs_root / f".{'a' * 32}.lock"
    assert core_functions._resolve_managed_child_path(
        upload_root, "nested/file.txt"
    ) == (upload_root / "nested" / "file.txt")
    assert core_functions._resolve_managed_directory_path(upload_root / "nested") == (
        upload_root / "nested"
    )

    try:
        core_functions._resolve_managed_child_path(upload_root, "../escape.txt")
    except ValueError as exc:
        assert "Invalid" in str(exc) or "outside" in str(exc).lower()
    else:
        raise AssertionError("Expected path traversal rejection")

    try:
        core_functions._resolve_managed_directory_path(tmp_path / "outside")
    except ValueError as exc:
        assert "outside managed upload roots" in str(exc)
    else:
        raise AssertionError("Expected outside-root rejection")


def test_resolve_managed_child_path_rejects_symlinked_segments(
    monkeypatch, tmp_path
) -> None:
    upload_root = tmp_path / "uploads"
    jobs_root = tmp_path / "jobs"
    outside_root = tmp_path / "outside"
    upload_root.mkdir()
    jobs_root.mkdir()
    outside_root.mkdir()
    (upload_root / "linked").symlink_to(outside_root, target_is_directory=True)

    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    try:
        core_functions._resolve_managed_child_path(upload_root, "linked/escape.txt")
    except ValueError as exc:
        assert "Invalid filename" in str(exc)
    else:
        raise AssertionError("Expected symlinked managed path rejection")


def test_managed_path_helpers_reject_embedded_null_bytes(monkeypatch, tmp_path) -> None:
    upload_root = tmp_path / "uploads"
    jobs_root = tmp_path / "jobs"
    upload_root.mkdir()
    jobs_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)

    with pytest.raises(ValueError, match="Invalid filename"):
        core_functions._resolve_managed_child_parts(upload_root, ("bad\x00name",))


def test_staged_upload_file_helpers_reject_symlink_leaf_targets(tmp_path) -> None:
    class _Upload:
        def __init__(self, *chunks):
            self._chunks = chunks

        def chunks(self):
            return list(self._chunks)

    upload_root = tmp_path / "uploads"
    outside_root = tmp_path / "outside"
    upload_root.mkdir()
    outside_root.mkdir()
    protected = outside_root / "file.bin"
    protected.write_bytes(b"outside")

    staged_dir = upload_root / "_staged" / "folder"
    staged_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(protected, staged_dir / "file.bin")

    bytes_written, size, append_error = (
        core_functions._append_upload_chunks_to_staged_path(
            upload_root,
            "_staged/folder/file.bin",
            _Upload(b"hello"),
        )
    )
    assert bytes_written is None
    assert size is None
    assert "Invalid filename" in append_error
    assert protected.read_bytes() == b"outside"

    size, size_error = core_functions._staged_upload_size(
        upload_root, "_staged/folder/file.bin"
    )
    assert size is None
    assert "Invalid filename" in size_error

    reset_error = core_functions._reset_staged_upload_file(
        upload_root, "_staged/folder/file.bin"
    )
    assert "Invalid filename" in reset_error
    assert protected.read_bytes() == b"outside"

    size, replace_error = core_functions._replace_staged_upload_file(
        upload_root,
        "_staged/folder/file.bin",
        _Upload(b"replaced"),
    )
    assert size is None
    assert "Invalid filename" in replace_error
    assert protected.read_bytes() == b"outside"


def test_replace_staged_upload_file_creates_private_modes(tmp_path) -> None:
    class _Upload:
        def __init__(self, *chunks):
            self._chunks = chunks

        def chunks(self):
            return list(self._chunks)

    upload_root = tmp_path / "uploads"
    upload_root.mkdir()

    size, replace_error = core_functions._replace_staged_upload_file(
        upload_root,
        "_staged/folder/file.bin",
        _Upload(b"replaced"),
    )

    created_dir = upload_root / "_staged" / "folder"
    created_file = created_dir / "file.bin"
    assert replace_error is None
    assert size == len(b"replaced")
    assert created_file.read_bytes() == b"replaced"
    assert (created_dir.stat().st_mode & 0o777) == 0o700
    assert (created_file.stat().st_mode & 0o777) == 0o600


def test_write_read_job_file_and_apply_upload_updates(monkeypatch, tmp_path) -> None:
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_fsync_jobs_directory", lambda: None)

    job_id = "a" * 32
    initial = {
        "job_id": job_id,
        "files": [
            {"upload_id": "u1", "status": "pending", "size": 5, "errors": []},
            {"upload_id": "u2", "status": "uploaded", "size": 7, "errors": []},
        ],
        "compatibility_enabled": True,
        "compatibility_status": "",
        "status": "uploading",
    }
    assert core_functions._write_job_file(job_id, initial) is True
    assert core_functions._read_job_file(job_id)["job_id"] == job_id

    monkeypatch.setattr(core_functions, "JOB_LOCK_RETRIES", 1)
    monkeypatch.setattr(core_functions, "JOB_LOCK_TIMEOUT_SECONDS", 0.01)

    updated = core_functions._apply_upload_updates(
        job_id,
        updates=[
            {"upload_id": "u1", "status": "uploaded"},
            {"upload_id": "u2", "status": "error", "errors": ["broken"]},
            {"upload_id": "missing", "status": "uploaded"},
        ],
        errors=["job-level"],
    )

    assert updated["uploaded_bytes"] == 5
    assert updated["files"][0]["status"] == "uploaded"
    assert updated["files"][1]["status"] == "error"
    assert updated["files"][1]["errors"] == ["broken"]
    assert updated["errors"] == ["job-level"]
    assert updated["compatibility_status"] == "checking"
    assert updated["status"] == "checking"


def test_compatibility_output_parsers_cover_candidates_groups_and_failures(
    tmp_path,
) -> None:
    image_path = tmp_path / "plate.zarr" / "0" / "0"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_text("chunk", encoding="utf-8")
    group_output = "\n".join(
        [
            "2 file(s) parsed into 1 group(s) with 1 call(s) to setId",
            f"# Group: {tmp_path / 'plate.zarr'} SPW: false",
            str(tmp_path / "plate.zarr" / ".zattrs"),
            str(image_path),
        ]
    )

    assert core_functions._parse_candidate_path_line(str(image_path)) == image_path
    assert core_functions._parse_candidate_path_line("not/a/path") is None
    assert core_functions._extract_import_candidates(group_output) == [
        str(tmp_path / "plate.zarr" / ".zattrs"),
        str(image_path),
    ]
    assert core_functions._parse_import_groups(group_output)[0]["members"] == [
        tmp_path / "plate.zarr" / ".zattrs",
        image_path,
    ]
    assert (
        core_functions._has_import_candidates_in_output(
            group_output,
            expected_file_path=tmp_path / "plate.zarr",
        )
        is True
    )
    assert core_functions._classify_compatibility_output(0, group_output, "") == (
        "compatible",
        "File format supported by OMERO",
    )
    assert (
        core_functions._classify_compatibility_output(
            0,
            "",
            "No reader found for file",
        )[0]
        == "incompatible"
    )
    assert (
        core_functions._classify_compatibility_output(
            1,
            "",
            "Permission denied",
        )[0]
        == "error"
    )


def test_relative_root_helpers_detect_directory_package_shapes() -> None:
    active_paths = [
        "plate.zarr/.zattrs",
        "plate.zarr/OME/METADATA.ome.xml",
        "plate.zarr/0/0/0",
        "other/file.txt",
    ]
    covered = active_paths[:-1]

    assert core_functions._relative_path_within_root(
        "plate.zarr/OME/METADATA.ome.xml", "plate.zarr"
    )
    assert (
        core_functions._common_relative_prefix(
            ["plate.zarr/OME/METADATA.ome.xml", "plate.zarr/0/0/0"]
        )
        == "plate.zarr"
    )
    assert (
        core_functions._group_covers_all_active_paths_under_root(
            active_paths,
            "plate.zarr",
            covered,
        )
        is True
    )
    assert (
        core_functions._looks_like_directory_package_root(
            active_paths,
            "plate.zarr",
            "plate.zarr/OME/METADATA.ome.xml",
            covered,
        )
        is True
    )


def test_collect_import_entries_and_single_entry_units() -> None:
    job = {
        "files": [
            {"relative_path": "a.tif", "status": "uploaded"},
            {"relative_path": "b.tif", "status": "pending"},
            {"relative_path": "c.tif", "status": "error"},
            {"relative_path": "d.tif", "status": "uploaded", "import_skip": True},
            {
                "relative_path": "e.tif",
                "status": "uploaded",
                "compatibility": "compatible",
            },
        ]
    }

    normal_entries = core_functions._collect_import_entries(job)
    compat_entries = core_functions._collect_import_entries(job, for_compatibility=True)
    unit = core_functions._single_entry_import_unit(normal_entries[0])

    assert [entry["relative_path"] for entry in normal_entries] == [
        "a.tif",
        "b.tif",
        "e.tif",
    ]
    assert [entry["relative_path"] for entry in compat_entries] == ["a.tif"]
    assert unit == {
        "cleanup_staged_paths": ["_staged/a.tif"],
        "covered_indexes": [0],
        "covered_relative_paths": ["a.tif"],
        "dataset_relative_path": "a.tif",
        "index": 0,
        "relative_path": "a.tif",
        "staged_path": "_staged/a.tif",
    }


def test_probe_import_path_caches_group_coverage_and_scan_failures(
    monkeypatch, tmp_path
) -> None:
    staged_root = tmp_path / "staged"
    path = staged_root / "plate.zarr"
    active_paths = [
        "plate.zarr/.zattrs",
        "plate.zarr/OME/METADATA.ome.xml",
        "plate.zarr/0/0/0",
    ]
    cache = {}
    stdout = "\n".join(
        [
            f"# Group: {path / 'OME' / 'METADATA.ome.xml'} SPW: false",
            str(path / ".zattrs"),
            str(path / "OME" / "METADATA.ome.xml"),
            str(path / "0" / "0" / "0"),
        ]
    )
    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda current_path: subprocess.CompletedProcess(
            args=["omero", "import"],
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    )

    result = core_functions._probe_import_path(path, staged_root, active_paths, cache)
    cached = core_functions._probe_import_path(path, staged_root, active_paths, cache)

    assert result["coverage"] == set(active_paths)
    assert result["groups"][0]["covered_relative_paths"] == tuple(active_paths)
    assert cached is result

    monkeypatch.setattr(
        core_functions,
        "_run_local_import_scan",
        lambda current_path: (_ for _ in ()).throw(RuntimeError("scan failed")),
    )
    failed = core_functions._probe_import_path(
        staged_root / "broken.pkg",
        staged_root,
        active_paths,
        {},
    )
    assert failed["returncode"] == -1
    assert failed["stderr"] == "scan failed"
