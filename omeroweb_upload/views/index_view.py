import logging
import os
from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required

logger = logging.getLogger(__name__)


def _get_upload_root() -> Path:
    configured = os.environ.get("OMERO_WEB_UPLOAD_DIR", "/OMERO/DropBox/Upload")
    return Path(configured)


def _ensure_upload_root(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.warning("Unable to create upload directory %s: %s", path, exc)
        return False


@login_required()
def index(request, conn=None, url=None, **kwargs):
    upload_root = _get_upload_root()
    return render(
        request,
        "omeroweb_upload/index.html",
        {
            "upload_root": str(upload_root),
            "upload_enabled": _ensure_upload_root(upload_root),
            "upload_url": reverse("omeroweb_upload_files"),
        },
    )


@csrf_exempt
@login_required()
def upload_files(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Upload endpoint expects POST."}, status=200)

    upload_root = _get_upload_root()
    if not _ensure_upload_root(upload_root):
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload folder is not writable. Please configure OMERO_WEB_UPLOAD_DIR.",
            },
            status=200,
        )

    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"ok": False, "error": "No files provided."}, status=200)

    saved = []
    errors = []
    for upload in files:
        filename = Path(upload.name).name
        target = upload_root / filename
        try:
            with target.open("wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            saved.append(filename)
        except OSError as exc:
            logger.warning("Failed to save upload %s: %s", filename, exc)
            errors.append(f"{filename}: {exc}")

    return JsonResponse({"ok": len(errors) == 0, "saved": saved, "errors": errors})
