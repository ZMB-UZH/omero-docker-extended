"""Root conftest — mock heavy OMERO/Ice dependencies for test collection."""

from importlib.machinery import ModuleSpec
import os
import sys
import tempfile
from types import ModuleType
from typing import Any, TypeVar
from unittest.mock import MagicMock

import pytest

_TEST_TMP_ROOT = tempfile.gettempdir()

_TEST_ENV_DEFAULTS = {
    "OMERO_WEB_ROOT": _TEST_TMP_ROOT,
    "OMERO_WEB_VENV": "venv",
    "OMERO_TMP_PATH": _TEST_TMP_ROOT,
    "OMERO_IMS_CELERY_BROKER_URL": "redis://localhost:6379/0",
    "OMERO_IMS_CELERY_BACKEND_URL": "redis://localhost:6379/1",
    "OMERO_IMS_CELERY_QUEUE": "imaris",
    "OMERO_IMS_CELERY_RESULT_EXPIRES": "3600",
    "OMERO_IMS_CELERY_TIME_LIMIT": "3600",
    "OMERO_IMS_CELERY_MAX_RETRIES": "3",
    "OMERO_IMS_CELERY_PREFETCH": "1",
    "OMERO_IMS_EXPORT_TIMEOUT": "30",
    "OMERO_IMS_EXPORT_POLL_INTERVAL": "0.01",
    "OMERO_IMS_SCRIPT_NAME": "Batch_Image_Export_Imaris.py",
    "OMERO_IMS_EXPORT_DIR": os.path.join(_TEST_TMP_ROOT, "imaris-exports"),
    "OMERO_IMS_SCRIPT_START_TIMEOUT": "30",
    "OMERO_IMS_SCRIPT_START_RETRY_INTERVAL": "0.1",
    "OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL": "60",
    "OMERO_WEB_UPLOAD_ALTERNATIVE_ZARR_IMPORT": "true",
    "OMERO_WEB_ZARR_ALTERNATIVE_RENDERING": "true",
}

for _env_name, _env_value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_env_name, _env_value)

_PACKAGE_STUBS = {
    "celery",
    "omero",
    "omero.model",
    "omero_figure",
    "omero_iviewer",
    "omeroweb",
    "omeroweb.webclient",
    "omeroweb.webgateway",
}
_ModuleStubT = TypeVar("_ModuleStubT", ModuleType, MagicMock)


def _set_module_metadata(
    module: _ModuleStubT,
    module_name: str,
) -> _ModuleStubT:
    """Give test stubs enough import metadata for importlib discovery."""

    is_package = module_name in _PACKAGE_STUBS
    module.__name__ = module_name
    module.__package__ = module_name if is_package else module_name.rpartition(".")[0]
    module.__spec__ = ModuleSpec(module_name, loader=None, is_package=is_package)
    if is_package:
        setattr(module, "__path__", [])
    return module


def _mock_module(module_name: str) -> MagicMock:
    return _set_module_metadata(MagicMock(), module_name)


