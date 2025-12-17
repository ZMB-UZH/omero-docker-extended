import sys
import types


def _ensure_module(name, attrs=None):
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if attrs:
        for key, value in attrs.items():
            setattr(mod, key, value)
    return mod


# Stub minimal Django pieces used during import-time evaluation
class _DummyResponse:
    def __init__(self, data=None, status=200):
        self.data = data
        self.status = status


http_mod = _ensure_module("django.http", {"HttpResponse": _DummyResponse, "JsonResponse": _DummyResponse})


def csrf_exempt(fn):
    return fn


csrf_mod = _ensure_module("django.views.decorators.csrf", {"csrf_exempt": csrf_exempt})
decorators_mod = _ensure_module("django.views.decorators")
setattr(decorators_mod, "csrf", csrf_mod)


def login_required(*args, **kwargs):
    def decorator(fn):
        return fn

    return decorator


_ensure_module("omeroweb.decorators", {"login_required": login_required})


# Minimal omero stubs so import-time references succeed
_ensure_module("omero")
omero_sys_mod = _ensure_module("omero.sys")


class _Dummy:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


omero_sys_mod.ParametersI = _Dummy


model_mod = _ensure_module(
    "omero.model",
    {
        "MapAnnotationI": _Dummy,
        "NamedValue": _Dummy,
        "ImageAnnotationLinkI": _Dummy,
    },
)


def _rstring(val):
    return _Dummy(val)


rtypes_mod = _ensure_module("omero.rtypes", {"rstring": _rstring, "rlong": _rstring})


# portalocker stub for import safety
def _noop(*args, **kwargs):
    return None


class _Lock:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


_ensure_module(
    "portalocker",
    {
        "Lock": _Lock,
        "LOCK_EX": 0,
        "LockException": Exception,
        "lock": _noop,
    },
)
