from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest import TestCase, mock, main as unittest_main


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = Path(tempfile.gettempdir()) / "omp-plugin-tests"
TEST_OMERO_CLI = "omero-cli"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_import_stubs() -> None:
    if "django" not in sys.modules:
        sys.modules["django"] = types.ModuleType("django")
    if not hasattr(sys.modules["django"], "__path__"):
        sys.modules["django"].__path__ = []

    django_conf = sys.modules.setdefault("django.conf", types.ModuleType("django.conf"))
    django_conf.settings = types.SimpleNamespace()

    django_http = sys.modules.setdefault("django.http", types.ModuleType("django.http"))

    def _json_response(payload=None, status=200, **kwargs):
        return {"payload": payload, "status": status, **kwargs}

    def _http_response(content="", status=200, **kwargs):
        return {"content": content, "status": status, **kwargs}

    django_http.JsonResponse = _json_response
    django_http.HttpResponse = _http_response
    django_http.HttpResponseBadRequest = lambda content="", **kwargs: _http_response(
        content,
        status=400,
        **kwargs,
    )

    django_shortcuts = sys.modules.setdefault(
        "django.shortcuts",
        types.ModuleType("django.shortcuts"),
    )
    django_shortcuts.render = lambda request, template, context=None, status=200: {
        "template": template,
        "context": context or {},
        "status": status,
    }

    django_urls = sys.modules.setdefault("django.urls", types.ModuleType("django.urls"))
    django_urls.reverse = lambda name, *args, **kwargs: f"/{name}/"

    django_utils_html = sys.modules.setdefault(
        "django.utils.html",
        types.ModuleType("django.utils.html"),
    )
    django_utils_html.escape = str

    django_utils_safe = sys.modules.setdefault(
        "django.utils.safestring",
        types.ModuleType("django.utils.safestring"),
    )
    django_utils_safe.mark_safe = lambda value: value

    csrf_module = sys.modules.setdefault(
        "django.views.decorators.csrf",
        types.ModuleType("django.views.decorators.csrf"),
    )
    csrf_module.csrf_exempt = lambda view: view
    csrf_module.ensure_csrf_cookie = lambda view: view

    if "omeroweb" not in sys.modules:
        sys.modules["omeroweb"] = types.ModuleType("omeroweb")

    decorators_module = sys.modules.setdefault(
        "omeroweb.decorators",
        types.ModuleType("omeroweb.decorators"),
    )
    decorators_module.login_required = lambda *args, **kwargs: lambda view: view

    portalocker_module = types.ModuleType("portalocker")

    class Lock:
        def __init__(self, *args, **kwargs):
            pass

        def acquire(self):
            return None

        def release(self):
            return None

    class LockException(Exception):
        pass

    portalocker_module.Lock = Lock
    portalocker_module.exceptions = types.SimpleNamespace(LockException=LockException)
    sys.modules["portalocker"] = portalocker_module

    if "omero" not in sys.modules:
        omero_module = types.ModuleType("omero")

        class _DummyClient:
            def createSession(self, *args, **kwargs):
                return None

            def closeSession(self):
                return None

        omero_module.client = lambda *args, **kwargs: _DummyClient()
        sys.modules["omero"] = omero_module

    omero_model = sys.modules.setdefault("omero.model", types.ModuleType("omero.model"))
    omero_model.MapAnnotationI = type("MapAnnotationI", (), {})
    omero_model.NamedValue = type("NamedValue", (), {})
    omero_model.ImageAnnotationLinkI = type("ImageAnnotationLinkI", (), {})

    omero_rtypes = sys.modules.setdefault(
        "omero.rtypes", types.ModuleType("omero.rtypes")
    )
    omero_rtypes.rstring = lambda value: value

    if "omero_plugin_common" not in sys.modules:
        common_module = types.ModuleType("omero_plugin_common")
        common_module.__path__ = [str(REPO_ROOT / "omero_plugin_common")]
        sys.modules["omero_plugin_common"] = common_module
    else:
        common_module = sys.modules["omero_plugin_common"]
        if not hasattr(common_module, "__path__"):
            common_module.__path__ = [str(REPO_ROOT / "omero_plugin_common")]

    env_utils = sys.modules.setdefault(
        "omero_plugin_common.env_utils",
        types.ModuleType("omero_plugin_common.env_utils"),
    )
    env_utils.ENV_FILE_OMEROWEB = ""
    env_utils.get_env = lambda key, env_file=None: (
        str(TEST_TMP_ROOT) if key == "OMERO_WEB_ROOT" else ""
    )

    tmp_utils = sys.modules.setdefault(
        "omero_plugin_common.tmp_utils",
        types.ModuleType("omero_plugin_common.tmp_utils"),
    )
    tmp_utils.get_plugin_tmp_dir = lambda name: TEST_TMP_ROOT / f"omp-plugin-{name}"

    request_utils = sys.modules.setdefault(
        "omero_plugin_common.request_utils",
        types.ModuleType("omero_plugin_common.request_utils"),
    )
    request_utils.current_username = lambda request, conn: "stub-user"
    request_utils.load_request_data = lambda request: json.loads(
        request.body.decode("utf-8")
    )
    request_utils.parse_json_body = lambda request: (
        json.loads(request.body.decode("utf-8")),
        None,
    )

    logging_utils = sys.modules.setdefault(
        "omero_plugin_common.logging_utils",
        types.ModuleType("omero_plugin_common.logging_utils"),
    )
    logging_utils.sanitize_log_value = lambda value: value
    logging_utils.sanitized_exc_info = lambda exc: None
    common_module.process_utils = importlib.import_module(
        "omero_plugin_common.process_utils"
    )


