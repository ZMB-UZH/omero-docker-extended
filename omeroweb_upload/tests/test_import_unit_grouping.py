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
            "index": 0,
            "relative_path": "plate.zarr",
            "staged_path": "_staged/plate.zarr/OME/METADATA.ome.xml",
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


def test_import_job_entry_uses_directory_package_dataset_id(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "job-root"
    metadata_path = upload_root / "_staged" / "plate.zarr" / "OME" / "METADATA.ome.xml"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text("x", encoding="utf-8")

    captured = {}

    def fake_import_file(conn, session_key, host, port, path, dataset_id):
        captured["path"] = path
        captured["dataset_id"] = dataset_id
        return True, "", ""

    monkeypatch.setattr(core_functions, "_import_file", fake_import_file)

    result = core_functions._import_job_entry(
        {
            "relative_path": "plate.zarr",
            "dataset_relative_path": "plate.zarr",
            "staged_path": "_staged/plate.zarr/OME/METADATA.ome.xml",
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
    assert captured["path"] == metadata_path
    assert captured["dataset_id"] == 77
