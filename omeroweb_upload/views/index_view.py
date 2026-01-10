import json
import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path, PurePosixPath

import portalocker
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from omero.model import DatasetI
from omero.rtypes import rstring
from omeroweb.decorators import login_required

logger = logging.getLogger(__name__)

UPLOAD_ROOT_ENV = "OMERO_WEB_UPLOAD_DIR"
DEFAULT_UPLOAD_ROOT = "/opt/omero-upload-tmp"
JOBS_DIR_ENV = "OMERO_WEB_UPLOAD_JOBS_DIR"
DEFAULT_JOBS_DIR = "/tmp/omero_web_upload_jobs"
UPLOAD_CONCURRENCY_ENV = "OMERO_WEB_UPLOAD_CONCURRENCY"
UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"
DEFAULT_UPLOAD_CONCURRENCY = 3
DEFAULT_UPLOAD_BATCH_FILES = 5
INT_SANITIZER = re.compile(r"[^0-9]")


# --------------------------------------------------------------------------
# PATHS + JOB STORAGE
# --------------------------------------------------------------------------

def _get_upload_root() -> Path:
    configured = os.environ.get(UPLOAD_ROOT_ENV, DEFAULT_UPLOAD_ROOT)
    return Path(configured)


def _get_jobs_root() -> Path:
    configured = os.environ.get(JOBS_DIR_ENV, DEFAULT_JOBS_DIR)
    return Path(configured)


def _ensure_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.warning("Unable to create directory %s: %s", path, exc)
        return False


def _job_path(job_id: str) -> Path:
    return _get_jobs_root() / f"{job_id}.json"


def _get_env_int(env_key: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.environ.get(env_key, "")
    if raw:
        raw = INT_SANITIZER.sub("", str(raw))
    try:
        value = int(raw) if raw else default
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _load_job(job_id: str):
    path = _job_path(job_id)
    if not path.exists():
        return None
    with portalocker.Lock(path, "r", timeout=1) as handle:
        return json.load(handle)


def _save_job(job_dict):
    path = _job_path(job_dict["job_id"])
    with portalocker.Lock(path, "w", timeout=1) as handle:
        json.dump(job_dict, handle)


def _safe_relative_path(raw_name: str):
    if not raw_name:
        return None
    raw = raw_name.replace("\\", "/")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        return None
    parts = []
    for part in candidate.parts:
        if part in ("", ".", ".."):
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _dataset_name_for_path(relative_path: str):
    parts = PurePosixPath(relative_path).parts
    if len(parts) <= 1:
        return None
    return "\\".join(parts[:-1])


# --------------------------------------------------------------------------
# OMERO IMPORT HELPERS
# --------------------------------------------------------------------------

def _resolve_omero_host_port(conn):
    host = getattr(conn, "host", None) or getattr(conn, "_host", None)
    port = getattr(conn, "port", None) or getattr(conn, "_port", None)

    if not host:
        host = getattr(settings, "OMERO_HOST", None)
    if not port:
        port = getattr(settings, "OMERO_PORT", None)

    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None

    return host, port


def _get_session_key(conn):
    if callable(getattr(conn, "getSessionId", None)):
        try:
            return conn.getSessionId()
        except Exception:
            return None
    for attr in ("_sessionUuid", "_session"):
        val = getattr(conn, attr, None)
        if val:
            return val
    return None


def _get_or_create_dataset(conn, name: str, dataset_map: dict):
    if not name:
        return None
    if name in dataset_map:
        return dataset_map[name]

    existing = None
    try:
        existing = next(conn.getObjects("Dataset", attributes={"name": name}), None)
    except Exception:
        existing = None

    if existing is not None:
        dataset_id = existing.getId().getValue()
        dataset_map[name] = dataset_id
        return dataset_id

    try:
        dataset = DatasetI()
        dataset.setName(rstring(name))
        dataset = conn.getUpdateService().saveAndReturnObject(dataset)
        dataset_id = dataset.getId().getValue()
    except Exception as exc:
        logger.warning("Failed to create dataset %s: %s", name, exc)
        return None

    dataset_map[name] = dataset_id
    return dataset_id


def _import_file(conn, session_key: str, host: str, port: int, path: Path, dataset_id=None):
    cmd = ["omero", "import", "-k", session_key]
    if host:
        cmd.extend(["-s", host])
    if port:
        cmd.extend(["-p", str(port)])
    if dataset_id:
        cmd.extend(["-d", str(dataset_id)])
    cmd.append(str(path))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.stdout, result.stderr


def _verify_import(conn, file_name: str, dataset_id=None):
    if dataset_id:
        try:
            dataset = conn.getObject("Dataset", dataset_id)
            if dataset is None:
                return False
            for image in dataset.listChildren():
                if getattr(image, "getName", None) and image.getName() == file_name:
                    return True
        except Exception:
            return False
        return False

    try:
        for image in conn.getObjects("Image", attributes={"name": file_name}):
            if getattr(image, "getName", None) and image.getName() == file_name:
                return True
    except Exception:
        return False
    return False


# --------------------------------------------------------------------------
# VIEWS
# --------------------------------------------------------------------------

@login_required()
def index(request, conn=None, url=None, **kwargs):
    upload_root = _get_upload_root()
    upload_enabled = _ensure_dir(upload_root)
    job_dir_ok = _ensure_dir(_get_jobs_root())
    upload_concurrency = _get_env_int(UPLOAD_CONCURRENCY_ENV, DEFAULT_UPLOAD_CONCURRENCY, 1, 10)
    upload_batch_files = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 25)
    return render(
        request,
        "omeroweb_upload/index.html",
        {
            "upload_root": str(upload_root),
            "upload_enabled": upload_enabled and job_dir_ok,
            "upload_start_url": reverse("omeroweb_upload_start"),
            "upload_concurrency": upload_concurrency,
            "upload_batch_files": upload_batch_files,
        },
    )


