from django.shortcuts import render
from omeroweb.decorators import login_required

from .utils import require_non_root_user


@login_required()
@require_non_root_user
def help_page(request, _conn=None, **kwargs):
    """Return the help page.

    Inputs: `request` Django request, `_conn`, `**kwargs` keyword arguments. Output:
    rendered Django response.
    """
    return render(request, "omeroweb_tools/help.html", {})
