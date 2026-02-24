from functools import wraps

from django.http import JsonResponse

from omero_plugin_common.request_utils import current_username


def require_root_user(view_func):
    @wraps(view_func)
    def _wrapped(request, conn=None, url=None, *args, **kwargs):
        username = current_username(request, conn)
        if username != "root":
            return JsonResponse(
                {
                    "error": (
                        "OMERO Admin Tools is restricted to the OMERO root account. "
                        "Please sign in as root to continue."
                    )
                },
                status=403,
            )
        return view_func(request, conn=conn, url=url, *args, **kwargs)

    return _wrapped


__all__ = ["current_username", "require_root_user"]
