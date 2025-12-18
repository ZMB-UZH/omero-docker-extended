from django.http import FileResponse, Http404
from omeroweb.decorators import login_required
import os

@login_required()
def help_page(request, **kwargs):
    help_path = "/opt/omero/web/OMERO.web/var/static/omeroweb_filenamemetadata/help.pdf"

    if not os.path.exists(help_path):
        raise Http404("Help file not found")

    return FileResponse(open(help_path, "rb"), content_type="application/pdf")
