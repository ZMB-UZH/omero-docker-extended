from django.http import HttpResponse
from omeroweb.decorators import login_required
from ..views.utils import require_non_root_user


@login_required()
@require_non_root_user
def save_keyvaluepairs(request, _conn=None, _url=None, **kwargs):
    """Save keyvaluepairs.

    Inputs: `request`, `_conn`, `_url`, `**kwargs`. Output: `HttpResponse` result.
    """
    return HttpResponse("Save endpoint ready")