def _install_omp_dependency_stubs() -> None:
    package_module = types.ModuleType("omeroweb_omp_plugin")
    package_module.__path__ = [str(REPO_ROOT / "omeroweb_omp_plugin")]
    sys.modules["omeroweb_omp_plugin"] = package_module

    views_package = types.ModuleType("omeroweb_omp_plugin.views")
    views_package.__path__ = [str(REPO_ROOT / "omeroweb_omp_plugin" / "views")]
    sys.modules["omeroweb_omp_plugin.views"] = views_package

    services_package = types.ModuleType("omeroweb_omp_plugin.services")
    services_package.__path__ = [str(REPO_ROOT / "omeroweb_omp_plugin" / "services")]
    sys.modules["omeroweb_omp_plugin.services"] = services_package

    strings_package = types.ModuleType("omeroweb_omp_plugin.strings")
    strings_package.__path__ = [str(REPO_ROOT / "omeroweb_omp_plugin" / "strings")]
    sys.modules["omeroweb_omp_plugin.strings"] = strings_package

    constants_module = types.ModuleType("omeroweb_omp_plugin.constants")
    constants_module.OMERO_CLI = TEST_OMERO_CLI
    constants_module.CHUNK_SIZE = 5
    constants_module.MAP_NS = "map-ns"
    constants_module.HASH_KEY = "hash-key"
    constants_module.DEFAULT_VARIABLE_NAMES = ["Var1", "Var2"]
    constants_module.MAX_PARSED_VARIABLES = 20
    constants_module.MAX_VARIABLE_SET_ENTRIES = 30
    sys.modules["omeroweb_omp_plugin.constants"] = constants_module

    core_module = types.ModuleType("omeroweb_omp_plugin.services.core")
    core_module.collect_images_in_project = lambda conn, project_id: []
    core_module.find_annotation_link_ids = lambda conn, annotation_id: []
    core_module.find_plugin_annotation_ids = lambda conn, image_id: []
    core_module.find_map_annotation_ids = lambda conn, image_id: []
    core_module.get_id = lambda obj: getattr(obj, "id", obj)
    core_module.get_text = lambda value: value
    core_module.load_job = lambda job_id: None
    core_module.save_job = lambda job: True
    core_module._job_lock_path = lambda job_id: str(TEST_TMP_ROOT / f"{job_id}.lock")
    core_module.collect_images_by_selected_datasets = lambda *args, **kwargs: []
    core_module.collect_dataset_summaries = lambda *args, **kwargs: []
    core_module.parse_filename = lambda *args, **kwargs: []
    core_module.fetch_images_by_ids = lambda conn, image_ids: {}
    core_module.compute_plugin_hash = lambda *args, **kwargs: "hash"
    core_module.delete_existing_annotations = lambda *args, **kwargs: (0, 0, 0)
    core_module.extract_acquisition_metadata = lambda *args, **kwargs: {}
    sys.modules["omeroweb_omp_plugin.services.core"] = core_module

    ai_assist_module = types.ModuleType("omeroweb_omp_plugin.services.ai_assist")

    class AiAssistError(Exception):
        pass

    ai_assist_module.AiAssistError = AiAssistError
    ai_assist_module.generate_ai_regex = lambda *args, **kwargs: {
        "regex": "_",
        "source": "ai",
    }
    ai_assist_module.generate_ai_parsed_values = lambda *args, **kwargs: {
        "rows": [],
        "source": "ai",
    }
    sys.modules["omeroweb_omp_plugin.services.ai_assist"] = ai_assist_module

    data_store_module = types.ModuleType("omeroweb_omp_plugin.services.data_store")

    class VariableStoreError(Exception):
        pass

    class AiCredentialStoreError(Exception):
        pass

    class UserSettingsStoreError(Exception):
        pass

    class UserDataStoreError(Exception):
        pass

    data_store_module.VariableStoreError = VariableStoreError
    data_store_module.AiCredentialStoreError = AiCredentialStoreError
    data_store_module.UserSettingsStoreError = UserSettingsStoreError
    data_store_module.UserDataStoreError = UserDataStoreError
    data_store_module.get_ai_credential = lambda *args, **kwargs: ""
    data_store_module.list_ai_credentials = lambda *args, **kwargs: []
    data_store_module.save_ai_credentials = lambda *args, **kwargs: None
    data_store_module.list_variable_sets = lambda *args, **kwargs: []
    data_store_module.load_variable_set = lambda *args, **kwargs: None
    data_store_module.save_variable_set = lambda *args, **kwargs: None
    data_store_module.delete_variable_set = lambda *args, **kwargs: None
    data_store_module.save_user_settings = lambda *args, **kwargs: None
    data_store_module.delete_all_ai_credentials = lambda *args, **kwargs: 0
    data_store_module.delete_all_variable_sets = lambda *args, **kwargs: 0
    data_store_module.delete_all_user_data = lambda *args, **kwargs: 0
    sys.modules["omeroweb_omp_plugin.services.data_store"] = data_store_module

    ai_providers_module = types.ModuleType("omeroweb_omp_plugin.services.ai_providers")
    ai_providers_module.list_ai_provider_options = lambda: []
    sys.modules["omeroweb_omp_plugin.services.ai_providers"] = ai_providers_module

    filename_utils_module = types.ModuleType(
        "omeroweb_omp_plugin.services.filename_utils"
    )
    filename_utils_module.suggest_separator_regex = lambda filenames: "_"
    sys.modules["omeroweb_omp_plugin.services.filename_utils"] = filename_utils_module

    rate_limit_module = types.ModuleType("omeroweb_omp_plugin.services.rate_limit")
    rate_limit_module.build_rate_limit_message = lambda remaining: (
        f"Rate limited: {remaining}"
    )
    rate_limit_module.check_major_action_rate_limit = lambda request, conn: (True, 0)
    sys.modules["omeroweb_omp_plugin.services.rate_limit"] = rate_limit_module


