from __future__ import annotations

import importlib.util
import logging
import sys
import tempfile
import types
from pathlib import Path
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from omeroweb_import import apps, urls
from omeroweb_import.services import compat, ome_zarr_support as support
from omeroweb_import.services.omero import dataset_service
from omeroweb_import.utils import omero_helpers
from omeroweb_import.views import core_functions, help_view, utils as view_utils
from omero_plugin_common import omero_helpers as common_omero_helpers


REPO_ROOT = PurePosixPath(__file__).parents[2]
TEST_JOBS_ROOT = str(Path(tempfile.gettempdir()) / "import-jobs")
TEST_OMERO_CLI = "omero-cli"


class _FakeValue:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _FakeDatasetI:
    def __init__(self, dataset_id=None, _loaded=True):
        self._id = dataset_id
        self.name = None

    def setName(self, value):
        self.name = value

    def getId(self):
        return _FakeValue(self._id)


class _FakeProjectI:
    def __init__(self, project_id, _loaded):
        self.project_id = project_id


class _FakeProjectDatasetLinkI:
    def __init__(self):
        self.parent = None
        self.child = None

    def setParent(self, parent):
        self.parent = parent

    def setChild(self, child):
        self.child = child


class _FakeDatasetChild:
    def __init__(self, dataset_id, name):
        self.id = dataset_id
        self._name = name

    def getName(self):
        return self._name


class _FakeProject:
    def __init__(
        self,
        project_id,
        name,
        *,
        owner_id=None,
        can_write=False,
        owner_name=None,
        children=None,
    ):
        self.id = project_id
        self._name = name
        self.owner_id = owner_id
        self.can_write = can_write
        self.owner_name = owner_name
        self._children = list(children or [])

    def getName(self):
        return self._name

    def listChildren(self):
        return list(self._children)


class _FakeExistingDataset:
    def __init__(self, dataset_id, *, expose_id=True):
        self.id = dataset_id if expose_id else None
        self._dataset_id = dataset_id

    def getId(self):
        return _FakeValue(self._dataset_id)


class _FakeUpdateService:
    def __init__(self):
        self.saved_links = []
        self.saved_datasets = []

    def saveAndReturnObject(self, obj):
        if isinstance(obj, _FakeDatasetI):
            if obj._id is None:
                obj._id = 77
            self.saved_datasets.append(obj)
            return obj
        self.saved_links.append(obj)
        return obj


class _FakeSecrets:
    def __init__(self, values):
        self._values = iter(values)

    def choice(self, _alphabet):
        return next(self._values)


class _FakeServiceOpts:
    def __init__(self, *, group="5", fail_get=False):
        self.group = group
        self.fail_get = fail_get
        self.set_calls = []

    def getOmeroGroup(self):
        if self.fail_get:
            raise RuntimeError("cannot read group")
        return self.group

    def setOmeroGroup(self, value):
        self.set_calls.append(value)


@pytest.fixture()
def dataset_module(monkeypatch):
    monkeypatch.setattr(core_functions, "PurePosixPath", PurePosixPath, raising=False)
    monkeypatch.setattr(core_functions, "secrets", _FakeSecrets("ABCD"), raising=False)
    monkeypatch.setattr(
        core_functions, "ORPHAN_SUFFIX_ALPHANUM", "ABCDEF", raising=False
    )
    monkeypatch.setattr(core_functions, "ORPHAN_SUFFIX_LENGTH", 4, raising=False)
    monkeypatch.setattr(
        core_functions, "ORPHAN_DATASET_PREFIX", "UploadRoot", raising=False
    )
    monkeypatch.setattr(core_functions, "OMERO_CLI", TEST_OMERO_CLI, raising=False)
    monkeypatch.setattr(
        core_functions,
        "settings",
        SimpleNamespace(OMERO_HOST="fallback-host", OMERO_PORT="4064"),
        raising=False,
    )
    monkeypatch.setattr(
        core_functions, "_get_id", lambda obj: getattr(obj, "id", None), raising=False
    )
    monkeypatch.setattr(core_functions, "_get_text", lambda value: value, raising=False)
    monkeypatch.setattr(
        core_functions,
        "_is_owned_by_user",
        lambda proj, user_id: getattr(proj, "owner_id", None) == user_id,
        raising=False,
    )
    monkeypatch.setattr(
        core_functions,
        "_has_read_write_permissions",
        lambda proj: getattr(proj, "can_write", False),
        raising=False,
    )
    monkeypatch.setattr(
        core_functions,
        "_get_owner_username",
        lambda proj: getattr(proj, "owner_name", None),
        raising=False,
    )
    monkeypatch.setattr(core_functions, "DatasetI", _FakeDatasetI, raising=False)
    monkeypatch.setattr(
        core_functions,
        "ProjectDatasetLinkI",
        _FakeProjectDatasetLinkI,
        raising=False,
    )
    monkeypatch.setattr(core_functions, "ProjectI", _FakeProjectI, raising=False)
    monkeypatch.setattr(core_functions, "rstring", lambda value: value, raising=False)
    return dataset_service


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")


