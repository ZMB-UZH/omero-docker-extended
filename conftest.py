"""Root conftest — mock heavy OMERO/Ice dependencies for test collection."""
import sys
from types import ModuleType
from unittest.mock import MagicMock


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

for _mod in [
    "omeroweb", "omeroweb.connector", "omeroweb.http",
    "omeroweb.webclient", "omeroweb.webclient.decorators",
    "Ice", "omero", "omero.gateway", "omero.rtypes", "omero.sys",
    "omero.clients", "omero.model", "omero.api",
]:
    sys.modules.setdefault(_mod, MagicMock())

sys.modules.setdefault("omeroweb.decorators", _omeroweb_decorators)

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATABASES={},
        INSTALLED_APPS=["django.contrib.contenttypes"],
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    )
    django.setup()
