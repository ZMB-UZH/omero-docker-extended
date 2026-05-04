from pathlib import Path

from django.http import FileResponse, Http404
from omeroweb.decorators import login_required
from .utils import require_root_user


@login_required()
@require_root_user
def help_page(request, **kwargs):
    """Return the help page.

    Inputs: `request` Django request, `**kwargs` keyword arguments. Output: Django
    `FileResponse`. Raises: Http404 when validation or the called operation fails.
    """
    help_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "help"
        / "omeroweb_admin_tools_help.md"
    )
    if not help_path.exists():
        raise Http404(f"Help file not found: {help_path}")
    return FileResponse(help_path.open("rb"), content_type="text/markdown")
