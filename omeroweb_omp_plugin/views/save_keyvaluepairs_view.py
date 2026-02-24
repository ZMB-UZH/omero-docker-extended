from django.http import HttpResponse
from omeroweb.decorators import login_required
from ..views.utils import require_non_root_user

@login_required()
@require_non_root_user
def save_keyvaluepairs(request, conn=None, url=None, **kwargs):
    return HttpResponse("Save endpoint ready")
