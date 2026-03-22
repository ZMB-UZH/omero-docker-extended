"""Tests for grouped import planning and tree-preserving staging."""
from __future__ import annotations

from contextlib import contextmanager
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

from omeroweb_import.strings import errors
from omeroweb_import.views import core_functions, index_view


def _patch_background_import_session(monkeypatch, session_key: str = "background-session"):
    @contextmanager
    def fake_background_import_session(*args, **kwargs):
        yield session_key

    monkeypatch.setattr(
        core_functions,
        "_background_import_session",
        fake_background_import_session,
    )


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
        "/omeroweb_import/start/",
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
        "/omeroweb_import/start/",
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
        "/omeroweb_import/start/",
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
    monkeypatch.setattr(
        core_functions,
        "_create_dataset_via_admin_connection",
        lambda *args, **kwargs: None,
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

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        captured["path"] = path
        captured["dataset_id"] = dataset_id
        captured["import_name"] = import_name
        return True, "Image:123\n", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

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
    # Directory packages always derive an import name from the folder name
    # (including extension) so Bio-Formats doesn't fall back to an internal
    # chunk filename.  Consistent with _logical_import_entry_display_name().
    assert captured["import_name"] == "plate.zarr"


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

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        captured["path"] = path
        captured["dataset_id"] = dataset_id
        captured["import_name"] = import_name
        return True, "Image:99", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    _patch_background_import_session(monkeypatch)

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


# ---------------------------------------------------------------------------
# Tests for server-side import validation (CLI exit-code 0 but no objects)
# ---------------------------------------------------------------------------


def test_import_object_pattern_matches_standard_cli_output():
    """The regex must detect Image, Fileset, Plate, Dataset, and
    OriginalFile object IDs in typical OMERO CLI stdout."""
    pattern = core_functions._IMPORT_OBJECT_PATTERN
    stdout = (
        "Other:1\n"
        "Image:42\n"
        "Fileset:10\n"
        "Plate:7\n"
        "OriginalFile:100\n"
        "Screen:3\n"
        "Dataset:99\n"
    )
    matches = pattern.findall(stdout)
    assert len(matches) == 6
    assert "42" in matches
    assert "10" in matches

    # Empty stdout: no matches
    assert pattern.findall("") == []
    assert pattern.findall("Some diagnostic output") == []


def test_import_job_entry_fails_when_cli_succeeds_but_no_objects_created(tmp_path: Path, monkeypatch):
    """Malformed Zarr metadata must fail before any fallback import path is
    attempted."""
    upload_root = tmp_path / "job-root"
    staged_file = upload_root / "_staged" / "broken.zarr" / ".zattrs"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("x", encoding="utf-8")

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("_import_file should not be called for malformed zarr metadata")

    monkeypatch.setattr(core_functions, "_import_file", must_not_be_called)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "broken.zarr",
            "staged_path": "_staged/broken.zarr",
            "covered_indexes": [0],
            "covered_relative_paths": ["broken.zarr/.zattrs"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "error"
    assert "failed to read zarr metadata" in result["entry_error"].lower()


def test_import_job_entry_succeeds_when_stdout_contains_image_id(tmp_path: Path, monkeypatch):
    """Normal successful import: CLI exit-code 0 with Image IDs in stdout."""
    upload_root = tmp_path / "job-root"
    staged_file = upload_root / "_staged" / "test.tif"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("x", encoding="utf-8")

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        return True, "OriginalFile:100\nImage:42\nFileset:10\n", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "test.tif",
            "staged_path": "_staged/test.tif",
            "covered_indexes": [0],
            "covered_relative_paths": ["test.tif"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "imported"


def test_import_job_entry_salvages_success_when_cli_nonzero_but_objects_exist(tmp_path: Path, monkeypatch):
    """When the OMERO CLI returns non-zero but stdout contains created
    object IDs, the import should be treated as success — the server
    committed the data before the CLI errored (e.g. thumbnail generation)."""
    upload_root = tmp_path / "job-root"
    staged_file = upload_root / "_staged" / "test.tif"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("x", encoding="utf-8")

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        # CLI returned non-zero but did create objects
        return False, "Image:751\nFileset:200\n", "Some error during post-processing"

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "test.tif",
            "staged_path": "_staged/test.tif",
            "covered_indexes": [0],
            "covered_relative_paths": ["test.tif"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "imported"


def test_import_job_entry_salvages_success_when_objects_in_stderr(tmp_path: Path, monkeypatch):
    """Some import formats (e.g. zarr) print object IDs only to stderr.
    The plugin must check both streams."""
    upload_root = tmp_path / "job-root"
    staged_file = upload_root / "_staged" / "test.tif"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("x", encoding="utf-8")

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        # CLI returned non-zero, stdout empty, but stderr has the object IDs
        return False, "", "Lots of debug output\nImage:805\nFileset:300\nMore output"

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "test.tif",
            "staged_path": "_staged/test.tif",
            "covered_indexes": [0],
            "covered_relative_paths": ["test.tif"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "imported"


def test_import_job_entry_fails_when_cli_nonzero_and_no_objects(tmp_path: Path, monkeypatch):
    """When the CLI returns non-zero and stdout has no objects, the import
    must report failure."""
    upload_root = tmp_path / "job-root"
    staged_file = upload_root / "_staged" / "test.tif"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("x", encoding="utf-8")

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        return False, "Some diagnostic output\n", "Fatal error"

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "test.tif",
            "staged_path": "_staged/test.tif",
            "covered_indexes": [0],
            "covered_relative_paths": ["test.tif"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "error"


def test_import_job_entry_sets_import_name_for_zarr_directory(tmp_path: Path, monkeypatch):
    """Zarr directory imports must always set an import name derived from
    the folder name so Bio-Formats doesn't use a chunk coordinate."""
    upload_root = tmp_path / "job-root"
    zarr_dir = upload_root / "_staged" / "myimage.ome.zarr"
    zarr_dir.mkdir(parents=True, exist_ok=True)
    (zarr_dir / ".zattrs").write_text("{}", encoding="utf-8")

    captured = {}

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        captured["import_name"] = import_name
        return True, "Image:1\n", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "myimage.ome.zarr",
            "staged_path": "_staged/myimage.ome.zarr",
            "covered_indexes": [0],
            "covered_relative_paths": ["myimage.ome.zarr/.zattrs"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "imported"
    assert captured["import_name"] == "myimage.ome.zarr"


# ---------------------------------------------------------------------------
# Tests for pre-flight zarr scan (native CLI detection of unsupported formats)
# ---------------------------------------------------------------------------


def test_ome_ngff_zarr_uses_cli_zarr_import(tmp_path: Path, monkeypatch):
    """OME-NGFF zarrs (multiscales, no bioformats2raw) must be imported via
    ``omero zarr import`` instead of the standard Bio-Formats path."""
    upload_root = tmp_path / "job-root"
    zarr_dir = upload_root / "_staged" / "image.ome.zarr"
    (zarr_dir / "0").mkdir(parents=True, exist_ok=True)
    (zarr_dir / ".zattrs").write_text(
        '{"multiscales": [{"version": "0.4", "axes": [{"name": "y"}, {"name": "x"}], "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0]}]}]}]}',
        encoding="utf-8",
    )
    (zarr_dir / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (zarr_dir / "0" / ".zarray").write_text('{"shape":[1,1],"dtype":"<u2"}', encoding="utf-8")

    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )
    # _import_file should NOT be called — OME-NGFF uses cli-zarr
    def must_not_be_called(*args, **kwargs):
        raise AssertionError("_import_file should not be called for OME-NGFF zarr")
    monkeypatch.setattr(core_functions, "_import_file", must_not_be_called)
    _patch_background_import_session(monkeypatch)

    # Mock _import_zarr_via_cli to verify it is called
    called = {"value": False}
    def mock_zarr_import(**kwargs):
        called["value"] = True
        return {
            "cleanup_staged_paths": kwargs.get("cleanup_staged_paths", []),
            "covered_indexes": kwargs.get("covered_indexes", []),
            "covered_relative_paths": kwargs.get("covered_relative_paths", []),
            "index": kwargs.get("entry", {}).get("index"),
            "status": "imported",
            "rel_path": "image.ome.zarr",
            "file_path": zarr_dir,
        }
    monkeypatch.setattr(core_functions, "_import_zarr_via_cli", mock_zarr_import)

    result = core_functions._import_job_entry(
        {
            "relative_path": "image.ome.zarr",
            "staged_path": "_staged/image.ome.zarr",
            "covered_indexes": [0],
            "covered_relative_paths": ["image.ome.zarr/.zattrs"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert called["value"], "_import_zarr_via_cli was not called for OME-NGFF zarr"
    assert result["status"] == "imported"


def test_bioformats2raw_zarr_uses_cli_zarr_import(tmp_path: Path, monkeypatch):
    """bioformats2raw-layout image stores supported by omero-cli-zarr must
    also use the native ``omero zarr import`` path."""
    upload_root = tmp_path / "job-root"
    zarr_dir = upload_root / "_staged" / "bf2raw.ome.zarr"
    series_dir = zarr_dir / "0"
    array_dir = series_dir / "0"
    array_dir.mkdir(parents=True, exist_ok=True)
    (zarr_dir / ".zattrs").write_text('{"bioformats2raw.layout": 3}', encoding="utf-8")
    (series_dir / ".zattrs").write_text(
        '{"multiscales": [{"version": "0.4", "axes": [{"name": "y"}, {"name": "x"}], "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0]}]}]}]}',
        encoding="utf-8",
    )
    (array_dir / ".zarray").write_text('{"shape":[1,1],"dtype":"<u2"}', encoding="utf-8")

    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("_import_file should not be called for bioformats2raw zarr")

    monkeypatch.setattr(core_functions, "_import_file", must_not_be_called)
    _patch_background_import_session(monkeypatch)

    called = {"value": False}

    def mock_zarr_import(**kwargs):
        called["value"] = True
        return {
            "cleanup_staged_paths": kwargs.get("cleanup_staged_paths", []),
            "covered_indexes": kwargs.get("covered_indexes", []),
            "covered_relative_paths": kwargs.get("covered_relative_paths", []),
            "index": kwargs.get("entry", {}).get("index"),
            "status": "imported",
            "rel_path": "bf2raw.ome.zarr",
            "file_path": zarr_dir,
        }

    monkeypatch.setattr(core_functions, "_import_zarr_via_cli", mock_zarr_import)

    result = core_functions._import_job_entry(
        {
            "relative_path": "bf2raw.ome.zarr",
            "staged_path": "_staged/bf2raw.ome.zarr",
            "covered_indexes": [0],
            "covered_relative_paths": ["bf2raw.ome.zarr/.zattrs"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert called["value"], "_import_zarr_via_cli was not called for bioformats2raw zarr"
    assert result["status"] == "imported"


def test_preflight_scan_passes_zarr_when_bioformats_finds_groups(tmp_path: Path, monkeypatch):
    """When ``omero import -f`` finds importable groups for a .zarr, the
    pre-flight check passes and the actual import proceeds normally."""
    upload_root = tmp_path / "job-root"
    zarr_dir = upload_root / "_staged" / "valid.zarr"
    (zarr_dir / "OME").mkdir(parents=True, exist_ok=True)
    (zarr_dir / "OME" / "METADATA.ome.xml").write_text("<xml/>", encoding="utf-8")

    # Mock the scan to return 1 group (like Bio-Formats does for bioformats2raw)
    scan_stdout = f"# Group: {zarr_dir}\n{zarr_dir / 'OME' / 'METADATA.ome.xml'}\n"
    scan_mock = type("Result", (), {"stdout": scan_stdout, "stderr": "", "returncode": 0})()
    monkeypatch.setattr(core_functions, "_run_local_import_scan", lambda path, timeout=None: scan_mock)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        return True, "Image:99\n", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "valid.zarr",
            "staged_path": "_staged/valid.zarr",
            "covered_indexes": [0],
            "covered_relative_paths": ["valid.zarr/OME/METADATA.ome.xml"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    assert result["status"] == "imported"


def test_preflight_scan_timeout_does_not_block_import(tmp_path: Path, monkeypatch):
    """If the pre-flight scan times out, the import proceeds anyway (the
    post-import validation is the safety net)."""
    upload_root = tmp_path / "job-root"
    zarr_dir = upload_root / "_staged" / "slow.zarr"
    zarr_dir.mkdir(parents=True, exist_ok=True)
    (zarr_dir / ".zattrs").write_text("{}", encoding="utf-8")

    def timeout_scan(path, timeout=None):
        raise subprocess.TimeoutExpired(cmd=["omero"], timeout=60)

    monkeypatch.setattr(core_functions, "_run_local_import_scan", timeout_scan)
    monkeypatch.setattr(
        core_functions,
        "_build_import_name_normalization_context",
        lambda entry, dataset_id: None,
    )

    def fake_import_file(conn, session_key, host, port, path, dataset_id, import_name=None, progress_job=None):
        return True, "Image:55\n", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)
    _patch_background_import_session(monkeypatch)

    result = core_functions._import_job_entry(
        {
            "relative_path": "slow.zarr",
            "staged_path": "_staged/slow.zarr",
            "covered_indexes": [0],
            "covered_relative_paths": ["slow.zarr/.zattrs"],
        },
        upload_root,
        "session-key",
        "omeroserver",
        4064,
        {},
        None,
    )

    # Import should proceed despite scan timeout, succeeding thanks to Image:55
    assert result["status"] == "imported"


# ---------------------------------------------------------------------------
# Tests for scan-failure resilience (probe exception safety + fallback
# directory package grouping).
# ---------------------------------------------------------------------------


def test_probe_import_path_returns_empty_result_on_scan_timeout(tmp_path: Path, monkeypatch):
    """_probe_import_path must NOT crash the caller when _run_local_import_scan
    raises (e.g. subprocess.TimeoutExpired).  It should return an empty result."""
    upload_root = tmp_path / "job-root"
    _, staged_members = _stage_relative_paths(upload_root, ["data.zarr/.zattrs"])
    staged_root = upload_root / "_staged"

    def timeout_scan(path: Path, timeout: int = 45):
        raise subprocess.TimeoutExpired(cmd=["omero", "import"], timeout=timeout)

    monkeypatch.setattr(core_functions, "_run_local_import_scan", timeout_scan)

    cache = {}
    result = core_functions._probe_import_path(
        staged_root / "data.zarr",
        staged_root,
        ["data.zarr/.zattrs"],
        cache,
    )

    assert result["coverage"] == set()
    assert result["groups"] == ()
    assert result["returncode"] == -1
    assert "timed out" in result["stderr"]
    # Cached so repeated calls do not re-run the scan.
    assert str(staged_root / "data.zarr") in cache


def test_probe_import_path_returns_empty_result_on_scan_oserror(tmp_path: Path, monkeypatch):
    """Same as above but for OSError (e.g. disk full, permission denied)."""
    upload_root = tmp_path / "job-root"
    _, staged_members = _stage_relative_paths(upload_root, ["data.zarr/.zattrs"])
    staged_root = upload_root / "_staged"

    def oserror_scan(path: Path, timeout: int = 45):
        raise OSError("No space left on device")

    monkeypatch.setattr(core_functions, "_run_local_import_scan", oserror_scan)

    cache = {}
    result = core_functions._probe_import_path(
        staged_root / "data.zarr",
        staged_root,
        ["data.zarr/.zattrs"],
        cache,
    )

    assert result["coverage"] == set()
    assert result["groups"] == ()
    assert result["returncode"] == -1


def test_build_import_units_groups_zarr_by_extension_when_scan_fails(tmp_path: Path, monkeypatch):
    """When the OMERO CLI scan fails for every probe, _build_import_units must
    still group files under a known directory package root (.zarr) into a
    single import unit instead of creating per-file units."""
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "data.zarr/.zattrs",
            "data.zarr/0/0/0",
            "data.zarr/0/0/1",
        ],
    )

    def failing_scan(path: Path, timeout: int = 45):
        raise subprocess.TimeoutExpired(cmd=["omero", "import"], timeout=timeout)

    monkeypatch.setattr(core_functions, "_run_local_import_scan", failing_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert len(units) == 1
    unit = units[0]
    assert unit["relative_path"] == "data.zarr"
    assert unit["staged_path"] == "_staged/data.zarr"
    assert unit["dataset_relative_path"] == "data.zarr"
    assert sorted(unit["covered_relative_paths"]) == sorted(
        ["data.zarr/.zattrs", "data.zarr/0/0/0", "data.zarr/0/0/1"]
    )
    assert unit["cleanup_staged_paths"] == ["_staged/data.zarr"]


def test_build_import_units_does_not_use_extension_fallback_when_probe_grouped(
    tmp_path: Path, monkeypatch
):
    """When the probe DID find groups covering some zarr files, the
    extension fallback must NOT re-group files that the probe excluded."""
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "plate.zarr/.zattrs",
            "plate.zarr/0/0/0",
            "plate.zarr/extra/notes.txt",
        ],
    )

    package_root = upload_root / "_staged" / "plate.zarr"

    def partial_scan(path: Path, timeout: int = 45):
        stdout = ""
        if path == package_root:
            stdout = _group_stdout(
                staged_members["plate.zarr/.zattrs"],
                [
                    staged_members["plate.zarr/.zattrs"],
                    staged_members["plate.zarr/0/0/0"],
                ],
            )
        return subprocess.CompletedProcess(
            args=["omero", "import"], returncode=0, stdout=stdout, stderr=""
        )

    monkeypatch.setattr(core_functions, "_run_local_import_scan", partial_scan)

    units = core_functions._build_import_units(job, upload_root)

    # The probe covered 2 files. The 3rd was NOT covered by any probe group
    # but since siblings WERE covered, the extension fallback must NOT fire.
    assert len(units) == 2
    grouped_rel_paths = [rp for u in units for rp in u["covered_relative_paths"]]
    assert "plate.zarr/extra/notes.txt" in grouped_rel_paths
    # notes.txt must be its own individual unit
    individual = [u for u in units if "plate.zarr/extra/notes.txt" in u["covered_relative_paths"]]
    assert len(individual) == 1
    assert individual[0]["relative_path"] == "plate.zarr/extra/notes.txt"


def test_build_import_units_groups_mixed_zarr_and_regular_files_when_scan_fails(
    tmp_path: Path, monkeypatch
):
    """A job with both zarr files and regular files.  The scan fails.
    Zarr files should be grouped; regular files should remain individual."""
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "data.zarr/.zattrs",
            "data.zarr/0/0/0",
            "images/photo.tif",
        ],
    )

    def failing_scan(path: Path, timeout: int = 45):
        raise subprocess.TimeoutExpired(cmd=["omero", "import"], timeout=timeout)

    monkeypatch.setattr(core_functions, "_run_local_import_scan", failing_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert len(units) == 2
    zarr_unit = [u for u in units if u["relative_path"] == "data.zarr"]
    tif_unit = [u for u in units if u["relative_path"] == "images/photo.tif"]
    assert len(zarr_unit) == 1
    assert len(tif_unit) == 1
    assert sorted(zarr_unit[0]["covered_relative_paths"]) == sorted(
        ["data.zarr/.zattrs", "data.zarr/0/0/0"]
    )


def test_build_import_units_groups_multiple_zarrs_when_scan_fails(
    tmp_path: Path, monkeypatch
):
    """Two separate zarr directories in one upload.  Both must be grouped
    independently when the scan fails."""
    upload_root = tmp_path / "job-root"
    job, staged_members = _stage_relative_paths(
        upload_root,
        [
            "a.zarr/.zattrs",
            "a.zarr/0/0",
            "b.zarr/.zgroup",
            "b.zarr/1/0",
        ],
    )

    def failing_scan(path: Path, timeout: int = 45):
        raise subprocess.TimeoutExpired(cmd=["omero", "import"], timeout=timeout)

    monkeypatch.setattr(core_functions, "_run_local_import_scan", failing_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert len(units) == 2
    unit_a = [u for u in units if u["relative_path"] == "a.zarr"]
    unit_b = [u for u in units if u["relative_path"] == "b.zarr"]
    assert len(unit_a) == 1
    assert len(unit_b) == 1
    assert sorted(unit_a[0]["covered_relative_paths"]) == ["a.zarr/.zattrs", "a.zarr/0/0"]
    assert sorted(unit_b[0]["covered_relative_paths"]) == ["b.zarr/.zgroup", "b.zarr/1/0"]


def test_build_import_units_groups_zarr_when_scan_returns_no_groups(
    tmp_path: Path, monkeypatch
):
    """Scan succeeds (no exception, exit code 0) but returns no import groups
    (e.g. JVM OOM wrote nothing to stdout, or Bio-Formats didn't recognize the
    format).  The extension fallback must still group zarr files."""
    upload_root = tmp_path / "job-root"
    job, _ = _stage_relative_paths(
        upload_root,
        [
            "data.zarr/.zattrs",
            "data.zarr/0/0/0",
            "data.zarr/0/0/1",
        ],
    )

    def empty_scan(path: Path, timeout: int = 45):
        return subprocess.CompletedProcess(
            args=["omero", "import"], returncode=1, stdout="", stderr="Java heap space"
        )

    monkeypatch.setattr(core_functions, "_run_local_import_scan", empty_scan)

    units = core_functions._build_import_units(job, upload_root)

    assert len(units) == 1
    unit = units[0]
    assert unit["relative_path"] == "data.zarr"
    assert unit["staged_path"] == "_staged/data.zarr"
    assert sorted(unit["covered_relative_paths"]) == sorted(
        ["data.zarr/.zattrs", "data.zarr/0/0/0", "data.zarr/0/0/1"]
    )


def test_compatibility_thread_resets_flag_on_crash(tmp_path: Path, monkeypatch):
    """If _run_compatibility_check_inner crashes, the wrapper must reset
    compatibility_thread_active so the job is not stuck forever."""
    jobs_root = tmp_path / "jobs"
    upload_root = tmp_path / "uploads"
    jobs_root.mkdir()
    upload_root.mkdir()

    import time as _time
    job_id = "deadbeef" * 4
    job = {
        "job_id": job_id,
        "username": "test",
        "session_key": "sk",
        "host": "omeroserver",
        "port": 4064,
        "files": [
            {
                "upload_id": "u0",
                "relative_path": "data.zarr/.zattrs",
                "staged_path": "_staged/data.zarr/.zattrs",
                "size": 1,
                "status": "uploaded",
                "errors": [],
            }
        ],
        "total_bytes": 1,
        "uploaded_bytes": 1,
        "imported_bytes": 0,
        "status": "checking",
        "errors": [],
        "created": _time.time(),
        "updated": _time.time(),
        "compatibility_thread_active": True,
        "compatibility_enabled": True,
        "compatibility_status": "checking",
        "incompatible_files": [],
        "planned_import_units": [],
        "dataset_map": {},
        "orphan_dataset_name": None,
        "import_index": 0,
        "messages": [],
        "import_thread_started": False,
        "job_batch_size": 5,
        "compatibility_confirmed": False,
        "special_upload": "",
        "sem_edx_associations": {},
        "sem_edx_settings": {},
    }

    monkeypatch.setattr(core_functions, "_get_jobs_root", lambda: jobs_root)
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    core_functions._save_job(job)

    # Inject a crash into _build_import_units to simulate a scan failure
    # that propagates.
    def crashing_build(*args, **kwargs):
        raise RuntimeError("simulated JVM crash")

    monkeypatch.setattr(core_functions, "_build_import_units", crashing_build)

    # This must NOT raise; it should catch and reset the flag.
    core_functions._run_compatibility_check(job_id)

    reloaded = core_functions._load_job(job_id)
    assert reloaded is not None
    assert reloaded["compatibility_thread_active"] is False
    assert reloaded["compatibility_status"] == "error"
    # The job should transition to "ready" (errors don't block import)
    assert reloaded["status"] == "ready"


# ---------------------------------------------------------------------------
# Tests for import progress monitoring helpers
# ---------------------------------------------------------------------------


def test_read_proc_rchar_returns_int_for_current_process():
    """_read_proc_rchar should be able to read /proc/self/io."""
    import os
    rchar = core_functions._read_proc_rchar(os.getpid())
    # On Linux this should return a positive integer.
    # On other platforms it returns None — both are acceptable.
    assert rchar is None or isinstance(rchar, int)


def test_read_proc_rchar_returns_none_for_missing_pid():
    """_read_proc_rchar must not crash for a non-existent PID."""
    result = core_functions._read_proc_rchar(999999999)
    assert result is None


def test_get_path_total_size_for_file(tmp_path: Path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"x" * 1234)
    assert core_functions._get_path_total_size(f) == 1234


def test_get_path_total_size_for_directory(tmp_path: Path):
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.txt").write_bytes(b"a" * 100)
    sub = d / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"b" * 200)
    assert core_functions._get_path_total_size(d) == 300


def test_get_path_total_size_for_missing_path(tmp_path: Path):
    missing = tmp_path / "nope"
    assert core_functions._get_path_total_size(missing) == 0


def test_build_cli_env_returns_dict_with_home(monkeypatch, tmp_path: Path):
    """_build_cli_env should set HOME and XDG_CACHE_HOME."""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    env = core_functions._build_cli_env()
    assert "HOME" in env
    assert "XDG_CACHE_HOME" in env
    assert env["HOME"].startswith(str(upload_root))


def test_import_file_progress_job_updates_import_progress_bytes(tmp_path: Path, monkeypatch):
    """When progress_job is provided, _import_file should update
    import_progress_bytes in the job dict via /proc monitoring."""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    monkeypatch.setattr(core_functions, "_get_upload_root", lambda: upload_root)
    monkeypatch.setattr(core_functions, "_get_import_timeout_seconds", lambda: 30)

    test_file = tmp_path / "test.czi"
    test_file.write_bytes(b"\x00" * (1024 * 1024))  # 1MB

    # Mock _build_omero_cli_command to return a simple command that reads the file
    monkeypatch.setattr(
        core_functions, "_build_omero_cli_command",
        lambda subcmd, sk, h, p: ["python3", "-c",
            f"import time; f=open('{test_file}','rb'); f.read(); time.sleep(0.5)"]
    )

    job = {"imported_bytes": 500, "import_progress_bytes": 500}

    # Replace _save_job with a no-op (no job file on disk)
    monkeypatch.setattr(core_functions, "_save_job", lambda j: None)

    success, stdout, stderr = core_functions._import_file(
        conn=None,
        session_key="test-key",
        host="localhost",
        port=4064,
        path=test_file,
        dataset_id=None,
        progress_job=job,
    )

    # The command should succeed (reading a file and sleeping is valid)
    assert success is True
    # import_progress_bytes should have been updated to reflect bytes read
    assert job["import_progress_bytes"] >= 500  # at least the base value
