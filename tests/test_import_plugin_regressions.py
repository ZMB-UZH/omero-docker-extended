import sys
import tempfile
import types
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as real_datetime
from pathlib import Path
from unittest import TestCase, mock, main as unittest_main
import threading


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_import_stubs():
    if "django.http" not in sys.modules:
        django_module = types.ModuleType("django")
        django_module.__path__ = []
        django_conf = types.ModuleType("django.conf")
        django_conf.settings = types.SimpleNamespace()
        django_http = types.ModuleType("django.http")
        django_http.JsonResponse = lambda payload=None, status=200, **kwargs: {
            "payload": payload,
            "status": status,
            **kwargs,
        }
        django_shortcuts = types.ModuleType("django.shortcuts")
        django_shortcuts.render = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
        django_urls = types.ModuleType("django.urls")
        django_urls.reverse = lambda name, *args, **kwargs: f"/{name}/"
        django_csrf = types.ModuleType("django.views.decorators.csrf")
        django_csrf.csrf_exempt = lambda view: view
        sys.modules["django"] = django_module
        sys.modules["django.conf"] = django_conf
        sys.modules["django.http"] = django_http
        sys.modules["django.shortcuts"] = django_shortcuts
        sys.modules["django.urls"] = django_urls
        sys.modules["django.views.decorators.csrf"] = django_csrf
    else:
        django_module = sys.modules.setdefault("django", types.ModuleType("django"))
        if not hasattr(django_module, "__path__"):
            django_module.__path__ = []
        django_conf = sys.modules.setdefault("django.conf", types.ModuleType("django.conf"))
        django_conf.settings = types.SimpleNamespace()

    if "omero" not in sys.modules:
        omero_module = types.ModuleType("omero")
        omero_gateway = types.ModuleType("omero.gateway")
        omero_gateway.BlitzGateway = type("BlitzGateway", (), {})
        omero_model = types.ModuleType("omero.model")
        omero_model.DatasetI = type("DatasetI", (), {})
        omero_model.ProjectDatasetLinkI = type("ProjectDatasetLinkI", (), {})
        omero_model.ProjectI = type("ProjectI", (), {})
        omero_rtypes = types.ModuleType("omero.rtypes")
        omero_rtypes.rstring = lambda value: value
        sys.modules["omero"] = omero_module
        sys.modules["omero.gateway"] = omero_gateway
        sys.modules["omero.model"] = omero_model
        sys.modules["omero.rtypes"] = omero_rtypes

    if "omeroweb.decorators" not in sys.modules:
        omeroweb_module = types.ModuleType("omeroweb")
        omeroweb_decorators = types.ModuleType("omeroweb.decorators")
        omeroweb_decorators.login_required = lambda *args, **kwargs: (lambda view: view)
        sys.modules["omeroweb"] = omeroweb_module
        sys.modules["omeroweb.decorators"] = omeroweb_decorators

    if "portalocker" not in sys.modules:
        portalocker_module = types.ModuleType("portalocker")
        lock_registry = {}
        lock_registry_guard = threading.Lock()

        class LockException(Exception):
            pass

        class Lock:
            def __init__(self, path, mode="a+", timeout=1):
                self.path = str(path)
                self.timeout = timeout
                self._lock = None

            def __enter__(self):
                with lock_registry_guard:
                    self._lock = lock_registry.setdefault(self.path, threading.Lock())
                acquired = self._lock.acquire(timeout=self.timeout)
                if not acquired:
                    raise LockException(f"Timed out acquiring {self.path}")
                return self

            def __exit__(self, exc_type, exc, tb):
                if self._lock and self._lock.locked():
                    self._lock.release()
                return False

        portalocker_module.Lock = Lock
        portalocker_module.exceptions = types.SimpleNamespace(LockException=LockException)
        sys.modules["portalocker"] = portalocker_module

    if "omero_plugin_common.logging_utils" not in sys.modules:
        common_module = types.ModuleType("omero_plugin_common")
        logging_utils = types.ModuleType("omero_plugin_common.logging_utils")
        logging_utils.sanitize_log_value = lambda value: value
        logging_utils.sanitized_exc_info = lambda exc: None
        tmp_utils = types.ModuleType("omero_plugin_common.tmp_utils")
        tmp_utils.get_plugin_tmp_dir = lambda name: Path("/tmp") / f"import-plugin-{name}"
        tmp_cleanup = types.ModuleType("omero_plugin_common.tmp_cleanup")
        tmp_cleanup.safe_mark_path_for_deferred_cleanup = lambda *args, **kwargs: True
        tmp_cleanup.safe_remove_job_data = lambda *args, **kwargs: None
        request_utils = types.ModuleType("omero_plugin_common.request_utils")
        request_utils.current_username = lambda request, conn: "stub-user"
        request_utils.load_request_data = lambda request: {}
        request_utils.parse_json_body = lambda request: ({}, None)
        env_utils = types.ModuleType("omero_plugin_common.env_utils")
        env_utils.ENV_FILE_OMEROWEB = ""
        env_utils.get_env = lambda key, env_file=None: ""
        sys.modules["omero_plugin_common"] = common_module
        sys.modules["omero_plugin_common.logging_utils"] = logging_utils
        sys.modules["omero_plugin_common.tmp_utils"] = tmp_utils
        sys.modules["omero_plugin_common.tmp_cleanup"] = tmp_cleanup
        sys.modules["omero_plugin_common.request_utils"] = request_utils
        sys.modules["omero_plugin_common.env_utils"] = env_utils

    if "omeroweb_import.services.data_store" not in sys.modules:
        data_store = types.ModuleType("omeroweb_import.services.data_store")

        class UserSettingsStoreError(Exception):
            pass

        data_store.UserSettingsStoreError = UserSettingsStoreError
        data_store.save_user_settings = lambda username, settings: None
        data_store.save_special_method_settings = lambda username, method_key, settings: None
        data_store.load_special_method_settings = lambda username, method_key: {}
        sys.modules["omeroweb_import.services.data_store"] = data_store