@csrf_exempt
@login_required()
def start_upload(request, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Upload start expects POST."}, status=200)

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root) or not _ensure_dir(_get_jobs_root()):
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload folder is not writable. Please configure OMERO_WEB_UPLOAD_DIR.",
            },
            status=200,
        )

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}

    files = payload.get("files") or []
    if not files:
        return JsonResponse({"ok": False, "error": "No files provided."}, status=200)

    normalized = []
    total_bytes = 0
    invalid = []

    for entry in files:
        raw_name = entry.get("relative_path") or entry.get("name")
        size = entry.get("size")
        rel_path = _safe_relative_path(raw_name or "")
        if rel_path is None:
            invalid.append(raw_name)
            continue
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        if size < 0:
            size = 0
        total_bytes += size
        normalized.append(
            {
                "relative_path": rel_path,
                "size": size,
                "status": "pending",
                "errors": [],
            }
        )

    if invalid:
        return JsonResponse(
            {"ok": False, "error": f"Invalid file paths: {', '.join(invalid)}."},
            status=200,
        )

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "files": normalized,
        "total_bytes": total_bytes,
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "status": "uploading",
        "errors": [],
        "created": time.time(),
        "dataset_map": {},
        "import_index": 0,
        "messages": [],
    }
    _save_job(job)

    return JsonResponse(
        {
            "ok": True,
            "job_id": job_id,
            "upload_url": reverse("omeroweb_upload_files", kwargs={"job_id": job_id}),
            "import_step_url": reverse("omeroweb_upload_import_step", kwargs={"job_id": job_id}),
            "status_url": reverse("omeroweb_upload_status", kwargs={"job_id": job_id}),
        }
    )


@csrf_exempt
@login_required()
def upload_files(request, job_id, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Upload endpoint expects POST."}, status=200)

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root):
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload folder is not writable. Please configure OMERO_WEB_UPLOAD_DIR.",
            },
            status=200,
        )

    job = _load_job(job_id)
    if not job:
        return JsonResponse({"ok": False, "error": "Upload job not found."}, status=200)

    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"ok": False, "error": "No files provided."}, status=200)

    relative_paths = request.POST.getlist("relative_paths")
    if relative_paths and len(relative_paths) != len(files):
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload payload mismatch. Please retry the upload.",
            },
            status=200,
        )

    job_root = upload_root / job_id
    if not _ensure_dir(job_root):
        return JsonResponse({"ok": False, "error": "Unable to initialize upload folder."}, status=200)

    saved = []
    errors = []
    known_paths = {file_entry["relative_path"]: file_entry for file_entry in job["files"]}

    for index, upload in enumerate(files):
        raw_name = relative_paths[index] if relative_paths else upload.name
        rel_path = _safe_relative_path(raw_name)
        if rel_path is None:
            errors.append(f"Invalid filename: {raw_name}")
            continue

        if rel_path not in known_paths:
            errors.append(f"Unexpected file: {rel_path}")
            continue

        target = job_root / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            saved.append(rel_path)
            known_paths[rel_path]["status"] = "uploaded"
        except OSError as exc:
            logger.warning("Failed to save upload %s: %s", rel_path, exc)
            errors.append(f"{rel_path}: {exc}")
            known_paths[rel_path]["status"] = "error"
            known_paths[rel_path]["errors"].append(str(exc))

    uploaded_bytes = 0
    for entry in job["files"]:
        if entry["status"] == "uploaded":
            uploaded_bytes += entry.get("size", 0)
    job["uploaded_bytes"] = uploaded_bytes
    if uploaded_bytes >= job.get("total_bytes", 0):
        job["status"] = "ready"

    _save_job(job)

    return JsonResponse(
        {
            "ok": len(errors) == 0,
            "saved": saved,
            "errors": errors,
            "error": errors[0] if errors else None,
            "uploaded_bytes": job["uploaded_bytes"],
            "total_bytes": job.get("total_bytes", 0),
            "ready": job["status"] == "ready",
        }
    )


