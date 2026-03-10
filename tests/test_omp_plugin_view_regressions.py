from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_import_stubs() -> None:
    if "django" not in sys.modules:
        sys.modules["django"] = types.ModuleType("django")

    django_conf = sys.modules.setdefault("django.conf", types.ModuleType("django.conf"))
    django_conf.settings = types.SimpleNamespace()

    django_http = sys.modules.setdefault("django.http", types.ModuleType("django.http"))

    def _json_response(payload=None, status=200, **kwargs):
        return {"payload": payload, "status": status, **kwargs}

    django_http.JsonResponse = _json_response

    csrf_module = sys.modules.setdefault(
        "django.views.decorators.csrf",
        types.ModuleType("django.views.decorators.csrf"),
    )
    csrf_module.csrf_exempt = lambda view: view

    if "omeroweb" not in sys.modules:
        sys.modules["omeroweb"] = types.ModuleType("omeroweb")

    decorators_module = sys.modules.setdefault(
        "omeroweb.decorators",
        types.ModuleType("omeroweb.decorators"),
    )
    decorators_module.login_required = lambda *args, **kwargs: (lambda view: view)

    if "portalocker" not in sys.modules:
        portalocker_module = types.ModuleType("portalocker")

        class Lock:
            def __init__(self, *args, **kwargs):
                pass

            def acquire(self):
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

    omero_rtypes = sys.modules.setdefault("omero.rtypes", types.ModuleType("omero.rtypes"))
    omero_rtypes.rstring = lambda value: value

    if "omero_plugin_common" not in sys.modules:
        sys.modules["omero_plugin_common"] = types.ModuleType("omero_plugin_common")

    env_utils = sys.modules.setdefault(
        "omero_plugin_common.env_utils",
        types.ModuleType("omero_plugin_common.env_utils"),
    )
    env_utils.ENV_FILE_OMEROWEB = ""
    env_utils.get_env = lambda key, env_file=None: "/tmp" if key == "OMERO_WEB_ROOT" else ""

    tmp_utils = sys.modules.setdefault(
        "omero_plugin_common.tmp_utils",
        types.ModuleType("omero_plugin_common.tmp_utils"),
    )
    tmp_utils.get_plugin_tmp_dir = lambda name: Path("/tmp") / f"omp-plugin-{name}"

    request_utils = sys.modules.setdefault(
        "omero_plugin_common.request_utils",
        types.ModuleType("omero_plugin_common.request_utils"),
    )
    request_utils.current_username = lambda request, conn: "stub-user"
    request_utils.load_request_data = lambda request: json.loads(request.body.decode("utf-8"))
    request_utils.parse_json_body = lambda request: (
        json.loads(request.body.decode("utf-8")),
        None,
    )

    logging_utils = sys.modules.setdefault(
        "omero_plugin_common.logging_utils",
        types.ModuleType("omero_plugin_common.logging_utils"),
    )
    logging_utils.sanitize_log_value = lambda value: value


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
    constants_module.OMERO_CLI = "/usr/bin/omero"
    constants_module.CHUNK_SIZE = 5
    constants_module.MAP_NS = "map-ns"
    constants_module.HASH_KEY = "hash-key"
    sys.modules["omeroweb_omp_plugin.constants"] = constants_module

    core_module = types.ModuleType("omeroweb_omp_plugin.services.core")
    core_module.collect_images_in_project = lambda conn, project_id: []
    core_module.find_annotation_link_ids = lambda conn, annotation_id: []
    core_module.find_plugin_annotation_ids = lambda conn, image_id: []
    core_module.find_map_annotation_ids = lambda conn, image_id: []
    core_module.get_id = lambda obj: getattr(obj, "id", obj)
    core_module.load_job = lambda job_id: None
    core_module.save_job = lambda job: True
    core_module._job_lock_path = lambda job_id: f"/tmp/{job_id}.lock"
    core_module.get_text = lambda value: value
    core_module.parse_filename = lambda *args, **kwargs: {}
    core_module.fetch_images_by_ids = lambda conn, image_ids: {}
    core_module.compute_plugin_hash = lambda *args, **kwargs: "hash"
    core_module.delete_existing_annotations = lambda *args, **kwargs: (0, 0, 0)
    core_module.extract_acquisition_metadata = lambda *args, **kwargs: {}
    sys.modules["omeroweb_omp_plugin.services.core"] = core_module

    rate_limit_module = types.ModuleType("omeroweb_omp_plugin.services.rate_limit")
    rate_limit_module.build_rate_limit_message = lambda remaining: f"Rate limited: {remaining}"
    rate_limit_module.check_major_action_rate_limit = lambda request, conn: (True, 0)
    sys.modules["omeroweb_omp_plugin.services.rate_limit"] = rate_limit_module


def _clear_omp_modules() -> None:
    for module_name in list(sys.modules):
        if module_name.startswith("omeroweb_omp_plugin"):
            sys.modules.pop(module_name, None)


class OmpPluginViewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_import_stubs()

    def setUp(self) -> None:
        _clear_omp_modules()
        _install_omp_dependency_stubs()

    def _make_request(self, method: str = "POST", payload: dict | None = None):
        body = json.dumps(payload or {}).encode("utf-8")
        return types.SimpleNamespace(method=method, body=body)

    def test_delete_plugin_view_returns_missing_password_error_without_unbound_local(self) -> None:
        view_module = importlib.import_module("omeroweb_omp_plugin.views.delete_plugin_view")

        request = self._make_request(payload={"project_id": 123})

        response = view_module.delete_plugin_keyvaluepairs(request, conn=mock.Mock())

        self.assertEqual(400, response["status"])
        self.assertEqual(
            "Missing password",
            response["payload"]["error"],
        )

    def test_delete_all_view_returns_missing_password_error_without_unbound_local(self) -> None:
        view_module = importlib.import_module("omeroweb_omp_plugin.views.delete_all_view")

        request = self._make_request(payload={"project_id": 123})

        response = view_module.delete_all_keyvaluepairs(request, conn=mock.Mock())

        self.assertEqual(400, response["status"])
        self.assertEqual(
            "Missing password",
            response["payload"]["error"],
        )

    def test_job_view_password_validator_reports_missing_password(self) -> None:
        job_view = importlib.import_module("omeroweb_omp_plugin.views.job_view")

        conn = mock.Mock()

        valid, error = job_view._validate_user_password(conn, "")

        self.assertFalse(valid)
        self.assertEqual("Missing password", error)


if __name__ == "__main__":
    unittest.main()
