from django.shortcuts import render
from omeroweb.decorators import login_required

from .utils import current_username


@login_required()
def index(request, conn=None, url=None, **kwargs):
    username = current_username(request, conn)
    is_root_user = username == "root"
    return render(
        request,
        "omeroweb_admin_tools/index.html",
        {
            "is_root_user": is_root_user,
        },
    )