def _clear_omp_modules() -> None:
    for module_name in list(sys.modules):
        if module_name.startswith("omeroweb_omp_plugin"):
            sys.modules.pop(module_name, None)


TEST_AUTH_FIXTURE = "test-fixture-auth"
TEST_AUTH_HMAC_FIXTURE = "test-fixture-hmac"


class OmpPluginViewRegressionTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_import_stubs()

    def setUp(self) -> None:
        _clear_omp_modules()
        _install_omp_dependency_stubs()

    def _make_request(self, method: str = "POST", payload: dict | None = None):
        body = json.dumps(payload or {}).encode("utf-8")
        return types.SimpleNamespace(
            method=method,
            body=body,
            COOKIES={},
            META={},
            _dont_enforce_csrf_checks=True,
        )

    def _make_form_request(self, method: str = "POST", post: dict | None = None):
        return types.SimpleNamespace(
            method=method,
            POST=post or {},
            GET={},
            body=b"",
            COOKIES={},
            META={},
            _dont_enforce_csrf_checks=True,
        )

    def test_delete_plugin_view_returns_missing_password_error_without_unbound_local(
        self,
    ) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.delete_plugin_view"
        )

        response = view_module.delete_plugin_keyvaluepairs(
            self._make_request(payload={"project_id": 123}),
            conn=mock.Mock(),
        )

        self.assertEqual(400, response["status"])
        self.assertEqual("Missing password", response["payload"]["error"])

    def test_delete_all_view_returns_missing_password_error_without_unbound_local(
        self,
    ) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.delete_all_view"
        )

        response = view_module.delete_all_keyvaluepairs(
            self._make_request(payload={"project_id": 123}),
            conn=mock.Mock(),
        )

        self.assertEqual(400, response["status"])
        self.assertEqual("Missing password", response["payload"]["error"])

    def test_job_view_password_validator_reports_missing_password(self) -> None:
        job_view = importlib.import_module("omeroweb_omp_plugin.views.job_view")

        valid, error = job_view._validate_user_password(mock.Mock(), "")

        self.assertFalse(valid)
        self.assertEqual("Missing password", error)

    def test_delete_plugin_login_failure_hides_cli_output(self) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.delete_plugin_view"
        )
        with mock.patch.object(
            view_module,
            "validate_user_password",
            return_value=(False, "Wrong password."),
        ):
            response = view_module.delete_plugin_keyvaluepairs(
                self._make_request(
                    payload={"project_id": 1, "password": TEST_AUTH_FIXTURE}
                ),
                conn=mock.Mock(),
            )

        self.assertEqual("OMERO.web login failed", response["payload"]["error"])
        self.assertNotIn("stdout", response["payload"])
        self.assertNotIn("stderr", response["payload"])

    def test_delete_plugin_view_uses_session_key_cli_without_passing_password(
        self,
    ) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.delete_plugin_view"
        )
        conn = mock.Mock()
        conn.getUser.return_value.getName.return_value = "alice"
        conn.getObject.return_value = None

        image = types.SimpleNamespace(id=12)
        recorded_commands = []

        def _record_run(cmd, **kwargs):
            recorded_commands.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(
                view_module, "validate_user_password", return_value=(True, None)
            ),
            mock.patch.object(
                view_module,
                "build_omero_cli_base_command",
                return_value=[
                    TEST_OMERO_CLI,
                    "-k",
                    "session-123",
                    "-s",
                    "omeroserver",
                    "-p",
                    "4064",
                ],
            ),
            mock.patch.object(
                view_module,
                "collect_images_in_project",
                return_value=[image],
            ),
            mock.patch.object(
                view_module,
                "find_plugin_annotation_ids",
                return_value=[77],
            ),
            mock.patch.object(
                view_module,
                "find_annotation_link_ids",
                return_value=[],
            ),
            mock.patch.object(
                view_module.subprocess,
                "run",
                side_effect=_record_run,
            ),
        ):
            response = view_module.delete_plugin_keyvaluepairs(
                self._make_request(
                    payload={"project_id": 1, "password": TEST_AUTH_HMAC_FIXTURE}
                ),
                conn=conn,
            )

        self.assertEqual(200, response["status"])
        self.assertEqual(1, len(recorded_commands))
        self.assertEqual(
            [
                TEST_OMERO_CLI,
                "-k",
                "session-123",
                "-s",
                "omeroserver",
                "-p",
                "4064",
                "delete",
                "Annotation:77",
                "--force",
            ],
            recorded_commands[0],
        )
        self.assertNotIn(TEST_AUTH_HMAC_FIXTURE, recorded_commands[0])

    def test_delete_all_view_uses_session_key_cli_without_passing_password(
        self,
    ) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.delete_all_view"
        )
        conn = mock.Mock()
        conn.getUser.return_value.getName.return_value = "alice"

        image = types.SimpleNamespace(id=12)
        recorded_commands = []

        def _record_run(cmd, **kwargs):
            recorded_commands.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(
                view_module, "validate_user_password", return_value=(True, None)
            ),
            mock.patch.object(
                view_module,
                "build_omero_cli_base_command",
                return_value=[
                    TEST_OMERO_CLI,
                    "-k",
                    "session-123",
                    "-s",
                    "omeroserver",
                    "-p",
                    "4064",
                ],
            ),
            mock.patch.object(
                view_module,
                "collect_images_in_project",
                return_value=[image],
            ),
            mock.patch.object(
                view_module,
                "find_map_annotation_ids",
                return_value=[],
            ),
            mock.patch.object(
                view_module.subprocess,
                "run",
                side_effect=_record_run,
            ),
        ):
            response = view_module.delete_all_keyvaluepairs(
                self._make_request(
                    payload={"project_id": 1, "password": TEST_AUTH_HMAC_FIXTURE}
                ),
                conn=conn,
            )

        self.assertEqual(200, response["status"])
        self.assertEqual(1, len(recorded_commands))
        self.assertEqual(
            [
                TEST_OMERO_CLI,
                "-k",
                "session-123",
                "-s",
                "omeroserver",
                "-p",
                "4064",
                "delete",
                "Image/Annotation:12",
                "--include",
                "MapAnnotation",
                "--include",
                "ImageAnnotationLink",
                "--force",
            ],
            recorded_commands[0],
        )
        self.assertNotIn(TEST_AUTH_HMAC_FIXTURE, recorded_commands[0])

    def test_job_view_invalid_regex_message_is_sanitized(self) -> None:
        job_view = importlib.import_module("omeroweb_omp_plugin.views.job_view")

        response = job_view.start_job(
            self._make_request(
                payload={"project_id": 123, "separator_mode": "regex", "separator": "("}
            ),
            conn=mock.Mock(),
        )

        self.assertEqual(400, response["status"])
        self.assertEqual("Invalid regex pattern.", response["payload"]["error"])

    def test_job_view_start_job_hides_internal_exception_text(self) -> None:
        job_view = importlib.import_module("omeroweb_omp_plugin.views.job_view")

        with (
            mock.patch.object(job_view, "_resolve_image_ids", return_value=[1]),
            mock.patch.object(
                job_view,
                "save_job",
                side_effect=RuntimeError("secret boom"),
            ),
        ):
            response = job_view.start_job(
                self._make_request(payload={"project_id": 123}),
                conn=mock.Mock(),
            )

        self.assertEqual(500, response["status"])
        self.assertEqual("Unexpected error.", response["payload"]["error"])

    def test_job_progress_hides_exception_text_in_last_log(self) -> None:
        job_view = importlib.import_module("omeroweb_omp_plugin.views.job_view")
        image = types.SimpleNamespace(id=1, getName=lambda: "demo.tif")
        job = {
            "job_id": "job-1",
            "type": "del_all",
            "total": 1,
            "index": 0,
            "var_names": [],
            "delete_mode": "all",
            "separator": "_",
            "image_ids": [1],
            "started": 1.0,
        }
        conn = mock.Mock()
        conn.getUpdateService.return_value = object()

        with (
            mock.patch.object(job_view, "load_job", return_value=job),
            mock.patch.object(job_view, "fetch_images_by_ids", return_value={1: image}),
            mock.patch.object(
                job_view,
                "delete_existing_annotations",
                side_effect=RuntimeError("sensitive details"),
            ),
            mock.patch.object(job_view, "save_job", return_value=True),
            mock.patch.object(job_view.time, "time", return_value=2.0),
        ):
            response = job_view.job_progress(
                self._make_request(method="GET"),
                job_id="job-1",
                conn=conn,
            )

        self.assertEqual(200, response["status"])
        self.assertIn(
            "ERROR deleting ALL key-value pairs.", response["payload"]["last_log"]
        )
        self.assertNotIn("sensitive details", response["payload"]["last_log"])

    def test_delete_views_hide_internal_exception_text(self) -> None:
        cases = [
            (
                "omeroweb_omp_plugin.views.delete_plugin_view",
                "delete_plugin_keyvaluepairs",
            ),
            ("omeroweb_omp_plugin.views.delete_all_view", "delete_all_keyvaluepairs"),
        ]
        for module_name, function_name in cases:
            with self.subTest(module=module_name):
                view_module = importlib.import_module(module_name)
                conn = mock.Mock()
                conn.getUser.return_value.getName.return_value = "alice"

                with (
                    mock.patch.object(
                        view_module,
                        "collect_images_in_project",
                        side_effect=RuntimeError("secret delete failure"),
                    ),
                    mock.patch.object(
                        view_module,
                        "validate_user_password",
                        return_value=(True, None),
                    ),
                    mock.patch.object(
                        view_module,
                        "build_omero_cli_base_command",
                        return_value=[
                            TEST_OMERO_CLI,
                            "-k",
                            "session-123",
                            "-s",
                            "omeroserver",
                            "-p",
                            "4064",
                        ],
                    ),
                    mock.patch.object(
                        view_module.subprocess,
                        "run",
                        return_value=types.SimpleNamespace(
                            returncode=0, stdout="", stderr=""
                        ),
                    ),
                ):
                    response = getattr(view_module, function_name)(
                        self._make_request(
                            payload={"project_id": 1, "password": TEST_AUTH_FIXTURE}
                        ),
                        conn=conn,
                    )

                self.assertEqual(500, response["status"])
                self.assertEqual("Unexpected error.", response["payload"]["error"])

    def test_variable_set_views_hide_store_exception_details(self) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.variable_set_view"
        )
        cases = [
            (
                "list_sets",
                self._make_request(method="GET"),
                {
                    "list_variable_sets": mock.Mock(
                        side_effect=view_module.VariableStoreError("db secret")
                    )
                },
                "Unable to fetch saved variable sets.",
            ),
            (
                "save_set",
                self._make_request(payload={"set_name": "demo", "var_names": ["A"]}),
                {
                    "save_variable_set": mock.Mock(
                        side_effect=view_module.VariableStoreError("db secret")
                    )
                },
                "Could not save variable set.",
            ),
            (
                "load_set",
                types.SimpleNamespace(method="GET", GET={"set_name": "demo"}, body=b""),
                {
                    "list_variable_sets": mock.Mock(return_value=["demo"]),
                    "load_variable_set": mock.Mock(
                        side_effect=view_module.VariableStoreError("db secret")
                    ),
                },
                "Unable to load variable set.",
            ),
            (
                "delete_set",
                self._make_request(payload={"set_name": "demo"}),
                {
                    "delete_variable_set": mock.Mock(
                        side_effect=view_module.VariableStoreError("db secret")
                    )
                },
                "Unable to delete variable set.",
            ),
        ]
        for function_name, request, patches, expected_error in cases:
            with self.subTest(view=function_name):
                with mock.patch.multiple(view_module, **patches):
                    response = getattr(view_module, function_name)(
                        request, conn=mock.Mock()
                    )
                self.assertEqual(500, response["status"])
                self.assertEqual(expected_error, response["payload"]["error"])
                self.assertNotIn("secret", response["payload"]["error"])

    def test_user_data_views_hide_store_exception_details(self) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.user_data_view"
        )
        cases = [
            (
                "delete_api_keys",
                "delete_all_ai_credentials",
                view_module.AiCredentialStoreError("db secret"),
                "Unable to delete AI credentials.",
            ),
            (
                "delete_variable_sets",
                "delete_all_variable_sets",
                view_module.VariableStoreError("db secret"),
                "Unable to delete variable sets.",
            ),
            (
                "delete_all_data",
                "delete_all_user_data",
                view_module.UserDataStoreError("db secret"),
                "Unable to delete user data.",
            ),
        ]
        for function_name, dependency_name, side_effect, expected_error in cases:
            with self.subTest(view=function_name):
                with mock.patch.object(
                    view_module, dependency_name, side_effect=side_effect
                ):
                    response = getattr(view_module, function_name)(
                        self._make_request(), conn=mock.Mock()
                    )
                self.assertEqual(500, response["status"])
                self.assertEqual(expected_error, response["payload"]["error"])

    def test_user_settings_view_hides_store_exception_details(self) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.user_settings_view"
        )

        with mock.patch.object(
            view_module,
            "save_user_settings",
            side_effect=view_module.UserSettingsStoreError("db secret"),
        ):
            response = view_module.save_settings(
                self._make_request(payload={"settings": {"chunk_size": 5}}),
                conn=mock.Mock(),
            )

        self.assertEqual(500, response["status"])
        self.assertEqual("Could not save user settings.", response["payload"]["error"])

    def test_ai_credentials_views_hide_store_exception_details(self) -> None:
        view_module = importlib.import_module(
            "omeroweb_omp_plugin.views.ai_credentials_view"
        )
        cases = [
            (
                "list_credentials",
                self._make_request(method="GET"),
                "list_ai_credentials",
                view_module.AiCredentialStoreError("db secret"),
                "Unable to fetch saved AI credentials.",
            ),
            (
                "save_credentials",
                self._make_request(payload={"provider": "groq", "api_key": "key"}),
                "save_ai_credentials",
                view_module.AiCredentialStoreError("db secret"),
                "Could not save AI credentials.",
            ),
            (
                "list_models",
                types.SimpleNamespace(method="GET", GET={"provider": "groq"}, body=b""),
                "get_ai_credential",
                view_module.AiCredentialStoreError("db secret"),
                "Unable to fetch saved AI credentials.",
            ),
        ]
        for (
            function_name,
            request,
            dependency_name,
            side_effect,
            expected_error,
        ) in cases:
            with self.subTest(view=function_name):
                with (
                    mock.patch.object(
                        view_module,
                        "_perform_connection_test",
                        return_value=(True, "ok"),
                    ),
                    mock.patch.object(
                        view_module,
                        dependency_name,
                        side_effect=side_effect,
                    ),
                ):
                    response = getattr(view_module, function_name)(
                        request, conn=mock.Mock()
                    )
                self.assertEqual(500, response["status"])
                self.assertEqual(expected_error, response["payload"]["error"])

    def test_index_view_hides_ai_store_exception_details(self) -> None:
        view_module = importlib.import_module("omeroweb_omp_plugin.views.index_view")
        request = self._make_form_request(
            post={
                "action": "ai_regex",
                "project": "1",
                "selected_datasets": "10",
                "provider": "groq",
            }
        )
        conn = mock.Mock()
        dataset = types.SimpleNamespace()
        image = types.SimpleNamespace(getName=lambda: "sample_a_01.tif")

        with (
            mock.patch.object(
                view_module, "_collect_project_payload", return_value={"owned": []}
            ),
            mock.patch.object(
                view_module, "_get_accessible_project", return_value=(object(), "owned")
            ),
            mock.patch.object(
                view_module,
                "collect_images_by_selected_datasets",
                return_value=[(dataset, [image])],
            ),
            mock.patch.object(
                view_module,
                "get_ai_credential",
                side_effect=view_module.AiCredentialStoreError("db secret"),
            ),
        ):
            response = view_module.index(request, conn=conn)

        self.assertEqual(500, response["status"])
        self.assertEqual(
            "Unable to fetch saved AI credentials.", response["payload"]["error"]
        )

    def test_index_view_preview_hides_ai_parse_json_error(self) -> None:
        view_module = importlib.import_module("omeroweb_omp_plugin.views.index_view")
        request = self._make_form_request(
            post={
                "project": "1",
                "separator_mode": "ai_parse",
                "selected_datasets": "10",
                "ai_parsed_json": "{bad",
            }
        )
        project = types.SimpleNamespace(getName=lambda: "Demo")

        with (
            mock.patch.object(
                view_module, "_collect_project_payload", return_value={"owned": []}
            ),
            mock.patch.object(
                view_module, "_get_accessible_project", return_value=(project, "owned")
            ),
        ):
            response = view_module.index(request, conn=mock.Mock())

        self.assertEqual(200, response["status"])
        self.assertEqual(
            "Invalid AI parsing data.",
            response["context"]["error_message"],
        )

    def test_index_view_preview_hides_regex_exception_details(self) -> None:
        view_module = importlib.import_module("omeroweb_omp_plugin.views.index_view")
        request = self._make_form_request(
            post={
                "project": "1",
                "separator_mode": "regex",
                "separator": "(",
                "selected_datasets": "10",
            }
        )
        project = types.SimpleNamespace(getName=lambda: "Demo")

        with (
            mock.patch.object(
                view_module, "_collect_project_payload", return_value={"owned": []}
            ),
            mock.patch.object(
                view_module, "_get_accessible_project", return_value=(project, "owned")
            ),
        ):
            response = view_module.index(request, conn=mock.Mock())

        self.assertEqual(200, response["status"])
        self.assertEqual(
            "Invalid regex pattern.",
            response["context"]["error_message"],
        )

    def test_index_view_hides_top_level_exception_details(self) -> None:
        view_module = importlib.import_module("omeroweb_omp_plugin.views.index_view")

        with mock.patch.object(
            view_module,
            "_collect_project_payload",
            side_effect=RuntimeError("secret top-level failure"),
        ):
            response = view_module.index(
                self._make_form_request(method="GET"), conn=mock.Mock()
            )

        self.assertEqual(500, response["status"])
        self.assertEqual("Unexpected error.", response["context"]["error_message"])


if __name__ == "__main__":
    unittest_main()
