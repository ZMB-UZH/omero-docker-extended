import sys
import tempfile
import types
import unittest
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
import threading


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_import_stubs():
    if "django.http" not in sys.modules:
        django_module = types.ModuleType("django")
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
        tmp_utils = types.ModuleType("omero_plugin_common.tmp_utils")
        tmp_utils.get_plugin_tmp_dir = lambda name: Path("/tmp") / f"upload-plugin-{name}"
        tmp_cleanup = types.ModuleType("omero_plugin_common.tmp_cleanup")
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

    if "omeroweb_upload.services.data_store" not in sys.modules:
        data_store = types.ModuleType("omeroweb_upload.services.data_store")

        class UserSettingsStoreError(Exception):
            pass

        data_store.UserSettingsStoreError = UserSettingsStoreError
        data_store.save_user_settings = lambda username, settings: None
        data_store.save_special_method_settings = lambda username, method_key, settings: None
        data_store.load_special_method_settings = lambda username, method_key: {}
        sys.modules["omeroweb_upload.services.data_store"] = data_store


_install_import_stubs()

from omeroweb_upload.views import core_functions
from omeroweb_upload.views import index_view


class UploadPluginRegressionTests(unittest.TestCase):
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
            json.loads(error_response.content.decode("utf-8")),
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
            json.loads(error_response.content.decode("utf-8")),
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
        from omeroweb_upload.views import user_settings_view
        from omeroweb_upload.services import data_store

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
        from omeroweb_upload.views import special_method_settings_view
        from omeroweb_upload.services import data_store

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
        template = (REPO_ROOT / "omeroweb_upload/templates/omeroweb_upload/index.html").read_text()

        self.assertIn("let uploadCompletedBytes = 0;", template)
        self.assertIn("function abortActiveUploadRequests()", template)
        self.assertIn("xhr.__uploadProgressCompleted = true;", template)
        self.assertIn("throw firstError || error;", template)
        self.assertIn("entry.file.name || (relativePath.split('/').pop() || relativePath)", template)

    def test_upload_styles_keep_long_names_inside_tree_column(self):
        styles = (REPO_ROOT / "omeroweb_upload/static/omeroweb_upload/styles.css").read_text()

        self.assertIn("grid-template-columns: minmax(0, 1fr) 120px 170px 32px;", styles)
        self.assertIn("overflow-x: hidden;", styles)
        self.assertIn("overflow-wrap: anywhere;", styles)
        self.assertIn("word-break: break-word;", styles)
        self.assertIn("margin-left: 0;", styles)
        self.assertIn("padding-left: 0;", styles)


if __name__ == "__main__":
    unittest.main()