_install_import_stubs()

from omeroweb_import.views import core_functions
from omeroweb_import.views import index_view


class ImportPluginRegressionTests(TestCase):
    def _json_status_and_payload(self, response):
        if isinstance(response, dict):
            return response["status"], response["payload"]
        return response.status_code, json.loads(response.content)

    def test_normalize_upload_relative_path_rejects_overlong_component_by_utf8_bytes(self):
        raw_name = f"{'ä' * 130}.tif"

        rel_path, error = core_functions._normalize_upload_relative_path(raw_name)

        self.assertIsNone(rel_path)
        self.assertIn("Filename is too long", error)

    def test_validate_staged_target_path_rejects_excessive_target_length(self):
        upload_root = Path("/tmp/upload-root")
        staged_path = "_staged/job/" + ("a" * 5000) + ".tif"

        error = core_functions._validate_staged_target_path(upload_root, staged_path)

        self.assertIn("File path is too long", error)

    def test_resolve_staged_target_path_rejects_traversal(self):
        upload_root = Path("/tmp/upload-root")

        target, error = core_functions._resolve_staged_target_path(upload_root, "../escape.bin")

        self.assertIsNone(target)
        self.assertIn("Invalid", error)

    def test_load_job_rejects_invalid_job_id_without_touching_jobs_root(self):
        with mock.patch.object(
            core_functions,
            "_get_jobs_root",
            side_effect=AssertionError("jobs root should not be resolved"),
        ):
            loaded = core_functions._load_job("../escape")

        self.assertIsNone(loaded)

    def test_save_job_rejects_invalid_job_id_without_touching_jobs_root(self):
        with mock.patch.object(
            core_functions,
            "_get_jobs_root",
            side_effect=AssertionError("jobs root should not be resolved"),
        ):
            saved = core_functions._save_job({"job_id": "../escape"})

        self.assertFalse(saved)

    def test_job_updates_remain_atomic_under_concurrency(self):
        job_id = "a" * 32
        job = {"job_id": job_id, "counter": 0, "files": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_root = Path(tmpdir)
            with mock.patch.object(core_functions, "_get_jobs_root", return_value=jobs_root):
                self.assertTrue(core_functions._save_job(dict(job)))

                def increment_job():
                    for _ in range(25):
                        updated = core_functions._robust_update_job(
                            job_id,
                            lambda job_dict: {**job_dict, "counter": job_dict.get("counter", 0) + 1},
                        )
                        self.assertIsNotNone(updated)

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(increment_job) for _ in range(4)]
                    for future in futures:
                        future.result()

                loaded = core_functions._load_job(job_id)
                self.assertIsNotNone(loaded)
                self.assertEqual(100, loaded["counter"])

    def test_open_session_connection_detaches_joined_session_before_wrapper_teardown(self):
        detach_calls = []
        group_calls = []
        client_calls = {}

        class FakeSession:
            def detachOnDestroy(self):
                detach_calls.append("detached")

        class FakeClient:
            def __init__(self, *, host, port):
                client_calls["host"] = host
                client_calls["port"] = port

            def joinSession(self, session_key):
                client_calls["session_key"] = session_key
                return FakeSession()

        class FakeServiceOpts:
            def setOmeroGroup(self, value):
                group_calls.append(value)

        class FakeGateway:
            def __init__(self, client_obj=None):
                self.client_obj = client_obj
                self.SERVICE_OPTS = FakeServiceOpts()

        with mock.patch.object(
            core_functions.omero,
            "client",
            side_effect=lambda host, port: FakeClient(host=host, port=port),
            create=True,
        ), mock.patch.object(core_functions, "BlitzGateway", FakeGateway):
            conn = core_functions._open_session_connection("session-key", "omeroserver", 4064)

        self.assertIsInstance(conn, FakeGateway)
        self.assertEqual({"host": "omeroserver", "port": 4064, "session_key": "session-key"}, client_calls)
        self.assertEqual(["detached"], detach_calls)
        self.assertEqual(["-1"], group_calls)

    def test_build_omero_cli_command_places_connection_flags_before_subcommand(self):
        command = core_functions._build_omero_cli_command(
            ["import", "--depth", "15"],
            "session-key",
            "omeroserver",
            4064,
        )

        self.assertEqual(
            [
                core_functions.OMERO_CLI,
                "-k",
                "session-key",
                "-s",
                "omeroserver",
                "-p",
                "4064",
                "import",
                "--depth",
                "15",
            ],
            command,
        )

    def test_extract_imported_object_ids_supports_created_image_output(self):
        output = "\n".join(
            [
                "Importing: Image",
                "Created Image 51",
                "Image:52",
                "Created Image 51",
            ]
        )

        self.assertEqual(["51", "52"], sorted(core_functions._extract_imported_object_ids(output)))

    def test_sanitize_cli_output_for_logging_redacts_uuid_tokens(self):
        raw = "Bad session key. Cannot join 12345678-1234-1234-1234-123456789abc on omeroserver:4064."

        sanitized = core_functions._sanitize_cli_output_for_logging(raw)

        self.assertIn("Cannot join ***", sanitized)
        self.assertNotIn("12345678-1234-1234-1234-123456789abc", sanitized)

    def test_build_zarr_store_destination_dir_uses_flat_sanitized_child(self):
        fixed_now = real_datetime(2026, 3, 22, 9, 51, 15, 243000)

        with mock.patch.object(core_functions, "OMERO_ZARR_STORE_ROOT", Path("/OMERO/OME-Zarr")), \
            mock.patch.object(core_functions, "datetime") as mock_datetime, \
            mock.patch.object(core_functions.uuid, "uuid4", return_value=types.SimpleNamespace(hex="deadbeefcafebabe")):
            mock_datetime.now.return_value = fixed_now

            path = core_functions._build_zarr_store_destination_dir(
                "te/st user",
                "users private",
            )

        self.assertEqual(Path("/OMERO/OME-Zarr"), path.parent)
        self.assertEqual(
            "users_private__te_st_user__2026-03-22T09-51-15.243__deadbeef",
            path.name,
        )

    def test_background_import_session_closes_created_session_object(self):
        fake_session = types.SimpleNamespace(
            getUuid=lambda: types.SimpleNamespace(getValue=lambda: "session-key")
        )
        fake_service = mock.Mock()
        fake_service.createSessionWithTimeouts.return_value = fake_session
        fake_admin_conn = mock.Mock()
        fake_admin_conn.c.sf.getSessionService.return_value = fake_service

        with mock.patch.object(core_functions, "_open_admin_connection", return_value=fake_admin_conn), \
            mock.patch.object(core_functions, "_resolve_group_name", return_value="users_private"), \
            mock.patch.object(core_functions, "_get_background_import_session_timeout_seconds", return_value=3600), \
            mock.patch.object(
                core_functions.omero,
                "sys",
                types.SimpleNamespace(Principal=lambda *args: ("Principal", args)),
                create=True,
            ):
            with core_functions._background_import_session(
                "test",
                "omeroserver",
                4064,
                group_name="users_private",
            ) as session_key:
                self.assertEqual("session-key", session_key)

        fake_service.closeSession.assert_called_once_with(fake_session)

    def test_load_job_falls_back_to_unlocked_read_after_lock_contention(self):
        job_id = "b" * 32
        job = {"job_id": job_id, "status": "uploading"}

        class FailingLock:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                raise core_functions.portalocker.exceptions.LockException("busy")

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_root = Path(tmpdir)
            with mock.patch.object(core_functions, "_get_jobs_root", return_value=jobs_root):
                self.assertTrue(core_functions._save_job(dict(job)))
                with mock.patch.object(core_functions.portalocker, "Lock", FailingLock):
                    loaded = core_functions._load_job(job_id)

        self.assertEqual(job["job_id"], loaded["job_id"])
        self.assertEqual(job["status"], loaded["status"])
        self.assertIn("updated", loaded)

    def test_mark_failed_job_for_deferred_cleanup_marks_upload_data_and_job_file(self):
        job_id = "c" * 32
        upload_root = Path("/tmp/upload-root")
        jobs_root = Path("/tmp/jobs-root")
        calls = []

        def capture_marker(path, root, *, ttl_seconds, now=None):
            calls.append((path, root, ttl_seconds, now))
            return True

        with mock.patch.object(core_functions, "_get_upload_root", return_value=upload_root), mock.patch.object(
            core_functions, "_get_jobs_root", return_value=jobs_root
        ), mock.patch.object(
            core_functions, "safe_mark_path_for_deferred_cleanup", side_effect=capture_marker
        ), mock.patch.dict(
            core_functions.os.environ,
            {core_functions.FAILED_IMPORT_RETENTION_SECONDS_ENV: "172800"},
            clear=False,
        ):
            self.assertTrue(core_functions._mark_failed_job_for_deferred_cleanup(job_id))

        self.assertEqual(
            [
                (upload_root / job_id, upload_root, 172800, None),
                (jobs_root / f"{job_id}.json", jobs_root, 172800, None),
            ],
            calls,
        )

    def test_build_import_units_uses_package_root_for_grouped_directory_imports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_root = Path(tmpdir) / "job-root"
            relative_paths = [
                "plate.zarr/.zattrs",
                "plate.zarr/OME/METADATA.ome.xml",
                "plate.zarr/0/0/0",
            ]
            entries = []
            staged_members = {}
            for index, relative_path in enumerate(relative_paths):
                staged_path = core_functions._build_staged_relative_path(relative_path)
                target = upload_root / staged_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x", encoding="utf-8")
                staged_members[relative_path] = target
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

            package_root = upload_root / "_staged" / "plate.zarr"
            group_path = staged_members["plate.zarr/OME/METADATA.ome.xml"]
            stdout = "\n".join(
                [
                    "3 file(s) parsed into 1 group(s) with 1 call(s) to setId",
                    f"# Group: {group_path} SPW: false",
                    str(staged_members["plate.zarr/.zattrs"]),
                    str(staged_members["plate.zarr/OME/METADATA.ome.xml"]),
                    str(staged_members["plate.zarr/0/0/0"]),
                    "",
                ]
            )

            def fake_scan(path, timeout=45):
                if path == package_root:
                    return subprocess.CompletedProcess(
                        args=["omero", "import"],
                        returncode=0,
                        stdout=stdout,
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    args=["omero", "import"],
                    returncode=0,
                    stdout="",
                    stderr="",
                )

            with mock.patch.object(core_functions, "_run_local_import_scan", side_effect=fake_scan):
                units = core_functions._build_import_units({"files": entries}, upload_root)

        self.assertEqual(1, len(units))
        self.assertEqual("plate.zarr", units[0]["relative_path"])
        self.assertEqual("plate.zarr", units[0]["dataset_relative_path"])
        self.assertEqual("_staged/plate.zarr", units[0]["staged_path"])
        self.assertEqual(["_staged/plate.zarr"], units[0]["cleanup_staged_paths"])
        self.assertEqual("METADATA.ome.xml", units[0]["group_header_name"])

    def test_upload_template_keeps_compatibility_polling_without_browser_timeout(self):
        template = (
            REPO_ROOT / "omeroweb_import" / "templates" / "omeroweb_import" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Compatibility check timeout - operation took too long. Please try again.", template)
        self.assertNotIn("Compatibility check timeout - maximum attempts exceeded.", template)
        self.assertNotIn("const maxTimeMs = 5 * 60 * 1000", template)

    def test_upload_template_uses_short_loading_label_for_dropped_files(self):
        template = (
            REPO_ROOT / "omeroweb_import" / "templates" / "omeroweb_import" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("withPreparingFilesState('LOADING', async () => {", template)
        self.assertNotIn("LOADING DROPPED FILES", template)

    def test_resolve_managed_child_path_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with self.assertRaises(ValueError):
                core_functions._resolve_managed_child_path(root, "../escape.txt")

    def test_load_owned_job_rejects_invalid_job_id_before_disk_access(self):
        request = types.SimpleNamespace(user=types.SimpleNamespace(username="alice"))

        with mock.patch.object(index_view, "_load_job") as load_job_mock:
            job, error_response = index_view._load_owned_job(
                request,
                conn=None,
                job_id="../bad",
                missing_error="Upload job not found.",
            )

        self.assertIsNone(job)
        self.assertEqual(
            {"ok": False, "error": "Upload job not found."},
            self._json_status_and_payload(error_response)[1],
        )
        load_job_mock.assert_not_called()

    def test_load_owned_job_rejects_cross_user_job_access(self):
        request = types.SimpleNamespace(user=types.SimpleNamespace(username="alice"))
        job_payload = {"job_id": "a" * 32, "username": "bob"}

        with mock.patch.object(index_view, "_load_job", return_value=job_payload), mock.patch.object(
            index_view, "current_username", return_value="alice"
        ):
            job, error_response = index_view._load_owned_job(
                request,
                conn=None,
                job_id="a" * 32,
                missing_error="Upload job not found.",
            )

        self.assertIsNone(job)
        self.assertEqual(
            {"ok": False, "error": "Upload job not found."},
            self._json_status_and_payload(error_response)[1],
        )

    def test_load_owned_job_allows_matching_owner(self):
        request = types.SimpleNamespace(user=types.SimpleNamespace(username="alice"))
        job_payload = {"job_id": "a" * 32, "username": "alice"}

        with mock.patch.object(index_view, "_load_job", return_value=job_payload), mock.patch.object(
            index_view, "current_username", return_value="alice"
        ):
            job, error_response = index_view._load_owned_job(
                request,
                conn=None,
                job_id="a" * 32,
                missing_error="Upload job not found.",
            )

        self.assertEqual(job_payload, job)
        self.assertIsNone(error_response)

    def test_confirm_import_defers_dataset_preparation_to_background_thread(self):
        job_id = "d" * 32
        request = types.SimpleNamespace(method="POST", user=types.SimpleNamespace(username="alice"))
        job_payload = {
            "job_id": job_id,
            "username": "alice",
            "status": "awaiting_confirmation",
            "compatibility_thread_active": True,
        }
        import_started = []

        with mock.patch.object(index_view, "_load_owned_job", return_value=(job_payload, None)), mock.patch.object(
            index_view, "_save_job", return_value=True
        ), mock.patch.object(
            index_view,
            "_prepare_job_import_datasets",
            side_effect=AssertionError("dataset prep must stay off confirm_import"),
        ), mock.patch.object(
            index_view, "_start_import_thread", side_effect=lambda current_job_id: import_started.append(current_job_id)
        ):
            response = index_view.confirm_import(request, conn=object(), job_id=job_id)

        status, payload = self._json_status_and_payload(response)
        self.assertEqual(200, status)
        self.assertEqual({"ok": True, "status": "ready"}, payload)
        self.assertTrue(job_payload["compatibility_confirmed"])
        self.assertFalse(job_payload["compatibility_thread_active"])
        self.assertEqual("ready", job_payload["status"])
        self.assertEqual([job_id], import_started)

    def test_ensure_job_dataset_targets_uses_request_connection_when_available(self):
        request_conn = types.SimpleNamespace(SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda group: None))
        created = []

        def fail_open_service_connection(*args, **kwargs):
            raise AssertionError("service connection should not be used when request connection is available")

        def fake_get_or_create_dataset(conn, name, dataset_map, project_id=None):
            created.append((conn, name, project_id))
            dataset_map[name] = 11
            return 11

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

        with mock.patch.object(core_functions, "_open_service_connection", side_effect=fail_open_service_connection), \
             mock.patch.object(core_functions, "_get_or_create_dataset", side_effect=fake_get_or_create_dataset):
            ok, error = core_functions._ensure_job_dataset_targets(job, entries_to_import, conn=request_conn)

        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual([(request_conn, "folder", 9)], created)
        self.assertEqual({"folder": 11}, job["dataset_map"])

    def test_prepare_request_job_import_datasets_uses_zarr_package_root_without_import_scan(self):
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

        with mock.patch.object(
            core_functions,
            "_get_or_create_dataset",
            side_effect=fake_get_or_create_dataset,
        ), mock.patch.object(
            core_functions,
            "_save_job",
            return_value=True,
        ):
            prepared_job, error = core_functions._prepare_request_job_import_datasets(
                job["job_id"],
                job,
                conn=_RequestConn(),
            )

        self.assertIs(prepared_job, job)
        self.assertIsNone(error)
        self.assertEqual(1, len(created))
        self.assertEqual("plate.zarr", created[0][1])
        self.assertEqual(9, created[0][2])
        self.assertEqual({"plate.zarr": 21}, job["dataset_map"])
        self.assertEqual(["4"], group_calls)

    def test_prepare_uploaded_job_dataset_targets_runs_when_job_is_ready(self):
        request_conn = object()
        job = {
            "job_id": "d" * 32,
            "status": "ready",
            "files": [{"status": "uploaded", "relative_path": "plate.zarr/.zattrs"}],
        }

        with mock.patch.object(
            index_view,
            "_prepare_uploaded_job_for_request_path_import",
            return_value=(job, None),
        ) as prepare_mock:
            prepared_job, error = index_view._prepare_uploaded_job_dataset_targets(
                job["job_id"],
                job,
                request_conn,
            )

        self.assertIs(prepared_job, job)
        self.assertIsNone(error)
        prepare_mock.assert_called_once_with(job["job_id"], job, request_conn)

    def test_prepare_uploaded_job_for_request_path_import_waits_for_planned_units_during_compatibility(self):
        job = {
            "job_id": "e" * 32,
            "status": "checking",
            "compatibility_enabled": True,
            "compatibility_thread_active": True,
            "planned_import_units": [],
            "files": [{"status": "uploaded", "relative_path": "bundle.pkg/data/0.bin"}],
        }

        with mock.patch.object(
            core_functions,
            "_prepare_request_job_import_datasets",
            side_effect=AssertionError("request-path preparation should wait for planned units"),
        ):
            prepared_job, error = core_functions._prepare_uploaded_job_for_request_path_import(
                job["job_id"],
                job,
                conn=object(),
            )

        self.assertIs(prepared_job, job)
        self.assertIsNone(error)

    def test_prepare_uploaded_job_for_request_path_import_waits_for_background_import_plan(self):
        job = {
            "job_id": "f" * 32,
            "status": "checking",
            "compatibility_enabled": False,
            "compatibility_thread_active": True,
            "planned_import_units": [],
            "files": [{"status": "uploaded", "relative_path": "plate.zarr/0/0/0"}],
        }

        with mock.patch.object(
            core_functions,
            "_prepare_request_job_import_datasets",
            side_effect=AssertionError("request-path preparation should wait for the persisted import plan"),
        ):
            prepared_job, error = core_functions._prepare_uploaded_job_for_request_path_import(
                job["job_id"],
                job,
                conn=object(),
            )

        self.assertIs(prepared_job, job)
        self.assertIsNone(error)

    def test_run_compatibility_check_skips_scan_when_compatibility_is_disabled(self):
        job_id = "1" * 32
        job_state = {
            "job_id": job_id,
            "status": "checking",
            "compatibility_enabled": False,
            "compatibility_thread_active": True,
            "compatibility_status": "checking",
            "files": [{"status": "uploaded", "relative_path": "plate.zarr/.zattrs"}],
            "planned_import_units": [],
            "host": "omeroserver",
            "port": 4064,
        }
        planned_unit = {
            "relative_path": "plate.zarr",
            "dataset_relative_path": "plate.zarr",
            "covered_relative_paths": ["plate.zarr/.zattrs"],
        }

        def fake_load_job(current_job_id):
            self.assertEqual(job_id, current_job_id)
            return job_state

        def fake_update_job(current_job_id, updater):
            self.assertEqual(job_id, current_job_id)
            updater(job_state)
            return job_state

        with mock.patch.object(core_functions, "_load_job", side_effect=fake_load_job), mock.patch.object(
            core_functions,
            "_build_import_units",
            return_value=[planned_unit],
        ), mock.patch.object(
            core_functions,
            "_update_job",
            side_effect=fake_update_job,
        ), mock.patch.object(
            core_functions,
            "_check_import_compatibility",
            side_effect=AssertionError("compatibility scan should not run when disabled"),
        ):
            core_functions._run_compatibility_check(job_id)

        self.assertEqual(
            [
                {
                    "relative_path": "plate.zarr",
                    "dataset_relative_path": "plate.zarr",
                    "covered_relative_paths": ["plate.zarr/.zattrs"],
                }
            ],
            job_state["planned_import_units"],
        )
        self.assertFalse(job_state["compatibility_thread_active"])
        self.assertEqual("compatible", job_state["compatibility_status"])
        self.assertEqual("ready", job_state["status"])

    def test_job_status_starts_ready_job_after_request_path_preparation(self):
        request = types.SimpleNamespace(method="GET")
        job_id = "f" * 32
        job = {
            "job_id": job_id,
            "status": "ready",
            "import_thread_started": False,
            "files": [],
            "uploaded_bytes": 0,
            "imported_bytes": 0,
            "total_bytes": 0,
            "errors": [],
            "messages": [],
            "compatibility_status": "compatible",
            "compatibility_enabled": True,
        }

        with mock.patch.object(index_view, "_load_owned_job", return_value=(job, None)), mock.patch.object(
            index_view,
            "_prepare_uploaded_job_dataset_targets",
            return_value=(job, None),
        ), mock.patch.object(
            index_view,
            "_prepare_ready_job_for_import_start",
            return_value=(job, None),
        ), mock.patch.object(index_view, "_start_import_thread") as start_import, mock.patch.object(
            index_view,
            "_load_job",
            return_value=job,
        ):
            response = index_view.job_status.__wrapped__(request, job_id, conn=object())

        status, payload = self._json_status_and_payload(response)
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        start_import.assert_called_once_with(job_id)

    def test_vizarr_openwith_uses_browser_origin_for_source_url(self):
        script = (
            REPO_ROOT
            / "omero_web_zarr/static/omero_web_zarr/openwith.js"
        ).read_text(encoding="utf-8")

        self.assertIn("window.location.origin", script)
        self.assertIn("encodeURIComponent(sourceUrl.toString())", script)

    def test_open_user_owned_background_connection_requires_service_connection(self):
        with mock.patch.object(
            core_functions,
            "_open_group_scoped_session_connection",
        ) as open_session:
            conn = core_functions._open_user_owned_background_connection(
                "alice",
                session_key="session-key",
                host="omeroserver",
                port=4064,
                group_id=4,
                purpose="dataset preparation",
            )

        self.assertIsNone(conn)
        open_session.assert_not_called()

    def test_ensure_job_dataset_targets_hides_impersonation_details(self):
        class _FakeServiceConn:
            def __init__(self):
                self.closed = False

            def suConn(self, username):
                return None

            def close(self):
                self.closed = True

        fake_service_conn = _FakeServiceConn()
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

        with mock.patch.object(core_functions, "_open_service_connection", return_value=fake_service_conn):
            ok, error = core_functions._ensure_job_dataset_targets(job, entries_to_import)

        self.assertFalse(ok)
        self.assertEqual("OMERO could not prepare the destination for this import.", error)
        self.assertNotIn("impersonate", error.lower())
        self.assertTrue(fake_service_conn.closed)

    def test_start_import_thread_does_not_spawn_when_save_fails(self):
        job = {"job_id": "b" * 32, "status": "ready", "import_thread_started": False}

        with mock.patch.object(core_functions, "_load_job", return_value=job), mock.patch.object(
            core_functions, "_save_job", return_value=False
        ), mock.patch.object(core_functions.threading, "Thread") as thread_cls, mock.patch.object(
            core_functions.logger, "error"
        ):
            core_functions._start_import_thread(job["job_id"])

        thread_cls.assert_not_called()

    def test_upload_user_settings_view_hides_store_exception_details(self):
        from omeroweb_import.views import user_settings_view
        from omeroweb_import.services import data_store

        request = types.SimpleNamespace(
            method="POST",
            body=b"{}",
            user=types.SimpleNamespace(username="alice"),
        )
        with mock.patch.object(user_settings_view, "load_request_data", return_value={"settings": {}}), mock.patch.object(
            user_settings_view,
            "save_user_settings",
            side_effect=data_store.UserSettingsStoreError("db secret"),
        ):
            response = user_settings_view.save_settings(request, conn=object())

        status, payload = self._json_status_and_payload(response)
        self.assertEqual(500, status)
        self.assertEqual("Could not save user settings.", payload["error"])
        self.assertNotIn("secret", payload["error"])

    def test_upload_special_method_load_hides_store_exception_details(self):
        from omeroweb_import.views import special_method_settings_view
        from omeroweb_import.services import data_store

        request = types.SimpleNamespace(
            method="POST",
            body=b"{}",
            user=types.SimpleNamespace(username="alice"),
        )
        with mock.patch.object(
            special_method_settings_view,
            "load_request_data",
            return_value={"method": "sem_edx"},
        ), mock.patch.object(
            special_method_settings_view,
            "load_special_method_settings",
            side_effect=data_store.UserSettingsStoreError("db secret"),
        ):
            response = special_method_settings_view.load_settings(request, conn=object())

        status, payload = self._json_status_and_payload(response)
        self.assertEqual(500, status)
        self.assertEqual("Could not load special method settings.", payload["error"])
        self.assertNotIn("secret", payload["error"])

    def test_upload_template_keeps_completed_bytes_and_aborts_parallel_failures(self):
        template = (REPO_ROOT / "omeroweb_import/templates/omeroweb_import/index.html").read_text()

        self.assertIn("let uploadCompletedBytes = 0;", template)
        self.assertIn("function abortActiveUploadRequests()", template)
        self.assertIn("xhr.__uploadProgressCompleted = true;", template)
        self.assertIn("throw firstError || error;", template)
        self.assertIn("entry.file.name || (relativePath.split('/').pop() || relativePath)", template)

    def test_upload_styles_keep_long_names_inside_tree_column(self):
        styles = (REPO_ROOT / "omeroweb_import/static/omeroweb_import/styles.css").read_text()

        self.assertIn("grid-template-columns: minmax(0, 1fr) 120px 170px 32px;", styles)
        self.assertIn("overflow-x: hidden;", styles)
        self.assertIn("overflow-wrap: anywhere;", styles)
        self.assertIn("word-break: break-word;", styles)
        self.assertIn("margin-left: 0;", styles)
        self.assertIn("padding-left: 0;", styles)


if __name__ == "__main__":
    unittest_main()