@csrf_exempt
@login_required()
def import_step(request, job_id, conn=None, url=None, **kwargs):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Import endpoint expects POST."}, status=200)

    job = _load_job(job_id)
    if not job:
        return JsonResponse({"ok": False, "error": "Import job not found."}, status=200)

    if job.get("status") not in ("ready", "importing", "error"):
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload is not ready for import.",
                "status": job.get("status"),
            },
            status=200,
        )

    session_key = _get_session_key(conn)
    if not session_key:
        return JsonResponse({"ok": False, "error": "Unable to resolve OMERO session."}, status=200)

    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        return JsonResponse({"ok": False, "error": "Unable to resolve OMERO host/port."}, status=200)

    upload_root = _get_upload_root() / job_id
    if not upload_root.exists():
        return JsonResponse({"ok": False, "error": "Upload folder missing on server."}, status=200)

    if job.get("status") != "importing":
        job["status"] = "importing"

    files = job.get("files", [])
    next_entry = None
    for entry in files:
        if entry.get("status") in ("uploaded", "pending"):
            next_entry = entry
            break

    if next_entry is None:
        job["status"] = "done" if not job["errors"] else "error"
        _save_job(job)
        return JsonResponse(
            {
                "ok": True,
                "done": True,
                "status": job["status"],
                "imported_bytes": job.get("imported_bytes", 0),
                "total_bytes": job.get("total_bytes", 0),
                "messages": job.get("messages", []),
            }
        )

    rel_path = next_entry["relative_path"]
    file_path = upload_root / rel_path
    dataset_name = _dataset_name_for_path(rel_path)
    dataset_map = job.setdefault("dataset_map", {})
    dataset_id = _get_or_create_dataset(conn, dataset_name, dataset_map)

    if not file_path.exists():
        error_msg = f"Missing staged file: {rel_path}"
        next_entry["status"] = "error"
        next_entry["errors"].append(error_msg)
        job["errors"].append(error_msg)
        job["messages"].append(error_msg)
        _save_job(job)
        return JsonResponse(
            {
                "ok": False,
                "error": error_msg,
                "status": job["status"],
                "messages": job.get("messages", []),
            }
        )

    success, stdout, stderr = _import_file(conn, session_key, host, port, file_path, dataset_id)
    if not success:
        error_msg = stderr.strip() or stdout.strip() or "Import failed."
        next_entry["status"] = "error"
        next_entry["errors"].append(error_msg)
        job["errors"].append(f"{rel_path}: {error_msg}")
        job["messages"].append(f"{rel_path}: {error_msg}")
        _save_job(job)
        return JsonResponse(
            {
                "ok": False,
                "error": error_msg,
                "status": job["status"],
                "messages": job.get("messages", []),
            }
        )

    verified = _verify_import(conn, file_path.name, dataset_id)
    if not verified:
        error_msg = "Import completed but verification failed."
        next_entry["status"] = "error"
        next_entry["errors"].append(error_msg)
        job["errors"].append(f"{rel_path}: {error_msg}")
        job["messages"].append(f"{rel_path}: {error_msg}")
    else:
        next_entry["status"] = "imported"
        job["imported_bytes"] = job.get("imported_bytes", 0) + next_entry.get("size", 0)
        job["messages"].append(f"Imported {rel_path}")
        try:
            file_path.unlink()
        except OSError as exc:
            logger.warning("Failed to remove staged file %s: %s", file_path, exc)

    _save_job(job)

    return JsonResponse(
        {
            "ok": verified,
            "done": False,
            "status": job["status"],
            "imported_bytes": job.get("imported_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "messages": job.get("messages", []),
        }
    )


@login_required()
def job_status(request, job_id, conn=None, url=None, **kwargs):
    job = _load_job(job_id)
    if not job:
        return JsonResponse({"ok": False, "error": "Upload job not found."}, status=200)

    return JsonResponse(
        {
            "ok": True,
            "status": job.get("status"),
            "uploaded_bytes": job.get("uploaded_bytes", 0),
            "imported_bytes": job.get("imported_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "errors": job.get("errors", []),
            "messages": job.get("messages", []),
        }
    )
