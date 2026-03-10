from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..views.utils import require_non_root_user


@csrf_exempt
@login_required()
@require_non_root_user
def delete_plugin_keyvaluepairs(request, conn=None, url=None, **kwargs):
    """Retire the legacy password-based plugin delete endpoint."""
    return JsonResponse(
        {
            "ok": False,
            "error": "This endpoint has been retired. Use the background delete job flow instead.",
        },
        status=410,
    )
