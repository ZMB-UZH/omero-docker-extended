from functools import wraps

from django.http import JsonResponse

from omero_plugin_common.request_utils import current_username


def require_root_user(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        conn = kwargs.get("conn")
        username = current_username(request, conn)
        if username != "root":
            return JsonResponse(
                {
                    "error": (
                        "PLEASE LOGIN AS ROOT USER\nTO USE THIS PLUGIN"
                    )
                },
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


__all__ = ["current_username", "require_root_user"]
