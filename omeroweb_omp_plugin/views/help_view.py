from django.http import FileResponse, Http404
from omeroweb.decorators import login_required
import os

from ..strings import errors

@login_required()
def help_page(request, **kwargs):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    help_path = os.path.join(
        base_dir,
        "static",
        "help.pdf",
    )

    if not os.path.exists(help_path):
        raise Http404(errors.help_file_not_found(help_path))

    return FileResponse(open(help_path, "rb"), content_type="application/pdf")
  