def test_import_module_contracts_and_reexports(monkeypatch):
    calls = []
    monkeypatch.setattr(
        apps, "configure_omero_gateway_logging", lambda: calls.append("configured")
    )
    apps.ImportPluginConfig("omeroweb_import", apps).ready()
    assert calls == ["configured"]

    route_map = {pattern.name: str(pattern.pattern) for pattern in urls.urlpatterns}
    assert route_map["omeroweb_import_help"] == "help/"
    assert route_map["omeroweb_import_files"] == "upload/<str:job_id>/"
    assert route_map["omeroweb_import_import_step"] == "import/<str:job_id>/"
    assert route_map["omeroweb_import_projects"] == "projects/"

    captured = {}
    monkeypatch.setattr(compat, "get_jobs_root", lambda: TEST_JOBS_ROOT)
    monkeypatch.setattr(
        compat,
        "_get_job_path_internal",
        lambda job_id, jobs_root: captured.setdefault("path", (job_id, jobs_root)),
    )
    monkeypatch.setattr(
        compat,
        "_load_job_internal",
        lambda job_id, jobs_root: captured.setdefault("load", (job_id, jobs_root)),
    )
    monkeypatch.setattr(
        compat,
        "_save_job_internal",
        lambda job_dict, jobs_root, retries, timeout: captured.setdefault(
            "save", (job_dict, jobs_root, retries, timeout)
        ),
    )
    monkeypatch.setattr(
        compat,
        "_robust_update_job_internal",
        lambda job_id, update_fn, jobs_root, retries, timeout: captured.setdefault(
            "update",
            (job_id, update_fn("value"), jobs_root, retries, timeout),
        ),
    )
    assert compat._job_path("job-1") == ("job-1", TEST_JOBS_ROOT)
    assert compat._load_job("job-2") == ("job-2", TEST_JOBS_ROOT)
    assert compat._save_job({"job_id": "job-3"}, retries=5, timeout=2.5) == (
        {"job_id": "job-3"},
        TEST_JOBS_ROOT,
        5,
        2.5,
    )
    assert compat._robust_update_job(
        "job-4",
        lambda value: f"updated-{value}",
        retries=6,
        timeout=3.5,
    ) == ("job-4", "updated-value", TEST_JOBS_ROOT, 6, 3.5)
    assert compat._iter_accessible_projects is core_functions._iter_accessible_projects
    assert (
        compat._build_sem_edx_associations_from_entries
        is core_functions._build_sem_edx_associations_from_entries
    )

    assert omero_helpers.get_text is common_omero_helpers.get_text
    assert omero_helpers.get_id is common_omero_helpers.get_id
    assert omero_helpers.get_owner_id is common_omero_helpers.get_owner_id
    assert omero_helpers.is_owned_by_user is common_omero_helpers.is_owned_by_user
    assert omero_helpers._current_user_id is common_omero_helpers._current_user_id
    assert omero_helpers._get_owner_username is common_omero_helpers._get_owner_username
    assert (
        omero_helpers._has_read_write_permissions
        is common_omero_helpers._has_read_write_permissions
    )


