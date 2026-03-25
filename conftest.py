"""Root conftest — mock heavy OMERO/Ice dependencies for test collection."""
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

os.environ.setdefault("OMERO_WEB_ROOT", "/tmp")
os.environ.setdefault("OMERO_WEB_VENV", "venv")
os.environ.setdefault("OMERO_TMP_PATH", "/tmp")
os.environ.setdefault("OMERO_IMS_CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("OMERO_IMS_CELERY_BACKEND_URL", "redis://localhost:6379/1")
os.environ.setdefault("OMERO_IMS_CELERY_QUEUE", "imaris")
os.environ.setdefault("OMERO_IMS_CELERY_RESULT_EXPIRES", "3600")
os.environ.setdefault("OMERO_IMS_CELERY_TIME_LIMIT", "3600")
os.environ.setdefault("OMERO_IMS_CELERY_MAX_RETRIES", "3")
os.environ.setdefault("OMERO_IMS_CELERY_PREFETCH", "1")
os.environ.setdefault("OMERO_IMS_EXPORT_TIMEOUT", "30")
os.environ.setdefault("OMERO_IMS_EXPORT_POLL_INTERVAL", "0.01")
os.environ.setdefault("OMERO_IMS_SCRIPT_NAME", "Batch_Image_Export_Imaris.py")
os.environ.setdefault("OMERO_IMS_EXPORT_DIR", "/tmp/imaris-exports")
os.environ.setdefault("OMERO_IMS_SCRIPT_START_TIMEOUT", "30")
os.environ.setdefault("OMERO_IMS_SCRIPT_START_RETRY_INTERVAL", "0.1")
os.environ.setdefault("OMERO_IMS_PROCESSOR_CONFIG_CACHE_TTL", "60")
os.environ.setdefault("OMERO_WEB_UPLOAD_ALTERNATIVE_ZARR_IMPORT", "true")
os.environ.setdefault("OMERO_WEB_ZARR_ALTERNATIVE_RENDERING", "true")


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
_omeroweb_decorators = ModuleType("omeroweb.decorators")
_omeroweb_decorators.login_required = _passthrough_login_required

_omeroweb_webclient_decorators = ModuleType("omeroweb.webclient.decorators")
_omeroweb_webclient_decorators.login_required = _passthrough_login_required


class _ColorHolder:
    """Minimal stand-in for omero.gateway.ColorHolder."""

    def __init__(self, r=0, g=0, b=0, a=255):
        self._r, self._g, self._b, self._a = r, g, b, a

    @classmethod
    def fromRGBA(cls, r, g, b, a):
        return cls(r, g, b, a)

    def getHtml(self):
        return "{:02X}{:02X}{:02X}".format(self._r, self._g, self._b)

    def getRed(self):
        return self._r

    def getGreen(self):
        return self._g

    def getBlue(self):
        return self._b

    def getAlpha(self):
        return self._a


_celery_module = ModuleType("celery")
_celery_states = ModuleType("celery.states")
for _name in ("PENDING", "RECEIVED", "STARTED", "FAILURE", "IGNORED", "SUCCESS", "REVOKED"):
    setattr(_celery_states, _name, _name)


class _DummyCelery:
    def __init__(self, *args, **kwargs):
        self.conf = MagicMock()

    def autodiscover_tasks(self, *args, **kwargs):
        return None

    def task(self, *args, **kwargs):
        def decorator(func):
            return func

        if args and callable(args[0]):
            return args[0]
        return decorator


_celery_module.Celery = _DummyCelery
_celery_module.states = _celery_states

for _mod in [
    "omeroweb", "omeroweb.connector", "omeroweb.http", "omeroweb.httprsp",
    "omeroweb.webclient",
    "omeroweb.webclient.urls", "omeroweb.webclient.views",
    "omeroweb.webclient.webclient_gateway",
    "omeroweb.webgateway", "omeroweb.webgateway.marshal",
    "omeroweb.webgateway.urls", "omeroweb.webgateway.views",
    "Ice", "omero", "omero.gateway", "omero.rtypes", "omero.sys",
    "omero.clients", "omero.model", "omero.model.enums", "omero.api",
    "omero_figure", "omero_figure.views",
    "omero_iviewer", "omero_iviewer.views",
]:
    sys.modules.setdefault(_mod, MagicMock())

sys.modules.setdefault("omeroweb.decorators", _omeroweb_decorators)
sys.modules.setdefault("omeroweb.webclient.decorators", _omeroweb_webclient_decorators)
sys.modules.setdefault("celery", _celery_module)
sys.modules.setdefault("celery.states", _celery_states)

# Inject ColorHolder into the omero.gateway mock so integration tests that
# use omero.gateway.ColorHolder.fromRGBA() get real string output.
sys.modules["omero.gateway"].ColorHolder = _ColorHolder

# Wire parent-mock attributes to their explicit sys.modules child mocks so
# ``from parent import child`` resolves the same object as
# ``sys.modules["parent.child"]``.  Without this, MagicMock auto-creates a
# different child attribute each time, breaking identity assertions in tests
# that monkeypatch module-level attributes on submodules.
_submodule_wiring = {
    "omeroweb": ["connector", "http", "httprsp"],
    "omeroweb.webgateway": ["marshal", "urls", "views"],
    "omeroweb.webclient": ["urls", "views", "webclient_gateway"],
    "omero": ["gateway", "rtypes", "sys", "clients", "model", "api"],
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
        USE_TZ=True,
    )
    django.setup()
