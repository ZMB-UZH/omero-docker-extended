from functools import wraps

from django.http import JsonResponse

from omero_plugin_common.request_utils import current_username


def require_root_user(view_func):
    """Require the root user.

    Inputs: `view_func`. Output: `_wrapped`.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        """Call the wrapped view after resolving user and connector context.

        Inputs: `request` Django request, `*args` positional arguments, `**kwargs`
        keyword arguments. Output: `view_func` result.
        """
        conn = kwargs.get("conn")
        username = current_username(request, conn)
        if username != "root":
            return JsonResponse(
                {"error": ("PLEASE LOGIN AS ROOT USER\nTO USE THIS PLUGIN")},
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


__all__ = ["current_username", "require_root_user"]