def test_dataset_service_wrapper_uses_canonical_core_functions(
    dataset_module, monkeypatch
):
    monkeypatch.setattr(
        core_functions,
        "_iter_accessible_projects",
        lambda conn: iter(
            [
                _FakeProject(11, "Owned", owner_id=7),
                _FakeProject(12, "Shared", can_write=True, owner_name="bob"),
                _FakeProject(None, "MissingId", owner_id=7),
            ]
        ),
    )

    payload = dataset_module._collect_project_payload(conn=object(), user_id=7)
    assert payload == {
        "owned": [{"id": "11", "name": "Owned"}],
        "collab": [{"id": "12", "name": "Shared", "owner": "bob"}],
    }

    monkeypatch.setattr(core_functions, "secrets", _FakeSecrets("WXYZ"), raising=False)
    assert (
        dataset_module._dataset_name_for_path("image.ome.tif", "UploadRoot_TEST")
        == "UploadRoot_TEST"
    )
    assert (
        dataset_module._dataset_name_for_path("dataset/subdir/image.ome.tif")
        == "dataset\\subdir"
    )
    assert dataset_module._generate_orphan_dataset_name() == "UploadRoot_WXYZ"

    project = _FakeProject(
        3,
        "Project",
        children=[_FakeDatasetChild(41, "Other"), _FakeDatasetChild(42, "Target")],
    )
    update_service = _FakeUpdateService()

    def _get_objects(model, *args, **kwargs):
        if model == "Project":
            return iter([project])
        if model == "Dataset":
            return iter([_FakeExistingDataset(55)])
        return iter([])

    conn = SimpleNamespace(
        getObject=lambda model, project_id: (
            project if (model, project_id) == ("Project", 3) else None
        ),
        getUpdateService=lambda: update_service,
        getObjects=_get_objects,
        SERVICE_OPTS=_FakeServiceOpts(),
    )

    assert dataset_module._find_project_dataset(conn, 3, "Target") == 42
    assert dataset_module._link_dataset_to_project(conn, 21, 3) is True
    assert update_service.saved_links[0].parent.project_id == 3
    assert update_service.saved_links[0].child._id == 21
    assert dataset_module._resolve_omero_host_port(
        SimpleNamespace(host=None, port=None)
    ) == (
        "fallback-host",
        4064,
    )
    assert (
        dataset_module._get_session_key(SimpleNamespace(_sessionUuid="session-key"))
        == "session-key"
    )
    dataset_map = {}
    assert dataset_module._get_or_create_dataset(conn, "Existing", dataset_map) == 55
    assert dataset_map["Existing"] == 55
    assert dataset_module._build_omero_cli_command(
        ["import", "file.tif"],
        "session-key",
        "omeroserver",
        4064,
    ) == [
        TEST_OMERO_CLI,
        "-k",
        "session-key",
        "-s",
        "omeroserver",
        "-p",
        "4064",
        "import",
        "file.tif",
    ]
    assert list(dataset_module._iter_accessible_projects(conn)) == [project]
    assert (
        dataset_service._get_or_create_dataset is core_functions._get_or_create_dataset
    )


def test_dataset_service_iter_accessible_projects_uses_fallback_paths(dataset_module):
    service_opts = _FakeServiceOpts()
    conn = SimpleNamespace(
        SERVICE_OPTS=service_opts,
        getObjects=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
        listProjects=lambda: ["project-a"],
    )

    assert list(dataset_module._iter_accessible_projects(conn)) == ["project-a"]
    assert service_opts.set_calls == ["-1", "5"]


