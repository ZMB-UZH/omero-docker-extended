from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

from ..views.utils import require_non_root_user


@csrf_exempt
@login_required()
@require_non_root_user
def delete_all_keyvaluepairs(request, conn=None, url=None, **kwargs):
    """Retire the legacy password-based delete endpoint.

    Destructive deletes now run through the authenticated job flow, which avoids
    putting user passwords on the OMERO CLI command line.
    """
    return JsonResponse(
        {
            "ok": False,
            "error": "This endpoint has been retired. Use the background delete job flow instead.",
        },
        status=410,
    )
