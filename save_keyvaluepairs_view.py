from django.http import HttpResponse
from omeroweb.decorators import login_required

@login_required()
def save_keyvaluepairs(request, conn=None, url=None, **kwargs):
    return HttpResponse("Save endpoint ready")