def test_core_function_helpers_cover_native_zarr_plan_and_shared_transfer_cleanup(
    tmp_path,
    monkeypatch,
    caplog,
):
    plan = core_functions._NativeZarrImportPlan(
        kind=support.OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW,
        recognized_zarr=True,
        validation_error="unsupported plate layout",
        verify_lsid_prefix=True,
        compatibility_details="detected by ome-zarr",
    )
    payload = core_functions._serialize_native_zarr_plan(plan)
    assert payload == {
        "kind": support.OME_ZARR_IMPORT_KIND_BIOFORMATS2RAW,
        "recognized_zarr": True,
        "validation_error": "unsupported plate layout",
        "verify_lsid_prefix": True,
        "compatibility_details": "detected by ome-zarr",
    }
    assert core_functions._deserialize_native_zarr_plan(payload) == plan
    assert (
        core_functions._serialize_native_zarr_plan(
            core_functions._NativeZarrImportPlan()
        )
        is None
    )
    assert (
        core_functions._deserialize_native_zarr_plan(["not", "a", "dict"])
        == core_functions._NativeZarrImportPlan()
    )

    transfer_root = tmp_path / "managed-zarr-transfer"
    protected_sibling = transfer_root / "sibling"
    target = transfer_root / "token"
    (target / "store.zarr").mkdir(parents=True)
    protected_sibling.mkdir(parents=True)
    monkeypatch.setattr(
        core_functions, "_shared_zarr_transfer_root", lambda: transfer_root
    )
    core_functions._cleanup_shared_zarr_transfer(target)
    assert not target.exists()
    assert protected_sibling.exists()

    transfer_root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    with caplog.at_level(logging.WARNING, logger=core_functions.logger.name):
        core_functions._cleanup_shared_zarr_transfer(transfer_root)
        core_functions._cleanup_shared_zarr_transfer(outside)
    assert "Refusing to remove shared Zarr transfer root directly" in caplog.text
    assert "Refusing to remove shared Zarr transfer path outside" in caplog.text


def test_ome_zarr_support_helpers_cover_metadata_fallback_axes_sizes_and_chunk_writer(
    tmp_path,
    monkeypatch,
):
    store = tmp_path / "image.ome.zarr"
    expected = {"multiscales": [{"datasets": [{"path": "0"}]}]}
    _write_json(store / "zarr.json", expected)
    payload, error = support._read_store_metadata_payload(store)
    assert payload == expected
    assert error is None

    (store / ".zattrs").write_text("{not-json", encoding="utf-8")
    payload, error = support._read_store_metadata_payload(store)
    assert payload is None
    assert ".zattrs" in error

    axis_names, axis_units, error = support._extract_axes(["x"])
    assert axis_names == []
    assert axis_units == {}
    assert "metadata objects" in error
    axis_names, axis_units, error = support._extract_axes([{"name": "   "}])
    assert axis_names == []
    assert axis_units == {}
    assert "non-empty axis names" in error

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
                    "datasets": [{"path": "s0"}, {"path": "s1"}],
                }
            ]
        },
    )
    _write_json(store / "s0" / ".zarray", {"shape": [6, 12, 12]})
    _write_json(store / "s1" / ".zarray", {"shape": [3, 6, 6]})
    detection = support._has_3d_pyramid_downsampling(store)
    assert detection["z_axis_index"] == 0
    assert detection["yx_indices"] == [1, 2]
    _write_json(store / "s1" / ".zarray", {"shape": [6, 6, 6]})
    assert support._has_3d_pyramid_downsampling(store) is None

    output_dir = tmp_path / "s1"
    data = __import__("numpy").arange(9, dtype="uint8").reshape(3, 3)
    error = support._write_zarr_v2_level(
        output_dir,
        data,
        chunks=[2, 2],
        compressor_spec=None,
        filters_spec=None,
        codec=None,
    )
    assert error is None
    metadata = __import__("json").loads(
        (output_dir / ".zarray").read_text(encoding="utf-8")
    )
    assert metadata["dimension_separator"] == "/"
    edge_chunk = (
        __import__("numpy")
        .frombuffer(
            (output_dir / "1" / "1").read_bytes(),
            dtype="uint8",
        )
        .reshape(2, 2)
    )
    assert edge_chunk.tolist() == [[8, 0], [0, 0]]

    monkeypatch.setenv(support.OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "bad")
    assert (
        support._native_ome_zarr_gzip_level()
        == support.DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL
    )
    monkeypatch.setenv(support.OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "-5")
    assert (
        support._native_ome_zarr_gzip_level()
        == support.DEFAULT_OME_ZARR_NATIVE_GZIP_LEVEL
    )
    monkeypatch.setenv(support.OME_ZARR_NATIVE_GZIP_LEVEL_ENV, "4")
    assert support._native_ome_zarr_gzip_level() == 4

    # Edge case: if _load_root_ome_zarr_metadata ever returns (None, None)
    # (a bug in the helper), inspect_ome_zarr_image should return a
    # non-crashing "not recognized" result instead of a None-dereference.
    monkeypatch.setattr(
        support, "_load_root_ome_zarr_metadata", lambda _path: (None, None)
    )
    result = support.inspect_ome_zarr_image(tmp_path / "dummy.zarr")
    assert not result.recognized
    assert result.support_error is not None