def _passthrough_login_required(*args, **kwargs):
    """Replicate omeroweb.decorators.login_required as a no-op decorator.

    Returns a thin wrapper that forwards all arguments unchanged and exposes
    ``__wrapped__`` (the ``functools.wraps`` contract) so tests can unwrap
    the decorator the same way they would in production.
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*a, **kw):
            return func(*a, **kw)

        return wrapper

    # Called as @login_required() (with parens)
    if args and callable(args[0]):
        return decorator(args[0])
    return decorator


# Build proper mocks for omeroweb.decorators and omeroweb.webclient.decorators
# with a real login_required so decorated view functions keep __wrapped__.
_omeroweb_decorators = _set_module_metadata(
    ModuleType("omeroweb.decorators"), "omeroweb.decorators"
)
_omeroweb_decorators.login_required = _passthrough_login_required

_omeroweb_webclient_decorators = _set_module_metadata(
    ModuleType("omeroweb.webclient.decorators"), "omeroweb.webclient.decorators"
)
_omeroweb_webclient_decorators.login_required = _passthrough_login_required


class _ColorHolder:
    """Minimal stand-in for omero.gateway.ColorHolder."""

    def __init__(self, r=0, g=0, b=0, a=255):
        self._r, self._g, self._b, self._a = r, g, b, a

    @classmethod
    def fromRGBA(cls, r, g, b, a):
        return cls(r, g, b, a)

    def getHtml(self):
        return f"{self._r:02X}{self._g:02X}{self._b:02X}"

    def getRed(self):
        return self._r

    def getGreen(self):
        return self._g

    def getBlue(self):
        return self._b

    def getAlpha(self):
        return self._a


_celery_module = _set_module_metadata(ModuleType("celery"), "celery")
_celery_states = _set_module_metadata(ModuleType("celery.states"), "celery.states")
for _name in (
    "PENDING",
    "RECEIVED",
    "STARTED",
    "FAILURE",
    "IGNORED",
    "SUCCESS",
    "REVOKED",
):
    setattr(_celery_states, _name, _name)


class _DummyCelery:
    def __init__(self, *args, **kwargs):
        self.conf = MagicMock()

    @staticmethod
    def autodiscover_tasks(*args, **kwargs):
        return None

    @staticmethod
    def task(*args, **kwargs):
        def decorator(func):
            return func

        if args and callable(args[0]):
            return args[0]
        return decorator


_celery_module.Celery = _DummyCelery
_celery_module.states = _celery_states
_celery_module.current_app = MagicMock()

for _mod in [
    "omeroweb",
    "omeroweb.connector",
    "omeroweb.http",
    "omeroweb.httprsp",
    "omeroweb.webclient",
    "omeroweb.webclient.urls",
    "omeroweb.webclient.views",
    "omeroweb.webclient.webclient_gateway",
    "omeroweb.webgateway",
    "omeroweb.webgateway.marshal",
    "omeroweb.webgateway.urls",
    "omeroweb.webgateway.views",
    "Ice",
    "omero",
    "omero.gateway",
    "omero.rtypes",
    "omero.sys",
    "omero.clients",
    "omero.model",
    "omero.model.enums",
    "omero.api",
    "omero.scripts",
    "omero_figure",
    "omero_figure.views",
    "omero_iviewer",
    "omero_iviewer.views",
]:
    _stub = sys.modules.setdefault(_mod, _mock_module(_mod))
    if getattr(_stub, "__spec__", None) is None:
        _set_module_metadata(_stub, _mod)

sys.modules.setdefault("omeroweb.decorators", _omeroweb_decorators)
sys.modules.setdefault("omeroweb.webclient.decorators", _omeroweb_webclient_decorators)
sys.modules.setdefault("celery", _celery_module)
sys.modules.setdefault("celery.states", _celery_states)

# Inject ColorHolder into the omero.gateway mock so integration tests that
# use omero.gateway.ColorHolder.fromRGBA() get real string output.
sys.modules["omero.gateway"].ColorHolder = _ColorHolder
sys.modules["omero.rtypes"].rstring = lambda value: value
sys.modules["omero.rtypes"].rint = lambda value: value
_webgateway_views = sys.modules["omeroweb.webgateway.views"]
setattr(
    _webgateway_views,
    "_get_prepared_image",
    getattr(_webgateway_views, "_get_prepared_image", lambda *args, **kwargs: None),
)
setattr(
    _webgateway_views,
    "_render_thumbnail",
    getattr(_webgateway_views, "_render_thumbnail", lambda *args, **kwargs: None),
)
_webgateway_views.get_thumbnails_json = getattr(
    _webgateway_views, "get_thumbnails_json", lambda *args, **kwargs: {}
)
_webgateway_views.render_image = getattr(
    _webgateway_views, "render_image", lambda *args, **kwargs: None
)
_webgateway_views.render_image_region = getattr(
    _webgateway_views, "render_image_region", lambda *args, **kwargs: None
)
_webgateway_views.imageData_json = getattr(
    _webgateway_views, "imageData_json", lambda *args, **kwargs: {}
)
_webgateway_views.imageMarshal = getattr(
    _webgateway_views, "imageMarshal", lambda *args, **kwargs: {}
)
_webgateway_views.jsonp = getattr(_webgateway_views, "jsonp", lambda func: func)
_webgateway_views.get_longs = getattr(
    _webgateway_views, "get_longs", lambda *args, **kwargs: []
)
_webgateway_views.getIntOrDefault = getattr(
    _webgateway_views, "getIntOrDefault", lambda *args, **kwargs: None
)

# Wire parent-mock attributes to their explicit sys.modules child mocks so
# ``from parent import child`` resolves the same object as
# ``sys.modules["parent.child"]``.  Without this, MagicMock auto-creates a
# different child attribute each time, breaking identity assertions in tests
# that monkeypatch module-level attributes on submodules.
_submodule_wiring = {
    "omeroweb": ["connector", "http", "httprsp"],
    "omeroweb.webgateway": ["marshal", "urls", "views"],
    "omeroweb.webclient": ["urls", "views", "webclient_gateway"],
    "omero": ["gateway", "rtypes", "sys", "clients", "model", "api", "scripts"],
    "omero.model": ["enums"],
    "omero_figure": ["views"],
    "omero_iviewer": ["views"],
}
for _parent_name, _children in _submodule_wiring.items():
    _parent = sys.modules.get(_parent_name)
    if _parent is None:
        continue
    for _child_name in _children:
        _full = f"{_parent_name}.{_child_name}"
        _child = sys.modules.get(_full)
        if _child is not None:
            setattr(_parent, _child_name, _child)

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATABASES={},
        INSTALLED_APPS=["django.contrib.contenttypes"],
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        ROOT_URLCONF="omeroweb_admin_tools.urls",
        ALLOWED_HOSTS=["*"],
        DEFAULT_CHARSET="utf-8",
        SECRET_KEY="test",
        USE_I18N=False,
        USE_TZ=True,
    )
    django.setup()


_ISOLATED_MODULE_PREFIXES = (
    "celery",
    "django",
    "omero",
    "omero_plugin_common",
    "omeroweb",
    "omeroweb_imaris_connector",
    "omeroweb_import",
    "omeroweb_omp_plugin",
    "omeroweb_tools",
    "portalocker",
)

_MODULE_STATE_BASELINE: dict[str, tuple[ModuleType, dict[str, Any]]] = {}


def _matches_isolated_prefix(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in _ISOLATED_MODULE_PREFIXES
    )


def _snapshot_module_state() -> dict[str, tuple[ModuleType, dict[str, Any]]]:
    snapshot: dict[str, tuple[ModuleType, dict[str, Any]]] = {}
    for module_name, module in list(sys.modules.items()):
        if _matches_isolated_prefix(module_name):
            snapshot[module_name] = (module, dict(getattr(module, "__dict__", {})))
    return snapshot


def _restore_module_state(
    snapshot: dict[str, tuple[ModuleType, dict[str, Any]]],
) -> None:
    if not snapshot:
        return

    for module_name in list(sys.modules):
        if _matches_isolated_prefix(module_name) and module_name not in snapshot:
            sys.modules.pop(module_name, None)

    for module_name, (module, saved_dict) in snapshot.items():
        sys.modules[module_name] = module
        current_dict = getattr(module, "__dict__", None)
        if current_dict is None:
            continue
        for key in list(current_dict):
            if key not in saved_dict:
                current_dict.pop(key, None)
        current_dict.update(saved_dict)


def pytest_collection_finish() -> None:
    _MODULE_STATE_BASELINE.clear()
    _MODULE_STATE_BASELINE.update(_snapshot_module_state())


@pytest.fixture(autouse=True)
def _isolate_module_state():
    _restore_module_state(_MODULE_STATE_BASELINE)
    yield
    _restore_module_state(_MODULE_STATE_BASELINE)
