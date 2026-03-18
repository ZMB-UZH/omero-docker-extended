"""Tests for grouped import planning and tree-preserving staging."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import django
from django.conf import settings
from django.test import RequestFactory

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

from omeroweb_upload.strings import errors
from omeroweb_upload.views import core_functions, index_view


def _stage_relative_paths(upload_root: Path, relative_paths: list[str]):
    staged_members = {}
    entries = []

    for index, relative_path in enumerate(relative_paths):
        staged_path = core_functions._build_staged_relative_path(relative_path)
        staged_target = upload_root / staged_path
        staged_target.parent.mkdir(parents=True, exist_ok=True)
        staged_target.write_text("x", encoding="utf-8")
        staged_members[relative_path] = staged_target
        entries.append(
            {
                "upload_id": f"u{index}",
                "relative_path": relative_path,
                "staged_path": staged_path,
                "size": 1,
                "status": "uploaded",
                "errors": [],
            }
        )

    return {"files": entries}, staged_members


def _group_stdout(group_path: Path, members: list[Path]) -> str:
    lines = [
        f"{len(members)} file(s) parsed into 1 group(s) with 1 call(s) to setId",
        f"# Group: {group_path} SPW: false",
    ]
    lines.extend(str(member) for member in members)
    return "\n".join(lines) + "\n"


def test_build_import_units_collapses_directory_package_to_single_logical_unit(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "plate.zarr/.zattrs",
            "plate.zarr/OME/METADATA.ome.xml",
            "plate.zarr/0/0/0",
        ],
    )

    package_root = upload_root / "_staged" / "plate.zarr"
    group_path = staged_members["plate.zarr/OME/METADATA.ome.xml"]

    def fake_scan(path: Path, timeout: int = 45):
        stdout = ""
        if path == package_root:
            stdout = _group_stdout(
                group_path,
                [
                    staged_members["plate.zarr/.zattrs"],
                    staged_members["plate.zarr/OME/METADATA.ome.xml"],
                    staged_members["plate.zarr/0/0/0"],
                ],
            )
        return subprocess.CompletedProcess(args=["omero", "import"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(core_functions, "_run_local_import_scan", fake_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert units == [
        {
            "cleanup_staged_paths": ["_staged/plate.zarr"],
            "covered_indexes": [0, 1, 2],
            "covered_relative_paths": [
                "plate.zarr/.zattrs",
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
            "dataset_relative_path": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
            "index": 0,
            "relative_path": "plate.zarr",
            "staged_path": "_staged/plate.zarr",
        }
    ]


def test_build_import_units_never_widens_cleanup_beyond_group_coverage(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "plate.zarr/.zattrs",
            "plate.zarr/OME/METADATA.ome.xml",
            "plate.zarr/0/0/0",
            "plate.zarr/notes/readme.txt",
        ],
    )

    package_root = upload_root / "_staged" / "plate.zarr"
    group_path = staged_members["plate.zarr/OME/METADATA.ome.xml"]

    def fake_scan(path: Path, timeout: int = 45):
        stdout = ""
        if path == package_root:
            stdout = _group_stdout(
                group_path,
                [
                    staged_members["plate.zarr/.zattrs"],
                    staged_members["plate.zarr/OME/METADATA.ome.xml"],
                    staged_members["plate.zarr/0/0/0"],
                ],
            )
        return subprocess.CompletedProcess(args=["omero", "import"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(core_functions, "_run_local_import_scan", fake_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert len(units) == 2

    grouped_unit = units[0]
    assert grouped_unit["relative_path"] == "plate.zarr/OME/METADATA.ome.xml"
    assert grouped_unit["dataset_relative_path"] == "plate.zarr/OME/METADATA.ome.xml"
    assert grouped_unit["staged_path"] == "_staged/plate.zarr/OME/METADATA.ome.xml"
    assert sorted(grouped_unit["cleanup_staged_paths"]) == sorted(
        [
            "_staged/plate.zarr/.zattrs",
            "_staged/plate.zarr/OME/METADATA.ome.xml",
            "_staged/plate.zarr/0/0/0",
        ]
    )

    trailing_unit = units[1]
    assert trailing_unit["relative_path"] == "plate.zarr/notes/readme.txt"
    assert trailing_unit["cleanup_staged_paths"] == ["_staged/plate.zarr/notes/readme.txt"]


def test_build_import_units_keeps_plain_folder_files_separate(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "folder/a.png",
            "folder/b.png",
        ],
    )

    plain_folder = upload_root / "_staged" / "folder"

    def fake_scan(path: Path, timeout: int = 45):
        stdout = ""
        if path == plain_folder:
            stdout = (
                _group_stdout(staged_members["folder/a.png"], [staged_members["folder/a.png"]])
                + _group_stdout(staged_members["folder/b.png"], [staged_members["folder/b.png"]])
            )
        return subprocess.CompletedProcess(args=["omero", "import"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(core_functions, "_run_local_import_scan", fake_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert units == [
        {
            "cleanup_staged_paths": ["_staged/folder/a.png"],
            "covered_indexes": [0],
            "covered_relative_paths": ["folder/a.png"],
            "dataset_relative_path": "folder/a.png",
            "index": 0,
            "relative_path": "folder/a.png",
            "staged_path": "_staged/folder/a.png",
        },
        {
            "cleanup_staged_paths": ["_staged/folder/b.png"],
            "covered_indexes": [1],
            "covered_relative_paths": ["folder/b.png"],
            "dataset_relative_path": "folder/b.png",
            "index": 1,
            "relative_path": "folder/b.png",
            "staged_path": "_staged/folder/b.png",
        },
    ]


def test_build_import_units_uses_member_path_for_dataset_when_group_header_is_directory(
    tmp_path: Path,
    monkeypatch,
):
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "folder/subfolder/a.tif",
            "folder/subfolder/b.tif",
        ],
    )

    plain_folder = upload_root / "_staged" / "folder"
    group_header = upload_root / "_staged" / "folder" / "subfolder"

    def fake_scan(path: Path, timeout: int = 45):
        stdout = ""
        if path == plain_folder:
            stdout = _group_stdout(
                group_header,
                [
                    staged_members["folder/subfolder/a.tif"],
                    staged_members["folder/subfolder/b.tif"],
                ],
            )
        return subprocess.CompletedProcess(args=["omero", "import"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(core_functions, "_run_local_import_scan", fake_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert units == [
        {
            "cleanup_staged_paths": [
                "_staged/folder/subfolder/a.tif",
                "_staged/folder/subfolder/b.tif",
            ],
            "covered_indexes": [0, 1],
            "covered_relative_paths": [
                "folder/subfolder/a.tif",
                "folder/subfolder/b.tif",
            ],
            "dataset_relative_path": "folder/subfolder/a.tif",
            "index": 0,
            "relative_path": "folder/subfolder",
            "staged_path": "_staged/folder/subfolder",
        }
    ]


def test_build_import_units_falls_back_to_per_entry_units_for_duplicate_relative_paths(tmp_path: Path):
    upload_root = tmp_path / "job-root"
    duplicate_rel_path = "folder/a.tif"
    staged_target = upload_root / "_staged" / "folder" / "a.tif"
    staged_target.parent.mkdir(parents=True, exist_ok=True)
    staged_target.write_text("x", encoding="utf-8")

    job = {
        "files": [
            {
                "upload_id": "u0",
                "relative_path": duplicate_rel_path,
                "staged_path": "_staged/folder/a.tif",
                "size": 1,
                "status": "uploaded",
                "errors": [],
            },
            {
                "upload_id": "u1",
                "relative_path": duplicate_rel_path,
                "staged_path": "_staged/folder/a.tif",
                "size": 1,
                "status": "uploaded",
                "errors": [],
            },
        ]
    }

    units = core_functions._build_import_units(job, upload_root)

    assert units == [
        {
            "cleanup_staged_paths": ["_staged/folder/a.tif"],
            "covered_indexes": [0],
            "covered_relative_paths": ["folder/a.tif"],
            "dataset_relative_path": "folder/a.tif",
            "index": 0,
            "relative_path": "folder/a.tif",
            "staged_path": "_staged/folder/a.tif",
        },
        {
            "cleanup_staged_paths": ["_staged/folder/a.tif"],
            "covered_indexes": [1],
            "covered_relative_paths": ["folder/a.tif"],
            "dataset_relative_path": "folder/a.tif",
            "index": 1,
            "relative_path": "folder/a.tif",
            "staged_path": "_staged/folder/a.tif",
        },
    ]


def test_start_upload_rejects_duplicate_normalized_relative_paths(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    upload_root.mkdir()
    jobs_root.mkdir()

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(index_view, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064))

    request = RequestFactory().post(
        "/omeroweb_upload/start/",
        data=json.dumps(
            {
                "files": [
                    {"relative_path": "folder\\\\sample.czi", "size": 1},
                    {"relative_path": "folder/sample.czi", "size": 1},
                ],
            }
        ),
        content_type="application/json",
    )

    response = index_view._start_upload(request, conn=object())
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error": errors.invalid_file_paths(["Duplicate file path: folder/sample.czi"]),
    }


def test_start_upload_rejects_ancestor_descendant_path_collisions(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    jobs_root = tmp_path / "jobs-root"
    upload_root.mkdir()
    jobs_root.mkdir()

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(index_view, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064))

    request = RequestFactory().post(
        "/omeroweb_upload/start/",
        data=json.dumps(
            {
                "files": [
                    {"relative_path": "folder", "size": 1},
                    {"relative_path": "folder/sample.czi", "size": 1},
                ],
            }
        ),
        content_type="application/json",
    )

    response = index_view._start_upload(request, conn=object())
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error": errors.invalid_file_paths(
            ["Conflicting file path hierarchy: folder <-> folder/sample.czi"]
        ),
    }


def test_dataset_name_for_import_entry_preserves_directory_package_root():
    entry = {
        "relative_path": "folder/plate.zarr",
        "dataset_relative_path": "folder/plate.zarr",
        "covered_relative_paths": [
            "folder/plate.zarr/.zattrs",
            "folder/plate.zarr/OME/METADATA.ome.xml",
            "folder/plate.zarr/0/0/0",
        ],
    }

    assert core_functions._dataset_name_for_import_entry(entry) == "folder\\plate.zarr"


def test_plan_job_dataset_targets_uses_orphan_dataset_for_top_level_file(monkeypatch):
    monkeypatch.setattr(core_functions, "_generate_orphan_dataset_name", lambda: "UploadRoot_TEST")

    orphan_dataset_name, dataset_names = core_functions._plan_job_dataset_targets(
        {"orphan_dataset_name": None},
        [{"relative_path": "top-level.ome.tiff"}],
    )

    assert orphan_dataset_name == "UploadRoot_TEST"
    assert dataset_names == ["UploadRoot_TEST"]


def test_start_upload_defers_dataset_creation_until_import(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "upload-root"
    upload_root.mkdir()
    saved_job = {}

    monkeypatch.setattr(index_view, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(index_view, "_get_jobs_root", lambda: tmp_path / "jobs-root")
    monkeypatch.setattr(index_view, "_ensure_dir", lambda path: True)
    monkeypatch.setattr(index_view, "_get_session_key", lambda conn: "session-key")
    monkeypatch.setattr(index_view, "_resolve_omero_host_port", lambda conn: ("omeroserver", 4064))
    monkeypatch.setattr(index_view, "current_username", lambda request, conn: "alice")
    monkeypatch.setattr(index_view, "reverse", lambda name, kwargs=None: f"/mock/{name}/{kwargs['job_id']}")
    monkeypatch.setattr(
        index_view,
        "_save_job",
        lambda job: saved_job.setdefault("value", json.loads(json.dumps(job))) or True,
    )
    monkeypatch.setattr(index_view, "_get_or_create_dataset", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("dataset creation should be deferred until import")
    ))

    class _FakeEventContext:
        groupId = 4

    class _FakeConn:
        def getEventContext(self):
            return _FakeEventContext()

    request = RequestFactory().post(
        "/omeroweb_upload/start/",
        data=json.dumps(
            {
                "files": [
                    {"relative_path": "folder/sample.czi", "size": 1},
                ],
            }
        ),
        content_type="application/json",
    )

    response = index_view._start_upload(request, conn=_FakeConn())
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["ok"] is True

    job = saved_job["value"]
    assert job["dataset_map"] == {}
    assert job["orphan_dataset_name"] is None


def test_ensure_job_dataset_targets_creates_only_logical_datasets(monkeypatch):
    created = []

    class _FakeServiceOpts:
        def __init__(self):
            self.groups = []

        def setOmeroGroup(self, group_id):
            self.groups.append(group_id)

    class _FakeUserConn:
        def __init__(self):
            self.SERVICE_OPTS = _FakeServiceOpts()
            self.closed = False

        def close(self):
            self.closed = True

    class _FakeServiceConn:
        def __init__(self):
            self.user_conn = _FakeUserConn()
            self.closed = False
            self.usernames = []

        def suConn(self, username):
            self.usernames.append(username)
            return self.user_conn

        def close(self):
            self.closed = True

    fake_service_conn = _FakeServiceConn()

    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda host, port, group_id=None: fake_service_conn,
    )

    def fake_get_or_create_dataset(conn, name, dataset_map, project_id=None):
        created.append((name, project_id))
        dataset_id = len(created)
        dataset_map[name] = dataset_id
        return dataset_id

    monkeypatch.setattr(core_functions, "_get_or_create_dataset", fake_get_or_create_dataset)

    job = {
        "host": "omeroserver",
        "port": 4064,
        "username": "alice",
        "group_id": 4,
        "project_id": None,
        "dataset_map": {},
        "orphan_dataset_name": None,
    }
    entries_to_import = [
        {
            "relative_path": "plate.zarr",
            "dataset_relative_path": "plate.zarr",
            "covered_relative_paths": [
                "plate.zarr/.zattrs",
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
        }
    ]

    ok, error = core_functions._ensure_job_dataset_targets(job, entries_to_import)

    assert ok is True
    assert error is None
    assert created == [("plate.zarr", None)]
    assert job["dataset_map"] == {"plate.zarr": 1}
    assert job["orphan_dataset_name"] is None
    assert fake_service_conn.usernames == ["alice"]
    assert fake_service_conn.user_conn.SERVICE_OPTS.groups == ["4"]
    assert fake_service_conn.user_conn.closed is True
    assert fake_service_conn.closed is True


def test_ensure_job_dataset_targets_uses_request_connection_when_available(monkeypatch):
    request_conn = object()
    created = []

    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda host, port, group_id=None: (_ for _ in ()).throw(AssertionError("service connection should not be used")),
    )

    def fake_get_or_create_dataset(conn, name, dataset_map, project_id=None):
        created.append((conn, name, project_id))
        dataset_map[name] = 11
        return 11

    monkeypatch.setattr(core_functions, "_get_or_create_dataset", fake_get_or_create_dataset)

    job = {
        "job_id": "a" * 32,
        "host": "omeroserver",
        "port": 4064,
        "username": "alice",
        "group_id": 4,
        "project_id": 9,
        "dataset_map": {},
        "orphan_dataset_name": None,
    }
    entries_to_import = [
        {
            "relative_path": "folder/sample.tif",
            "dataset_relative_path": "folder/sample.tif",
            "covered_relative_paths": ["folder/sample.tif"],
        }
    ]

    ok, error = core_functions._ensure_job_dataset_targets(job, entries_to_import, conn=request_conn)

    assert ok is True
    assert error is None
    assert created == [(request_conn, "folder", 9)]
    assert job["dataset_map"] == {"folder": 11}


def test_prepare_request_job_import_datasets_uses_zarr_package_root_without_import_scan(monkeypatch):
    created = []
    group_calls = []

    class _RequestConn:
        class _Opts:
            def setOmeroGroup(self, value):
                group_calls.append(value)

        SERVICE_OPTS = _Opts()

    def fake_get_or_create_dataset(conn, name, dataset_map, project_id=None):
        created.append((conn, name, project_id))
        dataset_map[name] = 21
        return 21

    monkeypatch.setattr(core_functions, "_get_or_create_dataset", fake_get_or_create_dataset)
    monkeypatch.setattr(core_functions, "_save_job", lambda job: True)

    job = {
        "job_id": "c" * 32,
        "group_id": 4,
        "project_id": 9,
        "dataset_map": {},
        "orphan_dataset_name": None,
        "files": [
            {"relative_path": "plate.zarr/.zattrs"},
            {"relative_path": "plate.zarr/OME/METADATA.ome.xml"},
            {"relative_path": "plate.zarr/0/0/0"},
        ],
    }

    prepared_job, error = core_functions._prepare_request_job_import_datasets(
        job["job_id"],
        job,
        conn=_RequestConn(),
    )

    assert prepared_job is job
    assert error is None
    assert len(created) == 1
    assert created[0][1:] == ("plate.zarr", 9)
    assert job["dataset_map"] == {"plate.zarr": 21}
    assert group_calls == ["4"]


def test_prepare_request_job_import_datasets_uses_planned_import_units_for_generic_directory_package(monkeypatch):
    created = []

    class _RequestConn:
        class _Opts:
            def setOmeroGroup(self, value):
                return None

        SERVICE_OPTS = _Opts()

    def fake_get_or_create_dataset(conn, name, dataset_map, project_id=None):
        created.append((conn, name, project_id))
        dataset_map[name] = 44
        return 44

    monkeypatch.setattr(core_functions, "_get_or_create_dataset", fake_get_or_create_dataset)
    monkeypatch.setattr(core_functions, "_save_job", lambda job: True)

    job = {
        "job_id": "d" * 32,
        "group_id": 4,
        "project_id": 9,
        "dataset_map": {},
        "orphan_dataset_name": None,
        "planned_import_units": [
            {
                "relative_path": "bundle.pkg",
                "dataset_relative_path": "bundle.pkg",
                "covered_relative_paths": [
                    "bundle.pkg/manifest.json",
                    "bundle.pkg/data/0.bin",
                ],
            }
        ],
        "files": [
            {"relative_path": "bundle.pkg/manifest.json"},
            {"relative_path": "bundle.pkg/data/0.bin"},
        ],
    }

    prepared_job, error = core_functions._prepare_request_job_import_datasets(
        job["job_id"],
        job,
        conn=_RequestConn(),
    )

    assert prepared_job is job
    assert error is None
    assert len(created) == 1
    assert created[0][1:] == ("bundle.pkg", 9)
    assert job["dataset_map"] == {"bundle.pkg": 44}


def test_ensure_job_dataset_targets_hides_impersonation_details(monkeypatch):
    class _FakeServiceConn:
        def __init__(self):
            self.closed = False

        def suConn(self, username):
            return None

        def close(self):
            self.closed = True

    fake_service_conn = _FakeServiceConn()

    monkeypatch.setattr(
        core_functions,
        "_open_service_connection",
        lambda host, port, group_id=None: fake_service_conn,
    )

    job = {
        "job_id": "b" * 32,
        "host": "omeroserver",
        "port": 4064,
        "username": "test",
        "group_id": 4,
        "project_id": None,
        "dataset_map": {},
        "orphan_dataset_name": None,
    }
    entries_to_import = [
        {
            "relative_path": "folder/sample.tif",
            "dataset_relative_path": "folder/sample.tif",
            "covered_relative_paths": ["folder/sample.tif"],
        }
    ]

    ok, error = core_functions._ensure_job_dataset_targets(job, entries_to_import)

    assert ok is False
    assert error == errors.unable_prepare_import_destination()
    assert "impersonate" not in error.lower()
    assert fake_service_conn.closed is True


def test_import_job_entry_uses_directory_package_dataset_id(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "job-root"
    package_root = upload_root / "_staged" / "plate.zarr"
    metadata_path = package_root / "OME" / "METADATA.ome.xml"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text("x", encoding="utf-8")

    captured = {}

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None):
        captured["path"] = path
        captured["dataset_id"] = dataset_id
        captured["import_name"] = import_name
        return True, "", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )

    result = core_functions._import_job_entry(
        {
            "relative_path": "plate.zarr",
            "dataset_relative_path": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
            "staged_path": "_staged/plate.zarr",
            "covered_indexes": [0, 1, 2],
            "covered_relative_paths": [
                "plate.zarr/.zattrs",
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {"plate.zarr": 77},
        None,
    )

    assert result["status"] == "imported"
    assert captured["path"] == package_root
    assert captured["dataset_id"] == 77
    assert captured["import_name"] is None


def test_entry_requires_name_normalization_only_for_grouped_internal_header():
    grouped_entry = {
        "group_header_name": "METADATA.ome.xml",
        "relative_path": "plate.zarr",
        "staged_path": "_staged/plate.zarr",
        "covered_relative_paths": [
            "plate.zarr/.zattrs",
            "plate.zarr/OME/METADATA.ome.xml",
            "plate.zarr/0/0/0",
        ],
    }
    plain_entry = {
        "relative_path": "folder/sample.czi",
        "staged_path": "_staged/folder/sample.czi",
        "covered_relative_paths": ["folder/sample.czi"],
    }
    grouped_folder_entry = {
        "relative_path": "folder/subfolder",
        "staged_path": "_staged/folder/subfolder",
        "covered_relative_paths": [
            "folder/subfolder/a.tif",
            "folder/subfolder/b.tif",
        ],
    }

    assert core_functions._entry_requires_name_normalization(grouped_entry, 7) is True
    assert core_functions._entry_requires_name_normalization(plain_entry, 7) is False
    assert core_functions._entry_requires_name_normalization(grouped_folder_entry, 7) is False
    assert core_functions._entry_requires_name_normalization(grouped_entry, None) is False


def test_extract_imported_image_ids_deduplicates_stdout():
    stdout = """
    Image:42
    Fileset:7
    Image:43
    Image:42
    """

    assert core_functions._extract_imported_image_ids(stdout) == [42, 43]


def test_apply_import_name_normalization_context_renames_single_placeholder_image(monkeypatch):
    class _FakeImage:
        def __init__(self, image_id, name):
            self._id = image_id
            self._name = name
            self.saved = False

        def getId(self):
            return self._id

        def getName(self):
            return self._name

        def setName(self, value):
            self._name = value

        def save(self):
            self.saved = True

    class _FakeConn:
        def __init__(self, images):
            self._images = images
            self.closed = False

        def getObject(self, object_type, object_id):
            if object_type == "Image":
                return self._images.get(object_id)
            return None

        def close(self):
            self.closed = True

    existing = _FakeImage(1, "existing")
    imported = _FakeImage(42, "METADATA.ome.xml")
    fake_conn = _FakeConn({1: existing, 42: imported})

    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda session_key, host, port, group_id=None: fake_conn,
    )

    renamed_ids = core_functions._apply_import_name_normalization_context(
        {
            "relative_path": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
            "staged_path": "_staged/plate.zarr",
        },
        {
            "desired_name": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
        },
        [42],
        "session-key",
        "omeroserver",
        4064,
        4,
    )

    assert renamed_ids == [42]
    assert imported.getName() == "plate.zarr"
    assert imported.saved is True
    assert fake_conn.closed is True


def test_apply_import_name_normalization_context_suffixes_multiple_placeholder_images(monkeypatch):
    class _FakeImage:
        def __init__(self, image_id, name):
            self._id = image_id
            self._name = name
            self.saved = False

        def getId(self):
            return self._id

        def getName(self):
            return self._name

        def setName(self, value):
            self._name = value

        def save(self):
            self.saved = True

    class _FakeConn:
        def __init__(self, images):
            self._images = images
            self.closed = False

        def getObject(self, object_type, object_id):
            if object_type == "Image":
                return self._images.get(object_id)
            return None

        def close(self):
            self.closed = True

    existing = _FakeImage(1, "existing")
    imported_a = _FakeImage(42, "METADATA.ome.xml")
    imported_b = _FakeImage(43, "")
    fake_conn = _FakeConn({1: existing, 42: imported_a, 43: imported_b})

    monkeypatch.setattr(
        core_functions,
        "_open_group_scoped_session_connection",
        lambda session_key, host, port, group_id=None: fake_conn,
    )

    renamed_ids = core_functions._apply_import_name_normalization_context(
        {
            "relative_path": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
            "staged_path": "_staged/plate.zarr",
        },
        {
            "desired_name": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
        },
        [42, 43],
        "session-key",
        "omeroserver",
        4064,
        4,
    )

    assert renamed_ids == [42, 43]
    assert imported_a.getName() == "plate.zarr [1]"
    assert imported_b.getName() == "plate.zarr [2]"
    assert imported_a.saved is True
    assert imported_b.saved is True
    assert fake_conn.closed is True


def test_import_job_entry_applies_name_normalization_for_grouped_package(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "job-root"
    package_root = upload_root / "_staged" / "plate.zarr"
    metadata_path = package_root / "OME" / "METADATA.ome.xml"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text("x", encoding="utf-8")

    captured = {}

    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: {
            "desired_name": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
        },
    )

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None):
        captured["path"] = path
        captured["dataset_id"] = dataset_id
        captured["import_name"] = import_name
        return True, "Image:99", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)

    result = core_functions._import_job_entry(
        {
            "relative_path": "plate.zarr",
            "dataset_relative_path": "plate.zarr",
            "group_header_name": "METADATA.ome.xml",
            "staged_path": "_staged/plate.zarr",
            "covered_indexes": [0, 1, 2],
            "covered_relative_paths": [
                "plate.zarr/.zattrs",
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {"plate.zarr": 77},
        None,
        group_id=4,
    )

    assert result["status"] == "imported"
    assert captured["path"] == package_root
    assert captured["dataset_id"] == 77
    assert captured["import_name"] == "plate.zarr"
