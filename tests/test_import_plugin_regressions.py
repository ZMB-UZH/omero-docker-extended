import importlib.util
import inspect
import os
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
TEST_TMP_ROOT = Path(tempfile.gettempdir()) / "import-plugin-tests"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _test_tmp_path(*parts: str) -> Path:
    return TEST_TMP_ROOT.joinpath(*parts)


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
        django_shortcuts.render = lambda *args, **kwargs: {
            "args": args,
            "kwargs": kwargs,
        }
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
        django_conf = sys.modules.setdefault(
            "django.conf", types.ModuleType("django.conf")
        )
        django_conf.settings = types.SimpleNamespace()

    if "omero" not in sys.modules:
        omero_module = types.ModuleType("omero")
        omero_module.__path__ = []
        omero_gateway = types.ModuleType("omero.gateway")
        omero_gateway.BlitzGateway = type("BlitzGateway", (), {})
        omero_model = types.ModuleType("omero.model")
        omero_model.DatasetI = type("DatasetI", (), {})
        omero_model.ProjectDatasetLinkI = type("ProjectDatasetLinkI", (), {})
        omero_model.ProjectI = type("ProjectI", (), {})
        omero_rtypes = types.ModuleType("omero.rtypes")
        omero_rtypes.rint = lambda value: value
        omero_rtypes.rstring = lambda value: value
        omero_scripts = types.ModuleType("omero.scripts")
        omero_scripts.String = lambda *args, **kwargs: ("String", args, kwargs)
        omero_scripts.client = lambda *args, **kwargs: None
        sys.modules["omero"] = omero_module
        sys.modules["omero.gateway"] = omero_gateway
        sys.modules["omero.model"] = omero_model
        sys.modules["omero.rtypes"] = omero_rtypes
        sys.modules["omero.scripts"] = omero_scripts
        omero_module.scripts = omero_scripts

    if "omeroweb.decorators" not in sys.modules:
        omeroweb_module = types.ModuleType("omeroweb")
        omeroweb_decorators = types.ModuleType("omeroweb.decorators")
        omeroweb_decorators.login_required = lambda *args, **kwargs: lambda view: view
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
        portalocker_module.exceptions = types.SimpleNamespace(
            LockException=LockException
        )
        sys.modules["portalocker"] = portalocker_module

    if "omero_plugin_common.logging_utils" not in sys.modules:
        common_module = types.ModuleType("omero_plugin_common")
        logging_utils = types.ModuleType("omero_plugin_common.logging_utils")
        logging_utils.sanitize_log_value = lambda value: value
        logging_utils.sanitized_exc_info = lambda exc: None
        tmp_utils = types.ModuleType("omero_plugin_common.tmp_utils")
        tmp_utils.get_plugin_tmp_dir = lambda name: _test_tmp_path(
            f"import-plugin-{name}"
        )
        tmp_cleanup = types.ModuleType("omero_plugin_common.tmp_cleanup")
        tmp_cleanup.safe_mark_path_for_deferred_cleanup = lambda *args, **kwargs: True
        tmp_cleanup.safe_remove_job_data = lambda *args, **kwargs: None
        request_utils = types.ModuleType("omero_plugin_common.request_utils")
        request_utils.current_username = lambda request, conn: "stub-user"
        request_utils.load_request_data = lambda request: {}
        request_utils.parse_json_body = lambda request: ({}, None)
        env_utils = types.ModuleType("omero_plugin_common.env_utils")
        env_utils.ENV_FILE_OMEROWEB = ""
        env_utils.get_env = lambda key, env_file=None: os.environ.get(key, "")
        env_utils.get_bool_env = lambda key, default=False, env_file=None: (
            (str(os.environ.get(key, "")).strip().lower() in {"1", "true", "yes", "on"})
            if key in os.environ
            else default
        )
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
        data_store.save_special_method_settings = (
            lambda username, method_key, settings: None
        )
        data_store.load_special_method_settings = lambda username, method_key: {}
        sys.modules["omeroweb_import.services.data_store"] = data_store


_install_import_stubs()

from omeroweb_import.views import core_functions
from omeroweb_import.views import index_view


