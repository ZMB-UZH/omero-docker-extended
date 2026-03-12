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


def _passthrough_login_required(*args, **kwargs):
    """Replicate omeroweb.decorators.login_required as a no-op decorator."""
    def decorator(func):
        return func
    # Called as @login_required() (with parens)
    if args and callable(args[0]):
        return args[0]
    return decorator


# Build a proper mock for omeroweb.decorators with a real login_required
_omeroweb_decorators = ModuleType("omeroweb.decorators")
_omeroweb_decorators.login_required = _passthrough_login_required

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
    "omeroweb", "omeroweb.connector", "omeroweb.http",
    "omeroweb.webclient", "omeroweb.webclient.decorators",
    "Ice", "omero", "omero.gateway", "omero.rtypes", "omero.sys",
    "omero.clients", "omero.model", "omero.api",
]:
    sys.modules.setdefault(_mod, MagicMock())

sys.modules.setdefault("omeroweb.decorators", _omeroweb_decorators)
sys.modules.setdefault("celery", _celery_module)
sys.modules.setdefault("celery.states", _celery_states)

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