def test_import_help_page_serves_markdown_and_404s_when_missing(monkeypatch, tmp_path):
    request = RequestFactory().get("/omeroweb_import/help/")
    monkeypatch.setattr(view_utils, "current_username", lambda request, conn: "alice")

    synthetic_module_path = tmp_path / "pkg" / "views" / "help_view.py"
    synthetic_module_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(help_view, "__file__", str(synthetic_module_path))

    help_doc = tmp_path / "docs" / "help" / "omeroweb_import_help.md"
    help_doc.parent.mkdir(parents=True, exist_ok=True)
    help_doc.write_text("# Import Help\n", encoding="utf-8")

    response = help_view.help_page(request, conn=None)
    assert response.status_code == 200
    assert b"Import Help" in b"".join(response.streaming_content)
    response.close()

    help_doc.unlink()
    with pytest.raises(help_view.Http404):
        help_view.help_page(request, conn=None)


def test_import_urls_module_can_be_loaded_in_isolation_with_stubbed_views(monkeypatch):
    package_module = types.ModuleType("omeroweb_import")
    package_module.__path__ = [str(REPO_ROOT / "omeroweb_import")]
    views_module = types.ModuleType("omeroweb_import.views")
    views_module.__path__ = [str(REPO_ROOT / "omeroweb_import" / "views")]
    monkeypatch.setitem(sys.modules, "omeroweb_import", package_module)
    monkeypatch.setitem(sys.modules, "omeroweb_import.views", views_module)

    index_view = types.ModuleType("omeroweb_import.views.index_view")
    for name in (
        "confirm_import",
        "import_step",
        "index",
        "job_status",
        "list_projects",
        "prune_upload",
        "root_status",
        "start_upload",
        "upload_files",
    ):
        setattr(index_view, name, lambda *args, _name=name, **kwargs: _name)
    monkeypatch.setitem(sys.modules, "omeroweb_import.views.index_view", index_view)

    special_method_settings_view = types.ModuleType(
        "omeroweb_import.views.special_method_settings_view"
    )
    special_method_settings_view.load_settings = lambda *args, **kwargs: "load"
    special_method_settings_view.save_settings = lambda *args, **kwargs: "save"
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.views.special_method_settings_view",
        special_method_settings_view,
    )

    user_settings_view = types.ModuleType("omeroweb_import.views.user_settings_view")
    user_settings_view.save_settings = lambda *args, **kwargs: "save-user"
    monkeypatch.setitem(
        sys.modules,
        "omeroweb_import.views.user_settings_view",
        user_settings_view,
    )

    help_page_view = types.ModuleType("omeroweb_import.views.help_view")
    help_page_view.help_page = lambda *args, **kwargs: "help"
    monkeypatch.setitem(sys.modules, "omeroweb_import.views.help_view", help_page_view)

    spec = importlib.util.spec_from_file_location(
        "omeroweb_import.urls",
        Path(str(REPO_ROOT)) / "omeroweb_import" / "urls.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "omeroweb_import.urls", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    route_map = {pattern.name: str(pattern.pattern) for pattern in module.urlpatterns}
    assert route_map["omeroweb_import_help"] == "help/"