def _load_manage_zarr_script_module():
    module_path = (
        REPO_ROOT
        / "omeroweb_import"
        / "omero_scripts"
        / "Manage_Zarr_ManagedRepository.py"
    )
    spec = importlib.util.spec_from_file_location(
        "manage_zarr_managed_repository_test_module",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImportPluginRegressionTests(TestCase):
    def _json_status_and_payload(self, response):
        if isinstance(response, dict):
            return response["status"], response["payload"]
        return response.status_code, json.loads(response.content)

    def test_normalize_upload_relative_path_rejects_overlong_component_by_utf8_bytes(
        self,
    ):
        raw_name = f"{'ä' * 130}.tif"

        rel_path, error = core_functions._normalize_upload_relative_path(raw_name)

        self.assertIsNone(rel_path)
        self.assertIn("Filename is too long", error)

    def test_get_text_falls_back_to_private_rstring_value(self):
        value_obj = types.SimpleNamespace(
            val=None, _val="/managed/path/sample.ome.zarr"
        )

        text = core_functions._get_text(value_obj)

        self.assertEqual("/managed/path/sample.ome.zarr", text)

    def test_external_info_text_uses_getter_when_attribute_is_unloaded(self):
        external_info = types.SimpleNamespace(
            lsid=types.SimpleNamespace(val=None, _val=None),
            getLsid=lambda: types.SimpleNamespace(
                val=None, _val="/managed/path/from-getter.ome.zarr"
            ),
        )

        text = core_functions._external_info_text(external_info, "lsid", "getLsid")

        self.assertEqual("/managed/path/from-getter.ome.zarr", text)

    def test_query_image_external_info_reads_projection_values(self):
        params_seen = {}
        fake_query = mock.Mock()
        fake_query.projection.return_value = [
            [
                types.SimpleNamespace(
                    val=None, _val="/managed/path/from-query.ome.zarr"
                ),
                types.SimpleNamespace(
                    val=None, _val="com.glencoesoftware.ngff:multiscales"
                ),
            ]
        ]
        fake_conn = types.SimpleNamespace(
            getQueryService=lambda: fake_query,
            SERVICE_OPTS=object(),
        )
        with mock.patch.object(
            core_functions.omero,
            "sys",
            types.SimpleNamespace(
                ParametersI=lambda: types.SimpleNamespace(
                    addId=lambda value: params_seen.setdefault("id", value)
                )
            ),
            create=True,
        ):
            lsid, entity_type = core_functions._query_image_external_info(fake_conn, 42)

        self.assertEqual(42, params_seen["id"])
        self.assertEqual("/managed/path/from-query.ome.zarr", lsid)
        self.assertEqual("com.glencoesoftware.ngff:multiscales", entity_type)

    def test_native_zarr_image_relative_path_from_lsid_handles_root_and_series(self):
        managed_root = Path("/OMERO/ManagedRepository/user/test/sample.ome.zarr")

        root_relative = core_functions._native_zarr_image_relative_path_from_lsid(
            managed_root,
            str(managed_root),
        )
        series_relative = core_functions._native_zarr_image_relative_path_from_lsid(
            managed_root,
            str(managed_root / "1"),
        )

        self.assertIsNone(root_relative)
        self.assertEqual("1", series_relative)

    def test_finalize_imported_zarr_image_metadata_persists_source_pixel_sizes(self):
        class _FakeUnit:
            def __init__(self, name):
                self.name = name

        class _FakeLength:
            def __init__(self, value, unit_name):
                self._value = float(value)
                self._unit = _FakeUnit(unit_name)

            def getValue(self):
                return self._value

            def getUnit(self):
                return self._unit

        class _FakePixelsModel:
            def __init__(self):
                self._x = None
                self._y = None
                self._z = None

            def setPhysicalSizeX(self, value):
                self._x = value

            def setPhysicalSizeY(self, value):
                self._y = value

            def setPhysicalSizeZ(self, value):
                self._z = value

        class _FakePixelsWrapper:
            def __init__(self, model):
                self._obj = model

            def getPhysicalSizeX(self):
                return self._obj._x

            def getPhysicalSizeY(self):
                return self._obj._y

            def getPhysicalSizeZ(self):
                return self._obj._z

        class _FakeImage:
            def __init__(self, image_id, pixels_wrapper):
                self._image_id = image_id
                self._pixels_wrapper = pixels_wrapper

            def getId(self):
                return self._image_id

            def getPrimaryPixels(self):
                return self._pixels_wrapper

        class _FakeUpdateService:
            def __init__(self):
                self.saved = []

            def saveAndReturnObject(self, obj):
                self.saved.append(obj)
                return obj

        class _FakeConn:
            def __init__(self, image):
                self._image = image
                self._update_service = _FakeUpdateService()
                self.SERVICE_OPTS = types.SimpleNamespace(
                    setOmeroGroup=lambda value: setattr(self, "_group", value)
                )
                self.closed = False

            def getObject(self, obj_type, image_id):
                self._last_lookup = (obj_type, image_id)
                return self._image

            def getUpdateService(self):
                return self._update_service

            def close(self):
                self.closed = True

        class _FakeAdminConn:
            def __init__(self, conn):
                self._conn = conn
                self.closed = False

            def suConn(self, username):
                self._username = username
                return self._conn

            def close(self):
                self.closed = True

        pixels_model = _FakePixelsModel()
        pixels_wrapper = _FakePixelsWrapper(pixels_model)
        image = _FakeImage(51, pixels_wrapper)
        fake_conn = _FakeConn(image)
        fake_admin_conn = _FakeAdminConn(fake_conn)
        expected_sizes = {
            "x": _FakeLength(0.5, "MICROMETER"),
            "y": _FakeLength(0.75, "MICROMETER"),
            "z": _FakeLength(1.25, "MICROMETER"),
        }

        with (
            mock.patch.object(
                core_functions,
                "_open_admin_connection",
                return_value=fake_admin_conn,
            ),
            mock.patch.object(
                core_functions,
                "_query_image_external_info",
                return_value=(
                    "/OMERO/ManagedRepository/user/test/sample.ome.zarr/0",
                    "com.glencoesoftware.ngff:multiscales",
                ),
            ),
            mock.patch.object(
                core_functions,
                "_runtime_native_zarr_physical_sizes",
                return_value=(expected_sizes, None),
            ),
        ):
            ok, errors = core_functions._finalize_imported_zarr_image_metadata(
                "test",
                "omeroserver",
                4064,
                ["51"],
                managed_zarr=Path("/OMERO/ManagedRepository/user/test/sample.ome.zarr"),
                group_name="private",
            )

        self.assertTrue(ok)
        self.assertEqual([], errors)
        self.assertEqual(
            core_functions._native_zarr_length_signature(expected_sizes["x"]),
            core_functions._native_zarr_length_signature(
                pixels_wrapper.getPhysicalSizeX()
            ),
        )
        self.assertEqual(
            core_functions._native_zarr_length_signature(expected_sizes["y"]),
            core_functions._native_zarr_length_signature(
                pixels_wrapper.getPhysicalSizeY()
            ),
        )
        self.assertEqual(
            core_functions._native_zarr_length_signature(expected_sizes["z"]),
            core_functions._native_zarr_length_signature(
                pixels_wrapper.getPhysicalSizeZ()
            ),
        )
        self.assertEqual([pixels_model], fake_conn.getUpdateService().saved)
        self.assertTrue(fake_conn.closed)
        self.assertTrue(fake_admin_conn.closed)

    def test_runtime_native_zarr_physical_sizes_normalizes_ngff_unit_symbols(self):
        class _FakeUnit:
            def __init__(self, name):
                self.name = name

        class _FakeLength:
            def __init__(self, value, unit):
                self._value = float(value)
                self._unit = unit

            def getValue(self):
                return self._value

            def getUnit(self):
                return self._unit

        unit_names = (
            "METER",
            "MICROMETER",
            "NANOMETER",
            "PIXEL",
        )
        fake_units = {name: _FakeUnit(name) for name in unit_names}

        class _FakeUnitsLength:
            _enumerators = {
                index: fake_units[name] for index, name in enumerate(unit_names)
            }

        for name, unit in fake_units.items():
            setattr(_FakeUnitsLength, name, unit)

        fake_enums_module = types.ModuleType("omero.model.enums")
        fake_enums_module.UnitsLength = _FakeUnitsLength

        core_functions._units_length_for_name.cache_clear()
        core_functions._units_length_by_normalized_name.cache_clear()
        core_functions._units_length_symbol_aliases.cache_clear()
        self.addCleanup(core_functions._units_length_for_name.cache_clear)
        self.addCleanup(core_functions._units_length_by_normalized_name.cache_clear)
        self.addCleanup(core_functions._units_length_symbol_aliases.cache_clear)

        with (
            mock.patch.dict(
                sys.modules,
                {"omero.model.enums": fake_enums_module},
            ),
            mock.patch.object(
                sys.modules["omero.model"],
                "LengthI",
                _FakeLength,
                create=True,
            ),
            mock.patch.object(
                core_functions,
                "inspect_ome_zarr_image",
                return_value=types.SimpleNamespace(
                    recognized=True,
                    support_error=None,
                    physical_sizes={
                        "x": ("10.0", "nm"),
                        "y": ("5.0", "µm"),
                        "z": ("2.5", "um"),
                    },
                ),
            ),
        ):
            sizes, error = core_functions._runtime_native_zarr_physical_sizes(
                Path("/OMERO/ManagedRepository/user/test/sample.ome.zarr"),
                "0",
            )

        self.assertIsNone(error)
        self.assertEqual(
            (10.0, "nanometer"),
            core_functions._native_zarr_length_signature(sizes["x"]),
        )
        self.assertEqual(
            (5.0, "micrometer"),
            core_functions._native_zarr_length_signature(sizes["y"]),
        )
        self.assertEqual(
            (2.5, "micrometer"),
            core_functions._native_zarr_length_signature(sizes["z"]),
        )

    def test_validate_staged_target_path_rejects_excessive_target_length(self):
        upload_root = _test_tmp_path("upload-root")
        staged_path = "_staged/job/" + ("a" * 5000) + ".tif"

        error = core_functions._validate_staged_target_path(upload_root, staged_path)

        self.assertIn("File path is too long", error)

    def test_resolve_staged_target_path_rejects_traversal(self):
        upload_root = _test_tmp_path("upload-root")

        target, error = core_functions._resolve_staged_target_path(
            upload_root, "../escape.bin"
        )

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
            with mock.patch.object(
                core_functions, "_get_jobs_root", return_value=jobs_root
            ):
                self.assertTrue(core_functions._save_job(dict(job)))

                def increment_job():
                    for _ in range(25):
                        updated = core_functions._robust_update_job(
                            job_id,
                            lambda job_dict: {
                                **job_dict,
                                "counter": job_dict.get("counter", 0) + 1,
                            },
                        )
                        self.assertIsNotNone(updated)

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(increment_job) for _ in range(4)]
                    for future in futures:
                        future.result()

                loaded = core_functions._load_job(job_id)
                self.assertIsNotNone(loaded)
                self.assertEqual(100, loaded["counter"])

    def test_open_session_connection_detaches_joined_session_before_wrapper_teardown(
        self,
    ):
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

        with (
            mock.patch.object(
                core_functions.omero,
                "client",
                side_effect=lambda host, port: FakeClient(host=host, port=port),
                create=True,
            ),
            mock.patch.object(core_functions, "BlitzGateway", FakeGateway),
        ):
            conn = core_functions._open_session_connection(
                "session-key", "omeroserver", 4064
            )

        self.assertIsInstance(conn, FakeGateway)
        self.assertEqual(
            {"host": "omeroserver", "port": 4064, "session_key": "session-key"},
            client_calls,
        )
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

        self.assertEqual(
            ["51", "52"], sorted(core_functions._extract_imported_object_ids(output))
        )

    def test_sanitize_cli_output_for_logging_redacts_uuid_tokens(self):
        raw = "Bad session key. Cannot join 12345678-1234-1234-1234-123456789abc on omeroserver:4064."

        sanitized = core_functions._sanitize_cli_output_for_logging(raw)

        self.assertIn("Cannot join ***", sanitized)
        self.assertNotIn("12345678-1234-1234-1234-123456789abc", sanitized)

    def test_extract_script_outputs_parses_named_lines(self):
        outputs = core_functions._extract_script_outputs(
            "\n".join(
                [
                    "Managed_Path=/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr",
                    "* Message=staged",
                    "ignored line",
                ]
            )
        )

        self.assertEqual(
            {
                "Managed_Path": "/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr",
                "Message": "staged",
            },
            outputs,
        )

    def test_find_script_id_by_name_prefers_import_scripts_path(self):
        def script(name, path, sid):
            return types.SimpleNamespace(
                name=types.SimpleNamespace(val=name),
                path=types.SimpleNamespace(val=path),
                id=types.SimpleNamespace(val=sid),
            )

        scripts = [
            script(
                "Manage_Zarr_ManagedRepository.py",
                "/OMERO/other/Manage_Zarr_ManagedRepository.py",
                11,
            ),
            script(
                "Manage_Zarr_ManagedRepository.py",
                "/OMERO/omero/import_scripts/Manage_Zarr_ManagedRepository.py",
                37,
            ),
            script(
                "Manage_Zarr_ManagedRepository.py",
                "/OMERO/omero/import_scripts/Manage_Zarr_ManagedRepository.py",
                18,
            ),
        ]
        conn = types.SimpleNamespace(
            getScriptService=lambda: types.SimpleNamespace(getScripts=lambda: scripts),
            c=types.SimpleNamespace(
                sf=types.SimpleNamespace(getScriptService=lambda: None)
            ),
        )

        script_id = core_functions._find_script_id_by_name(
            conn,
            "Manage_Zarr_ManagedRepository.py",
            preferred_path_fragment="omero/import_scripts",
        )

        self.assertEqual(37, script_id)

    def test_run_zarr_managed_repo_script_launches_expected_cli_command(self):
        completed = subprocess.CompletedProcess(
            args=["omero"],
            returncode=0,
            stdout="\n".join(
                [
                    "Managed_Path=/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr",
                    "Message=staged",
                ]
            ),
            stderr="",
        )
        admin_conn = types.SimpleNamespace(close=lambda: None)

        with (
            mock.patch.object(
                core_functions,
                "_open_admin_connection",
                return_value=admin_conn,
            ),
            mock.patch.object(
                core_functions,
                "_find_script_id_by_name",
                return_value=42,
            ),
            mock.patch.object(
                core_functions,
                "_get_import_timeout_seconds",
                return_value=120,
            ),
            mock.patch.object(
                core_functions,
                "_get_root_password",
                return_value="root-secret",
            ),
            mock.patch.object(
                core_functions,
                "_build_cli_env",
                return_value={"TEST_ENV": "1"},
            ),
            mock.patch.object(
                core_functions.subprocess,
                "run",
                return_value=completed,
            ) as run_mock,
        ):
            ok, outputs, message = core_functions._run_zarr_managed_repo_script(
                "stage",
                "omeroserver",
                4064,
                username="test",
                group_name="users_private",
                source_path=_test_tmp_path("job", "sample.zarr"),
            )

        self.assertTrue(ok)
        self.assertEqual(
            "/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr",
            outputs["Managed_Path"],
        )
        self.assertEqual("staged", message)

        command = run_mock.call_args.args[0]
        env = run_mock.call_args.kwargs["env"]
        self.assertEqual(core_functions.OMERO_CLI, command[0])
        self.assertEqual(
            [
                "-q",
                "-s",
                "omeroserver",
                "-p",
                "4064",
                "-u",
                "root",
                "script",
                "launch",
                "42",
            ],
            command[1:11],
        )
        self.assertEqual("root-secret", env["OMERO_PASSWORD"])
        self.assertEqual("stage", command[11].split("=", 1)[1])
        self.assertEqual("users_private", command[12].split("=", 1)[1])
        self.assertEqual("test", command[13].split("=", 1)[1])
        self.assertEqual(
            str(_test_tmp_path("job", "sample.zarr")),
            command[14].split("=", 1)[1],
        )

    def test_run_zarr_managed_repo_script_retries_when_no_processor_is_temporarily_unavailable(
        self,
    ):
        admin_conn = types.SimpleNamespace(close=lambda: None)
        results = [
            subprocess.CompletedProcess(
                args=["omero"],
                returncode=1,
                stdout="",
                stderr="omero.NoProcessorAvailable: No processor available! [1 response(s)]",
            ),
            subprocess.CompletedProcess(
                args=["omero"],
                returncode=0,
                stdout="Managed_Path=/OMERO/ManagedRepository/users_private/test/retried.zarr\nMessage=staged",
                stderr="",
            ),
        ]

        with (
            mock.patch.object(
                core_functions,
                "_open_admin_connection",
                return_value=admin_conn,
            ),
            mock.patch.object(
                core_functions,
                "_find_script_id_by_name",
                return_value=42,
            ),
            mock.patch.object(
                core_functions,
                "_get_root_password",
                return_value="root-secret",
            ),
            mock.patch.object(
                core_functions,
                "_build_cli_env",
                return_value={},
            ),
            mock.patch.object(
                core_functions,
                "_get_import_timeout_seconds",
                return_value=120,
            ),
            mock.patch.object(
                core_functions,
                "_get_script_start_timeout_seconds",
                return_value=60,
            ),
            mock.patch.object(
                core_functions,
                "_get_script_start_retry_seconds",
                return_value=1,
            ),
            mock.patch.object(
                core_functions.time,
                "sleep",
                return_value=None,
            ) as sleep_mock,
            mock.patch.object(
                core_functions.subprocess,
                "run",
                side_effect=results,
            ) as run_mock,
        ):
            ok, outputs, message = core_functions._run_zarr_managed_repo_script(
                "stage",
                "omeroserver",
                4064,
                username="test",
                group_name="users_private",
                source_path=_test_tmp_path("job", "sample.zarr"),
            )

        self.assertTrue(ok)
        self.assertEqual(
            "/OMERO/ManagedRepository/users_private/test/retried.zarr",
            outputs["Managed_Path"],
        )
        self.assertEqual("staged", message)
        self.assertEqual(2, run_mock.call_count)
        sleep_mock.assert_called_once_with(1)

    def test_import_zarr_via_cli_cleans_managed_path_when_no_objects_are_created(self):
        managed_path = Path(
            "/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr"
        )
        shared_source = _test_tmp_path("managed-zarr-transfer", "token", "sample.zarr")
        shared_parent = shared_source.parent

        with (
            mock.patch.object(
                core_functions,
                "_prepare_server_readable_zarr_source",
                return_value=(shared_source, shared_parent, None),
            ),
            mock.patch.object(
                core_functions,
                "_run_zarr_managed_repo_script",
                return_value=(True, {"Managed_Path": str(managed_path)}, "staged"),
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_shared_zarr_transfer",
            ) as cleanup_transfer_mock,
            mock.patch.object(
                core_functions,
                "_build_omero_cli_command",
                return_value=["omero", "zarr", "import"],
            ),
            mock.patch.object(
                core_functions,
                "_build_cli_env",
                return_value={"TEST_ENV": "1"},
            ),
            mock.patch.object(
                core_functions.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["omero", "zarr", "import"],
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ),
            mock.patch.object(
                core_functions,
                "_verify_zarr_import_via_api",
                return_value=[],
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_managed_zarr_path",
            ) as cleanup_mock,
        ):
            result = core_functions._import_zarr_via_cli(
                file_path=_test_tmp_path("job", "sample.zarr"),
                session_key="session-key",
                host="omeroserver",
                port=4064,
                dataset_id=7,
                import_name="sample.zarr",
                rel_path="sample.zarr",
                entry={"index": 3},
                cleanup_staged_paths=["_staged/sample.zarr"],
                covered_indexes=[3],
                covered_relative_paths=["sample.zarr/.zattrs"],
                group_id=4,
                progress_job=None,
                username="test",
                group_name="users_private",
                native_plan=core_functions._NativeZarrImportPlan(
                    kind=core_functions._NATIVE_ZARR_KIND_OME_ZARR,
                    compatibility_details="OME-Zarr image detected by ome-zarr",
                ),
            )

        self.assertEqual("error", result["status"])
        self.assertIn("no images were created", result["entry_error"].lower())
        cleanup_transfer_mock.assert_called_once_with(shared_parent)
        cleanup_mock.assert_called_once_with(
            "omeroserver",
            4064,
            username="test",
            group_name="users_private",
            managed_path=managed_path,
        )

    def test_import_zarr_via_cli_rolls_back_when_render_verification_fails(self):
        managed_path = Path(
            "/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr"
        )
        shared_source = _test_tmp_path("managed-zarr-transfer", "token", "sample.zarr")
        shared_parent = shared_source.parent

        with (
            mock.patch.object(
                core_functions,
                "_prepare_server_readable_zarr_source",
                return_value=(shared_source, shared_parent, None),
            ),
            mock.patch.object(
                core_functions,
                "_run_zarr_managed_repo_script",
                return_value=(True, {"Managed_Path": str(managed_path)}, "staged"),
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_shared_zarr_transfer",
            ),
            mock.patch.object(
                core_functions,
                "_build_omero_cli_command",
                return_value=["omero", "zarr", "import"],
            ),
            mock.patch.object(
                core_functions,
                "_build_cli_env",
                return_value={"TEST_ENV": "1"},
            ),
            mock.patch.object(
                core_functions.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["omero", "zarr", "import"],
                    returncode=0,
                    stdout="Created Image 51\n",
                    stderr="",
                ),
            ),
            mock.patch.object(
                core_functions,
                "_verify_zarr_import_via_api",
                return_value=["51"],
            ),
            mock.patch.object(
                core_functions,
                "_finalize_imported_zarr_image_metadata",
                return_value=(True, []),
            ),
            mock.patch.object(
                core_functions,
                "_verify_imported_zarr_images_renderable",
                return_value=(False, ["thumbnail failed"]),
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_imported_images",
            ) as cleanup_images_mock,
            mock.patch.object(
                core_functions,
                "_cleanup_managed_zarr_path",
            ) as cleanup_managed_mock,
        ):
            result = core_functions._import_zarr_via_cli(
                file_path=_test_tmp_path("job", "sample.zarr"),
                session_key="session-key",
                host="omeroserver",
                port=4064,
                dataset_id=7,
                import_name="sample.zarr",
                rel_path="sample.zarr",
                entry={"index": 3},
                cleanup_staged_paths=["_staged/sample.zarr"],
                covered_indexes=[3],
                covered_relative_paths=["sample.zarr/.zattrs"],
                group_id=4,
                progress_job=None,
                username="test",
                group_name="users_private",
                native_plan=core_functions._NativeZarrImportPlan(
                    kind=core_functions._NATIVE_ZARR_KIND_OME_ZARR,
                    compatibility_details="OME-Zarr image detected by ome-zarr",
                ),
            )

        self.assertEqual("error", result["status"])
        self.assertIn("render verification", result["entry_error"].lower())
        cleanup_images_mock.assert_called_once_with("omeroserver", 4064, ["51"])
        cleanup_managed_mock.assert_called_once_with(
            "omeroserver",
            4064,
            username="test",
            group_name="users_private",
            managed_path=managed_path,
        )

    def test_import_zarr_via_cli_rolls_back_when_metadata_finalization_fails(self):
        managed_path = Path(
            "/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr"
        )
        shared_source = _test_tmp_path("managed-zarr-transfer", "token", "sample.zarr")
        shared_parent = shared_source.parent

        with (
            mock.patch.object(
                core_functions,
                "_prepare_server_readable_zarr_source",
                return_value=(shared_source, shared_parent, None),
            ),
            mock.patch.object(
                core_functions,
                "_run_zarr_managed_repo_script",
                return_value=(True, {"Managed_Path": str(managed_path)}, "staged"),
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_shared_zarr_transfer",
            ),
            mock.patch.object(
                core_functions,
                "_build_omero_cli_command",
                return_value=["omero", "zarr", "import"],
            ),
            mock.patch.object(
                core_functions,
                "_build_cli_env",
                return_value={"TEST_ENV": "1"},
            ),
            mock.patch.object(
                core_functions.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["omero", "zarr", "import"],
                    returncode=0,
                    stdout="Created Image 61\n",
                    stderr="",
                ),
            ),
            mock.patch.object(
                core_functions,
                "_verify_zarr_import_via_api",
                return_value=["61"],
            ),
            mock.patch.object(
                core_functions,
                "_finalize_imported_zarr_image_metadata",
                return_value=(False, ["physical size save failed"]),
            ),
            mock.patch.object(
                core_functions,
                "_verify_imported_zarr_images_renderable",
            ) as render_verify_mock,
            mock.patch.object(
                core_functions,
                "_cleanup_imported_images",
            ) as cleanup_images_mock,
            mock.patch.object(
                core_functions,
                "_cleanup_managed_zarr_path",
            ) as cleanup_managed_mock,
        ):
            result = core_functions._import_zarr_via_cli(
                file_path=_test_tmp_path("job", "sample.zarr"),
                session_key="session-key",
                host="omeroserver",
                port=4064,
                dataset_id=7,
                import_name="sample.zarr",
                rel_path="sample.zarr",
                entry={"index": 3},
                cleanup_staged_paths=["_staged/sample.zarr"],
                covered_indexes=[3],
                covered_relative_paths=["sample.zarr/.zattrs"],
                group_id=4,
                progress_job=None,
                username="test",
                group_name="users_private",
                native_plan=core_functions._NativeZarrImportPlan(
                    kind=core_functions._NATIVE_ZARR_KIND_OME_ZARR,
                    compatibility_details="OME-Zarr image detected by ome-zarr",
                ),
            )

        self.assertEqual("error", result["status"])
        self.assertIn("metadata finalization", result["entry_error"].lower())
        cleanup_images_mock.assert_called_once_with("omeroserver", 4064, ["61"])
        cleanup_managed_mock.assert_called_once_with(
            "omeroserver",
            4064,
            username="test",
            group_name="users_private",
            managed_path=managed_path,
        )
        render_verify_mock.assert_not_called()

    def test_import_zarr_via_cli_accepts_only_renderable_images(self):
        managed_path = Path(
            "/OMERO/ManagedRepository/users_private/test/2026-03-22/09-51-15/sample.zarr"
        )
        shared_source = _test_tmp_path("managed-zarr-transfer", "token", "sample.zarr")
        shared_parent = shared_source.parent

        with (
            mock.patch.object(
                core_functions,
                "_prepare_server_readable_zarr_source",
                return_value=(shared_source, shared_parent, None),
            ),
            mock.patch.object(
                core_functions,
                "_run_zarr_managed_repo_script",
                return_value=(True, {"Managed_Path": str(managed_path)}, "staged"),
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_shared_zarr_transfer",
            ),
            mock.patch.object(
                core_functions,
                "_build_omero_cli_command",
                return_value=["omero", "zarr", "import"],
            ),
            mock.patch.object(
                core_functions,
                "_build_cli_env",
                return_value={"TEST_ENV": "1"},
            ),
            mock.patch.object(
                core_functions.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["omero", "zarr", "import"],
                    returncode=0,
                    stdout="Created Image 52\n",
                    stderr="",
                ),
            ),
            mock.patch.object(
                core_functions,
                "_verify_zarr_import_via_api",
                return_value=["52"],
            ),
            mock.patch.object(
                core_functions,
                "_finalize_imported_zarr_image_metadata",
                return_value=(True, []),
            ),
            mock.patch.object(
                core_functions,
                "_verify_imported_zarr_images_renderable",
                return_value=(True, []),
            ),
            mock.patch.object(
                core_functions,
                "_cleanup_imported_images",
            ) as cleanup_images_mock,
            mock.patch.object(
                core_functions,
                "_cleanup_managed_zarr_path",
            ) as cleanup_managed_mock,
        ):
            result = core_functions._import_zarr_via_cli(
                file_path=_test_tmp_path("job", "sample.zarr"),
                session_key="session-key",
                host="omeroserver",
                port=4064,
                dataset_id=7,
                import_name="sample.zarr",
                rel_path="sample.zarr",
                entry={"index": 3},
                cleanup_staged_paths=["_staged/sample.zarr"],
                covered_indexes=[3],
                covered_relative_paths=["sample.zarr/.zattrs"],
                group_id=4,
                progress_job=None,
                username="test",
                group_name="users_private",
                native_plan=core_functions._NativeZarrImportPlan(
                    kind=core_functions._NATIVE_ZARR_KIND_OME_ZARR,
                    compatibility_details="OME-Zarr image detected by ome-zarr",
                ),
            )

        self.assertEqual("imported", result["status"])
        self.assertEqual(managed_path, result["file_path"])
        cleanup_images_mock.assert_not_called()
        cleanup_managed_mock.assert_not_called()

    def test_prepare_server_readable_zarr_source_copies_into_shared_transfer_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            source = tmp_root / "upload" / "sample.zarr"
            (source / "0").mkdir(parents=True)
            (source / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "axes": [{"name": "y"}, {"name": "x"}],
                                "datasets": [
                                    {
                                        "path": "0",
                                        "coordinateTransformations": [
                                            {"type": "scale", "scale": [1.0, 1.0]}
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source / "0" / ".zarray").write_text(
                '{"shape":[1,1],"dtype":"<u2"}', encoding="utf-8"
            )
            (source / "0" / "0.0").write_bytes(b"abc")
            transfer_root = tmp_root / "shared-transfer"
            transfer_root.mkdir()

            with (
                mock.patch.object(
                    core_functions, "get_plugin_tmp_dir", return_value=transfer_root
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=True,
                        support_error=None,
                        compatibility_details="OME-Zarr image detected by ome-zarr",
                    ),
                ),
                mock.patch.object(
                    core_functions, "normalize_native_ome_zarr_copy", return_value=None
                ),
            ):
                shared_source, shared_parent, error = (
                    core_functions._prepare_server_readable_zarr_source(source)
                )

            self.assertIsNone(error)
            self.assertIsNotNone(shared_source)
            self.assertIsNotNone(shared_parent)
            self.assertTrue(shared_source.is_dir())
            self.assertEqual("sample.zarr", shared_source.name)
            self.assertIn(
                '"multiscales"', (shared_source / ".zattrs").read_text(encoding="utf-8")
            )
            self.assertEqual(b"abc", (shared_source / "0" / "0.0").read_bytes())
            self.assertEqual(0o711, shared_parent.stat().st_mode & 0o777)
            self.assertEqual(0o755, shared_source.stat().st_mode & 0o777)
            self.assertEqual(
                0o644, (shared_source / "0" / "0.0").stat().st_mode & 0o777
            )

    def test_prepare_server_readable_zarr_source_preserves_multiscale_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            source = tmp_root / "upload" / "sample.zarr"
            transfer_root = tmp_root / "shared-transfer"
            transfer_root.mkdir()

            source.mkdir(parents=True)
            (source / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
            (source / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "version": "0.4",
                                "axes": [{"name": "y"}, {"name": "x"}],
                                "datasets": [
                                    {
                                        "path": "s0",
                                        "coordinateTransformations": [
                                            {"type": "scale", "scale": [1.0, 1.0]}
                                        ],
                                    },
                                    {
                                        "path": "s1",
                                        "coordinateTransformations": [
                                            {"type": "scale", "scale": [2.0, 2.0]}
                                        ],
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            for name in ("s0", "s1"):
                subdir = source / name
                subdir.mkdir()
                (subdir / ".zarray").write_text(
                    '{"shape":[4,4],"dtype":"<u2"}', encoding="utf-8"
                )
                (subdir / "0.0").write_bytes(b"chunk")

            with (
                mock.patch.object(
                    core_functions, "get_plugin_tmp_dir", return_value=transfer_root
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=True,
                        support_error=None,
                        compatibility_details="OME-Zarr image detected by ome-zarr",
                    ),
                ),
                mock.patch.object(
                    core_functions, "normalize_native_ome_zarr_copy", return_value=None
                ),
            ):
                shared_source, shared_parent, error = (
                    core_functions._prepare_server_readable_zarr_source(source)
                )

            self.assertIsNone(error)
            self.assertIsNotNone(shared_source)
            self.assertTrue(
                (source / "s1").exists(), "original upload must not be modified"
            )
            self.assertTrue(
                (shared_source / "s1").exists(),
                "shared copy must preserve native levels",
            )
            with open(shared_source / ".zattrs", encoding="utf-8") as fh:
                attrs = json.load(fh)
            self.assertEqual(
                ["s0", "s1"], [d["path"] for d in attrs["multiscales"][0]["datasets"]]
            )

    def test_check_import_compatibility_accepts_incompatible_ome_zarr_via_ome_zarr_support(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            zarr_dir = Path(tmpdir) / "image.ome.zarr"
            zarr_dir.mkdir()
            (zarr_dir / "s0").mkdir()
            (zarr_dir / "s0" / ".zarray").write_text(
                '{"zarr_format": 2, "shape":[1,1],"chunks":[1,1],"dtype":"|u1","compressor":null,"fill_value":0,"filters":null,"order":"C"}',
                encoding="utf-8",
            )
            (zarr_dir / "s0" / "0").write_bytes(b"\x00")
            (zarr_dir / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "version": "0.4",
                                "axes": [{"name": "y"}, {"name": "x"}],
                                "datasets": [
                                    {
                                        "path": "s0",
                                        "coordinateTransformations": [
                                            {"type": "scale", "scale": [1.0, 1.0]}
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            scan_result = subprocess.CompletedProcess(
                args=["omero", "import", "-f"],
                returncode=0,
                stdout="",
                stderr="unsupported",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {core_functions.NATIVE_ZARR_IMPORT_ENABLED_ENV: "true"},
                ),
                mock.patch.object(
                    core_functions, "_run_local_import_scan", return_value=scan_result
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=True,
                        support_error=None,
                        compatibility_details="OME-Zarr image detected by ome-zarr",
                    ),
                ),
            ):
                result = core_functions._check_import_compatibility(
                    "session-key",
                    "omeroserver",
                    4064,
                    zarr_dir,
                    dataset_id=None,
                    relative_path="image.ome.zarr",
                )

        self.assertEqual("compatible", result["status"])
        self.assertIn("ome-zarr", result["details"].lower())

    def test_check_import_compatibility_uses_bioformats_when_scan_finds_groups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zarr_dir = Path(tmpdir) / "bf2raw.ome.zarr"
            series_dir = zarr_dir / "0"
            array_dir = series_dir / "0"
            array_dir.mkdir(parents=True)
            (array_dir / ".zarray").write_text(
                '{"shape":[1,1],"dtype":"<u2"}',
                encoding="utf-8",
            )
            (zarr_dir / ".zattrs").write_text(
                json.dumps({"bioformats2raw.layout": 3}),
                encoding="utf-8",
            )
            (series_dir / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "version": "0.4",
                                "axes": [{"name": "y"}, {"name": "x"}],
                                "datasets": [
                                    {
                                        "path": "0",
                                        "coordinateTransformations": [
                                            {"type": "scale", "scale": [1.0, 1.0]}
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            scan_result = subprocess.CompletedProcess(
                args=["omero", "import", "-f"],
                returncode=0,
                stdout=f"# Group: {zarr_dir}\n{array_dir}\n",
                stderr="",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {core_functions.NATIVE_ZARR_IMPORT_ENABLED_ENV: "true"},
                ),
                mock.patch.object(
                    core_functions, "_run_local_import_scan", return_value=scan_result
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=False,
                        support_error="OME-Zarr metadata is missing multiscale axes information.",
                        compatibility_details="",
                    ),
                ),
            ):
                result = core_functions._check_import_compatibility(
                    "session-key",
                    "omeroserver",
                    4064,
                    zarr_dir,
                    dataset_id=None,
                    relative_path="bf2raw.ome.zarr",
                )

        self.assertEqual("compatible", result["status"])
        self.assertEqual("File format supported by OMERO", result["details"])

    def test_check_import_compatibility_rejects_invalid_native_zarr_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zarr_dir = Path(tmpdir) / "broken.ome.zarr"
            zarr_dir.mkdir()
            (zarr_dir / "s0").mkdir()
            (zarr_dir / "s0" / ".zarray").write_text(
                '{"shape":[1,1]}', encoding="utf-8"
            )
            (zarr_dir / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "datasets": [{"path": "s0"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            scan_result = subprocess.CompletedProcess(
                args=["omero", "import", "-f"],
                returncode=0,
                stdout="",
                stderr="unsupported",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {core_functions.NATIVE_ZARR_IMPORT_ENABLED_ENV: "true"},
                ),
                mock.patch.object(
                    core_functions, "_run_local_import_scan", return_value=scan_result
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=False,
                        support_error="OME-Zarr metadata is missing coordinate transformations for the primary resolution level.",
                        compatibility_details="",
                    ),
                ),
            ):
                result = core_functions._check_import_compatibility(
                    "session-key",
                    "omeroserver",
                    4064,
                    zarr_dir,
                    dataset_id=None,
                    relative_path="broken.ome.zarr",
                )

        self.assertEqual("error", result["status"])
        self.assertIn("coordinate transformations", result["details"].lower())

    def test_check_import_compatibility_rejects_native_zarr_missing_scale_transform(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            zarr_dir = Path(tmpdir) / "broken-scale.ome.zarr"
            zarr_dir.mkdir()
            (zarr_dir / "s0").mkdir()
            (zarr_dir / "s0" / ".zarray").write_text(
                '{"shape":[1,1],"dtype":"<u2"}',
                encoding="utf-8",
            )
            (zarr_dir / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "axes": [{"name": "y"}, {"name": "x"}],
                                "datasets": [{"path": "s0"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            scan_result = subprocess.CompletedProcess(
                args=["omero", "import", "-f"],
                returncode=0,
                stdout="",
                stderr="unsupported",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {core_functions.NATIVE_ZARR_IMPORT_ENABLED_ENV: "true"},
                ),
                mock.patch.object(
                    core_functions, "_run_local_import_scan", return_value=scan_result
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=False,
                        support_error="OME-Zarr metadata is missing coordinate transformations for the primary resolution level.",
                        compatibility_details="",
                    ),
                ),
            ):
                result = core_functions._check_import_compatibility(
                    "session-key",
                    "omeroserver",
                    4064,
                    zarr_dir,
                    dataset_id=None,
                    relative_path="broken-scale.ome.zarr",
                )

        self.assertEqual("error", result["status"])
        self.assertIn("coordinate transformations", result["details"].lower())

    def test_check_import_compatibility_rejects_native_zarr_string_axes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zarr_dir = Path(tmpdir) / "string-axes.ome.zarr"
            zarr_dir.mkdir()
            (zarr_dir / "s0").mkdir()
            (zarr_dir / "s0" / ".zarray").write_text(
                '{"shape":[1,1],"dtype":"<u2"}',
                encoding="utf-8",
            )
            (zarr_dir / ".zattrs").write_text(
                json.dumps(
                    {
                        "multiscales": [
                            {
                                "axes": ["y", "x"],
                                "datasets": [
                                    {
                                        "path": "s0",
                                        "coordinateTransformations": [
                                            {"type": "scale", "scale": [1.0, 1.0]}
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            scan_result = subprocess.CompletedProcess(
                args=["omero", "import", "-f"],
                returncode=0,
                stdout="",
                stderr="unsupported",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {core_functions.NATIVE_ZARR_IMPORT_ENABLED_ENV: "true"},
                ),
                mock.patch.object(
                    core_functions, "_run_local_import_scan", return_value=scan_result
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=False,
                        support_error="OME-Zarr metadata was found, but ome-zarr did not expose a readable multiscale image node.",
                        compatibility_details="",
                    ),
                ),
            ):
                result = core_functions._check_import_compatibility(
                    "session-key",
                    "omeroserver",
                    4064,
                    zarr_dir,
                    dataset_id=None,
                    relative_path="string-axes.ome.zarr",
                )

        self.assertEqual("error", result["status"])
        self.assertIn("readable multiscale image node", result["details"].lower())

    def test_check_import_compatibility_rejects_sparse_bioformats2raw_series(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zarr_dir = Path(tmpdir) / "bf2raw-gap.ome.zarr"
            for series_name in ("0", "2"):
                array_dir = zarr_dir / series_name / "0"
                array_dir.mkdir(parents=True)
                (array_dir / ".zarray").write_text(
                    '{"shape":[1,1],"dtype":"<u2"}',
                    encoding="utf-8",
                )
                (zarr_dir / series_name / ".zattrs").write_text(
                    json.dumps(
                        {
                            "multiscales": [
                                {
                                    "axes": [{"name": "y"}, {"name": "x"}],
                                    "datasets": [
                                        {
                                            "path": "0",
                                            "coordinateTransformations": [
                                                {"type": "scale", "scale": [1.0, 1.0]}
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
            (zarr_dir / ".zattrs").write_text(
                json.dumps({"bioformats2raw.layout": 3}),
                encoding="utf-8",
            )

            scan_result = subprocess.CompletedProcess(
                args=["omero", "import", "-f"],
                returncode=0,
                stdout="",
                stderr="unsupported",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {core_functions.NATIVE_ZARR_IMPORT_ENABLED_ENV: "true"},
                ),
                mock.patch.object(
                    core_functions, "_run_local_import_scan", return_value=scan_result
                ),
                mock.patch.object(
                    core_functions,
                    "inspect_ome_zarr_image",
                    return_value=types.SimpleNamespace(
                        recognized=True,
                        supported=False,
                        support_error=(
                            "OME-Zarr metadata was found, but ome-zarr did not expose "
                            "a readable multiscale image node."
                        ),
                        compatibility_details="",
                    ),
                ),
            ):
                result = core_functions._check_import_compatibility(
                    "session-key",
                    "omeroserver",
                    4064,
                    zarr_dir,
                    dataset_id=None,
                    relative_path="bf2raw-gap.ome.zarr",
                )

        self.assertEqual("error", result["status"])
        self.assertIn("readable multiscale image node", result["details"])

    def test_background_import_session_closes_created_session_object(self):
        fake_session = types.SimpleNamespace(
            getUuid=lambda: types.SimpleNamespace(getValue=lambda: "session-key")
        )
        fake_service = mock.Mock()
        fake_service.createSessionWithTimeouts.return_value = fake_session
        fake_admin_conn = mock.Mock()
        fake_admin_conn.c.sf.getSessionService.return_value = fake_service

        with (
            mock.patch.object(
                core_functions, "_open_admin_connection", return_value=fake_admin_conn
            ),
            mock.patch.object(
                core_functions, "_resolve_group_name", return_value="users_private"
            ),
            mock.patch.object(
                core_functions,
                "_get_background_import_session_timeout_seconds",
                return_value=3600,
            ),
            mock.patch.object(
                core_functions.omero,
                "sys",
                types.SimpleNamespace(Principal=lambda *args: ("Principal", args)),
                create=True,
            ),
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
            with mock.patch.object(
                core_functions, "_get_jobs_root", return_value=jobs_root
            ):
                self.assertTrue(core_functions._save_job(dict(job)))
                with mock.patch.object(core_functions.portalocker, "Lock", FailingLock):
                    loaded = core_functions._load_job(job_id)

        self.assertEqual(job["job_id"], loaded["job_id"])
        self.assertEqual(job["status"], loaded["status"])
        self.assertIn("updated", loaded)

    def test_mark_failed_job_for_deferred_cleanup_marks_upload_data_and_job_file(self):
        job_id = "c" * 32
        upload_root = _test_tmp_path("upload-root")
        jobs_root = _test_tmp_path("jobs-root")
        calls = []

        def capture_marker(path, root, *, ttl_seconds, now=None):
            calls.append((path, root, ttl_seconds, now))
            return True

        with (
            mock.patch.object(
                core_functions, "_get_upload_root", return_value=upload_root
            ),
            mock.patch.object(core_functions, "_get_jobs_root", return_value=jobs_root),
            mock.patch.object(
                core_functions,
                "safe_mark_path_for_deferred_cleanup",
                side_effect=capture_marker,
            ),
            mock.patch.dict(
                core_functions.os.environ,
                {core_functions.FAILED_IMPORT_RETENTION_SECONDS_ENV: "172800"},
                clear=False,
            ),
        ):
            self.assertTrue(
                core_functions._mark_failed_job_for_deferred_cleanup(job_id)
            )

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

            with mock.patch.object(
                core_functions, "_run_local_import_scan", side_effect=fake_scan
            ):
                units = core_functions._build_import_units(
                    {"files": entries}, upload_root
                )

        self.assertEqual(1, len(units))
        self.assertEqual("plate.zarr", units[0]["relative_path"])
        self.assertEqual("plate.zarr", units[0]["dataset_relative_path"])
        self.assertEqual("_staged/plate.zarr", units[0]["staged_path"])
        self.assertEqual(["_staged/plate.zarr"], units[0]["cleanup_staged_paths"])
        self.assertEqual("METADATA.ome.xml", units[0]["group_header_name"])

    def test_upload_template_keeps_compatibility_polling_without_browser_timeout(self):
        template = (
            REPO_ROOT
            / "omeroweb_import"
            / "templates"
            / "omeroweb_import"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "Compatibility check timeout - operation took too long. Please try again.",
            template,
        )
        self.assertNotIn(
            "Compatibility check timeout - maximum attempts exceeded.", template
        )
        self.assertNotIn("const maxTimeMs = 5 * 60 * 1000", template)

    def test_upload_template_uses_short_loading_label_for_dropped_files(self):
        template = (
            REPO_ROOT
            / "omeroweb_import"
            / "templates"
            / "omeroweb_import"
            / "index.html"
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

        with (
            mock.patch.object(index_view, "_load_job", return_value=job_payload),
            mock.patch.object(index_view, "current_username", return_value="alice"),
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

        with (
            mock.patch.object(index_view, "_load_job", return_value=job_payload),
            mock.patch.object(index_view, "current_username", return_value="alice"),
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
        request = types.SimpleNamespace(
            method="POST", user=types.SimpleNamespace(username="alice")
        )
        job_payload = {
            "job_id": job_id,
            "username": "alice",
            "status": "awaiting_confirmation",
            "compatibility_thread_active": True,
        }
        import_started = []

        with (
            mock.patch.object(
                index_view, "_load_owned_job", return_value=(job_payload, None)
            ),
            mock.patch.object(index_view, "_save_job", return_value=True),
            mock.patch.object(
                index_view,
                "_prepare_job_import_datasets",
                side_effect=AssertionError("dataset prep must stay off confirm_import"),
            ),
            mock.patch.object(
                index_view,
                "_start_import_thread",
                side_effect=lambda current_job_id: import_started.append(
                    current_job_id
                ),
            ),
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
        request_conn = types.SimpleNamespace(
            SERVICE_OPTS=types.SimpleNamespace(setOmeroGroup=lambda group: None)
        )
        created = []

        def fail_open_service_connection(*args, **kwargs):
            raise AssertionError(
                "service connection should not be used when request connection is available"
            )

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

        with (
            mock.patch.object(
                core_functions,
                "_open_service_connection",
                side_effect=fail_open_service_connection,
            ),
            mock.patch.object(
                core_functions,
                "_get_or_create_dataset",
                side_effect=fake_get_or_create_dataset,
            ),
        ):
            ok, error = core_functions._ensure_job_dataset_targets(
                job, entries_to_import, conn=request_conn
            )

        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual([(request_conn, "folder", 9)], created)
        self.assertEqual({"folder": 11}, job["dataset_map"])

    def test_prepare_request_job_import_datasets_uses_zarr_package_root_without_import_scan(
        self,
    ):
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

        with (
            mock.patch.object(
                core_functions,
                "_get_or_create_dataset",
                side_effect=fake_get_or_create_dataset,
            ),
            mock.patch.object(
                core_functions,
                "_save_job",
                return_value=True,
            ),
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

    def test_prepare_uploaded_job_for_request_path_import_waits_for_planned_units_during_compatibility(
        self,
    ):
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
            side_effect=AssertionError(
                "request-path preparation should wait for planned units"
            ),
        ):
            prepared_job, error = (
                core_functions._prepare_uploaded_job_for_request_path_import(
                    job["job_id"],
                    job,
                    conn=object(),
                )
            )

        self.assertIs(prepared_job, job)
        self.assertIsNone(error)

    def test_prepare_uploaded_job_for_request_path_import_waits_for_background_import_plan(
        self,
    ):
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
            side_effect=AssertionError(
                "request-path preparation should wait for the persisted import plan"
            ),
        ):
            prepared_job, error = (
                core_functions._prepare_uploaded_job_for_request_path_import(
                    job["job_id"],
                    job,
                    conn=object(),
                )
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

        with (
            mock.patch.object(core_functions, "_load_job", side_effect=fake_load_job),
            mock.patch.object(
                core_functions,
                "_build_import_units",
                return_value=[planned_unit],
            ),
            mock.patch.object(
                core_functions,
                "_update_job",
                side_effect=fake_update_job,
            ),
            mock.patch.object(
                core_functions,
                "_check_import_compatibility",
                side_effect=AssertionError(
                    "compatibility scan should not run when disabled"
                ),
            ),
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

        with (
            mock.patch.object(index_view, "_load_owned_job", return_value=(job, None)),
            mock.patch.object(
                index_view,
                "_prepare_uploaded_job_dataset_targets",
                return_value=(job, None),
            ),
            mock.patch.object(
                index_view,
                "_prepare_ready_job_for_import_start",
                return_value=(job, None),
            ),
            mock.patch.object(index_view, "_start_import_thread") as start_import,
            mock.patch.object(
                index_view,
                "_load_job",
                return_value=job,
            ),
        ):
            response = inspect.unwrap(index_view.job_status)(
                request, job_id, conn=object()
            )

        status, payload = self._json_status_and_payload(response)
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        start_import.assert_called_once_with(job_id)

    def test_vizarr_openwith_uses_browser_origin_for_source_url(self):
        script = (
            REPO_ROOT / "omero_web_zarr/static/omero_web_zarr/openwith.js"
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

        with mock.patch.object(
            core_functions, "_open_service_connection", return_value=fake_service_conn
        ):
            ok, error = core_functions._ensure_job_dataset_targets(
                job, entries_to_import
            )

        self.assertFalse(ok)
        self.assertEqual(
            "OMERO could not prepare the destination for this import.", error
        )
        self.assertNotIn("impersonate", error.lower())
        self.assertTrue(fake_service_conn.closed)

    def test_start_import_thread_does_not_spawn_when_save_fails(self):
        job = {"job_id": "b" * 32, "status": "ready", "import_thread_started": False}

        with (
            mock.patch.object(core_functions, "_load_job", return_value=job),
            mock.patch.object(core_functions, "_save_job", return_value=False),
            mock.patch.object(core_functions.threading, "Thread") as thread_cls,
            mock.patch.object(core_functions.logger, "error"),
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
        with (
            mock.patch.object(
                user_settings_view, "load_request_data", return_value={"settings": {}}
            ),
            mock.patch.object(
                user_settings_view,
                "save_user_settings",
                side_effect=data_store.UserSettingsStoreError("db secret"),
            ),
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
        with (
            mock.patch.object(
                special_method_settings_view,
                "load_request_data",
                return_value={"method": "sem_edx"},
            ),
            mock.patch.object(
                special_method_settings_view,
                "load_special_method_settings",
                side_effect=data_store.UserSettingsStoreError("db secret"),
            ),
        ):
            response = special_method_settings_view.load_settings(
                request, conn=object()
            )

        status, payload = self._json_status_and_payload(response)
        self.assertEqual(500, status)
        self.assertEqual("Could not load special method settings.", payload["error"])
        self.assertNotIn("secret", payload["error"])

    def test_upload_template_keeps_completed_bytes_and_aborts_parallel_failures(self):
        template = (
            REPO_ROOT / "omeroweb_import/templates/omeroweb_import/index.html"
        ).read_text()

        self.assertIn("let uploadCompletedBytes = 0;", template)
        self.assertIn("function abortActiveUploadRequests()", template)
        self.assertIn("xhr.__uploadProgressCompleted = true;", template)
        self.assertIn("throw firstError || error;", template)
        self.assertIn(
            "entry.file.name || (relativePath.split('/').pop() || relativePath)",
            template,
        )

    def test_upload_styles_keep_long_names_inside_tree_column(self):
        styles = (
            REPO_ROOT / "omeroweb_import/static/omeroweb_import/styles.css"
        ).read_text()

        self.assertIn("grid-template-columns: minmax(0, 1fr) 120px 170px 32px;", styles)
        self.assertIn("overflow-x: hidden;", styles)
        self.assertIn("overflow-wrap: anywhere;", styles)
        self.assertIn("word-break: break-word;", styles)
        self.assertIn("margin-left: 0;", styles)
        self.assertIn("padding-left: 0;", styles)


class ManageZarrManagedRepositoryScriptTests(TestCase):
    @staticmethod
    def _server_config(tmpdir: str, tmp_root: Path) -> dict[str, str]:
        return {
            "omero.data.dir": str(Path(tmpdir) / "data"),
            "omero.managed.dir": str(Path(tmpdir) / "data" / "ManagedRepository"),
            "omero.fs.repo.path": "%group%/%user%/%year%-%month%-%day%/%time%",
            "omero.web.import.shared_tmp_path": str(tmp_root),
        }

    def test_stage_zarr_uses_existing_user_prefix_and_template_suffix(self):
        manage_script = _load_manage_zarr_script_module()
        fixed_now = real_datetime(2026, 3, 22, 9, 51, 15)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir) / "tmp"
            source = tmp_root / "job-1" / "sample.ome.zarr"
            payload_file = source / "0" / "0"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_text("pixels", encoding="utf-8")

            managed_root = Path(tmpdir) / "data" / "ManagedRepository"
            user_prefix = managed_root / "users_private" / "test"
            user_prefix.mkdir(parents=True, exist_ok=True)
            server_config = self._server_config(tmpdir, tmp_root)

            with mock.patch.object(manage_script, "datetime") as mock_datetime:
                mock_datetime.now.return_value = fixed_now
                destination = manage_script._stage_zarr(
                    server_config,
                    str(source),
                    "users_private",
                    "test",
                )

            self.assertEqual(
                user_prefix / "2026-03-22" / "09-51-15" / "sample.ome.zarr",
                destination,
            )
            self.assertTrue((destination / "0" / "0").is_file())
            self.assertEqual(0o750, destination.stat().st_mode & 0o777)
            self.assertEqual(0o640, (destination / "0" / "0").stat().st_mode & 0o777)

    def test_shared_tmp_root_requires_persisted_server_config(self):
        manage_script = _load_manage_zarr_script_module()
        with self.assertRaisesRegex(RuntimeError, "omero.web.import.shared_tmp_path"):
            manage_script._shared_tmp_root({})

    def test_managed_repository_root_rejects_relative_managed_dir(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._server_config(tmpdir, Path(tmpdir) / "tmp")
            config["omero.managed.dir"] = "ManagedRepository"
            with self.assertRaisesRegex(RuntimeError, "must be an absolute path"):
                manage_script._managed_repository_root(config)

    def test_managed_repository_root_rejects_root_outside_data_dir(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._server_config(tmpdir, Path(tmpdir) / "tmp")
            outside_root = Path(tmpdir) / "server-image" / "ManagedRepository"
            outside_root.mkdir(parents=True, exist_ok=True)
            config["omero.managed.dir"] = str(outside_root)
            with self.assertRaisesRegex(RuntimeError, "must stay within"):
                manage_script._managed_repository_root(config)

    def test_stage_zarr_creates_missing_user_prefix(self):
        manage_script = _load_manage_zarr_script_module()
        fixed_now = real_datetime(2026, 3, 22, 9, 51, 15)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir) / "tmp"
            source = tmp_root / "job-1" / "sample.zarr"
            (source / "0").mkdir(parents=True, exist_ok=True)
            (source / "0" / "0").write_text("pixels", encoding="utf-8")
            managed_root = Path(tmpdir) / "data" / "ManagedRepository"
            managed_root.mkdir(parents=True, exist_ok=True)
            server_config = self._server_config(tmpdir, tmp_root)

            with mock.patch.object(manage_script, "datetime") as mock_datetime:
                mock_datetime.now.return_value = fixed_now
                destination = manage_script._stage_zarr(
                    server_config,
                    str(source),
                    "users_private",
                    "test",
                )

            self.assertEqual(
                managed_root
                / "users_private"
                / "test"
                / "2026-03-22"
                / "09-51-15"
                / "sample.zarr",
                destination,
            )
            self.assertTrue((managed_root / "users_private" / "test").is_dir())

    def test_load_server_config_reads_runtime_state_file(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            omerodir = Path(tmpdir) / "OMERO.server"
            state_dir = omerodir / "var"
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "managed-zarr-runtime.env").write_text(
                "omero.web.import.shared_tmp_path=/shared-transfer\n",
                encoding="utf-8",
            )

            values = {
                "omero.data.dir": "/OMERO",
                "omero.managed.dir": "/OMERO/ManagedRepository",
                "omero.fs.repo.path": "%group%/%user%/%year%-%month%-%day%/%time%",
            }
            conn = types.SimpleNamespace(
                c=types.SimpleNamespace(
                    sf=types.SimpleNamespace(
                        getConfigService=lambda: types.SimpleNamespace(
                            getConfigValue=lambda key: values[key]
                        )
                    )
                )
            )

            with mock.patch.dict(os.environ, {"OMERODIR": str(omerodir)}):
                config = manage_script._load_server_config(conn)

        self.assertEqual("/OMERO", config["omero.data.dir"])
        self.assertEqual("/OMERO/ManagedRepository", config["omero.managed.dir"])
        self.assertEqual("/shared-transfer", config["omero.web.import.shared_tmp_path"])

    def test_load_runtime_state_value_requires_existing_state_file_and_key(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            omerodir = Path(tmpdir) / "OMERO.server"
            with mock.patch.dict(os.environ, {"OMERODIR": str(omerodir)}):
                with self.assertRaisesRegex(
                    RuntimeError, "Missing import runtime state file"
                ):
                    manage_script._load_runtime_state_value(
                        "omero.web.import.shared_tmp_path"
                    )

            state_dir = omerodir / "var"
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "managed-zarr-runtime.env").write_text(
                "other=value\n", encoding="utf-8"
            )

            with mock.patch.dict(os.environ, {"OMERODIR": str(omerodir)}):
                with self.assertRaisesRegex(
                    RuntimeError, "Missing required import runtime value"
                ):
                    manage_script._load_runtime_state_value(
                        "omero.web.import.shared_tmp_path"
                    )

    def test_render_repo_template_and_validate_source_path_enforce_safe_inputs(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir) / "tmp"
            tmp_root.mkdir(parents=True, exist_ok=True)
            config = self._server_config(tmpdir, tmp_root)

            prefix_parts, suffix_parts = manage_script._render_repo_template(
                config,
                "users_private",
                "test",
                real_datetime(2026, 3, 22, 9, 51, 15),
            )
            self.assertEqual(["users_private", "test"], prefix_parts)
            self.assertEqual(["2026-03-22", "09-51-15"], suffix_parts)

            config["omero.fs.repo.path"] = "%group%/%unknown%"
            with self.assertRaisesRegex(RuntimeError, "unsupported tokens"):
                manage_script._render_repo_template(
                    config,
                    "users_private",
                    "test",
                    real_datetime(2026, 3, 22, 9, 51, 15),
                )

            config["omero.fs.repo.path"] = "%group%/%year%"
            with self.assertRaisesRegex(RuntimeError, "must include a %user% token"):
                manage_script._render_repo_template(
                    config,
                    "users_private",
                    "test",
                    real_datetime(2026, 3, 22, 9, 51, 15),
                )

            config = self._server_config(tmpdir, tmp_root)
            source = tmp_root / "job-1" / "sample.zarr"
            source.mkdir(parents=True, exist_ok=True)
            self.assertEqual(
                source.resolve(),
                manage_script._validate_source_path(config, str(source)),
            )

            outside = Path(tmpdir) / "outside" / "sample.zarr"
            outside.mkdir(parents=True, exist_ok=True)
            with self.assertRaisesRegex(RuntimeError, "must stay within"):
                manage_script._validate_source_path(config, str(outside))

            not_zarr = tmp_root / "job-1" / "sample.txt"
            not_zarr.mkdir(parents=True, exist_ok=True)
            with self.assertRaisesRegex(RuntimeError, "not a .zarr directory"):
                manage_script._validate_source_path(config, str(not_zarr))

    def test_allocate_destination_dir_cleanup_and_symlink_guards(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "data" / "ManagedRepository"
            prefix_dir = managed_root / "users_private" / "test"
            prefix_dir.mkdir(parents=True, exist_ok=True)
            target_dir = prefix_dir / "2026-03-22" / "09-51-15"
            target_dir.mkdir(parents=True, exist_ok=True)
            existing = target_dir / "sample.zarr"
            existing.mkdir()

            alternative = manage_script._allocate_destination_dir(
                target_dir, "sample.zarr"
            )
            self.assertNotEqual(existing, alternative)
            self.assertTrue(alternative.name.startswith("sample__"))
            self.assertTrue(alternative.name.endswith(".zarr"))

            payload = target_dir / "delete-me.zarr"
            payload.mkdir()
            server_config = self._server_config(tmpdir, Path(tmpdir) / "tmp")
            deleted = manage_script._cleanup_zarr(
                server_config, str(payload), "users_private", "test"
            )
            self.assertEqual(payload, deleted)
            self.assertFalse(payload.exists())

            with self.assertRaisesRegex(
                RuntimeError, "Refusing to delete the user managed-repository prefix"
            ):
                manage_script._cleanup_zarr(
                    server_config, str(prefix_dir), "users_private", "test"
                )

            symlink_source = Path(tmpdir) / "tmp" / "job-1" / "link.zarr"
            symlink_source.mkdir(parents=True, exist_ok=True)
            (symlink_source / "real").mkdir()
            (symlink_source / "bad-link").symlink_to(
                symlink_source / "real", target_is_directory=True
            )
            with self.assertRaisesRegex(RuntimeError, "Symlinks are not allowed"):
                manage_script._reject_symlinks(symlink_source)

    def test_cleanup_zarr_rejects_path_outside_user_prefix(self):
        manage_script = _load_manage_zarr_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "data" / "ManagedRepository"
            (managed_root / "users_private" / "test").mkdir(parents=True, exist_ok=True)
            outside_path = (
                managed_root
                / "users_private"
                / "other"
                / "2026-03-22"
                / "09-51-15"
                / "sample.zarr"
            )
            server_config = self._server_config(tmpdir, Path(tmpdir) / "tmp")

            with self.assertRaisesRegex(
                RuntimeError, "outside the allowed user prefix"
            ):
                manage_script._cleanup_zarr(
                    server_config, str(outside_path), "users_private", "test"
                )

    def test_run_script_sets_outputs_and_closes_session(self):
        manage_script = _load_manage_zarr_script_module()

        class _FakeClient:
            def __init__(self, params):
                self._params = params
                self.outputs = {}
                self.closed = False

            def getInputs(self, unwrap=True):
                return dict(self._params)

            def setOutput(self, key, value):
                self.outputs[key] = value

            def closeSession(self):
                self.closed = True

        stage_client = _FakeClient(
            {
                "Action": "stage",
                "Group_Name": "users_private",
                "Username": "test",
                "Source_Path": str(_test_tmp_path("source.zarr")),
            }
        )
        cleanup_client = _FakeClient(
            {
                "Action": "cleanup",
                "Group_Name": "users_private",
                "Username": "test",
                "Managed_Path": "/OMERO/ManagedRepository/users_private/test/sample.zarr",
            }
        )

        with (
            mock.patch.object(
                manage_script.scripts,
                "client",
                side_effect=[stage_client, cleanup_client],
            ),
            mock.patch.object(
                manage_script,
                "BlitzGateway",
                side_effect=lambda client_obj=None: object(),
            ),
            mock.patch.object(manage_script, "_load_server_config", return_value={}),
            mock.patch.object(
                manage_script,
                "_stage_zarr",
                return_value=Path(
                    "/OMERO/ManagedRepository/users_private/test/sample.zarr"
                ),
            ),
            mock.patch.object(
                manage_script,
                "_cleanup_zarr",
                return_value=Path(
                    "/OMERO/ManagedRepository/users_private/test/sample.zarr"
                ),
            ),
            mock.patch.object(
                manage_script, "rstring", side_effect=lambda value: value
            ),
            mock.patch("builtins.print") as print_mock,
        ):
            manage_script.run_script()
            manage_script.run_script()

        self.assertEqual(
            "/OMERO/ManagedRepository/users_private/test/sample.zarr",
            stage_client.outputs["Managed_Path"],
        )
        self.assertIn(
            "Staged Zarr into managed repository", stage_client.outputs["Message"]
        )
        self.assertIn(
            "Cleaned managed-repository Zarr path", cleanup_client.outputs["Message"]
        )
        self.assertTrue(stage_client.closed)
        self.assertTrue(cleanup_client.closed)
        self.assertGreaterEqual(print_mock.call_count, 4)

    def test_run_script_reports_invalid_actions_without_leaking_session(self):
        manage_script = _load_manage_zarr_script_module()

        class _FakeClient:
            def __init__(self):
                self.outputs = {}
                self.closed = False

            def getInputs(self, unwrap=True):
                return {
                    "Action": "invalid",
                    "Group_Name": "users_private",
                    "Username": "test",
                }

            def setOutput(self, key, value):
                self.outputs[key] = value

            def closeSession(self):
                self.closed = True

        client = _FakeClient()
        with (
            mock.patch.object(manage_script.scripts, "client", return_value=client),
            mock.patch.object(
                manage_script,
                "BlitzGateway",
                side_effect=lambda client_obj=None: object(),
            ),
            mock.patch.object(manage_script, "_load_server_config", return_value={}),
            mock.patch.object(
                manage_script, "rstring", side_effect=lambda value: value
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Action must be one of"):
                manage_script.run_script()

        self.assertTrue(client.closed)
        self.assertIn("Script error: Action must be one of", client.outputs["Message"])


if __name__ == "__main__":
    unittest_main()
