from django.http import JsonResponse
from django.shortcuts import render
from omeroweb.decorators import login_required

from .utils import current_username


@login_required()
def index(request, conn=None, url=None, **kwargs):
    return render(
        request,
        "omeroweb_admin_tools/index.html",
        {},
    )


@login_required()
def root_status(request, conn=None, url=None, **kwargs):
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})
