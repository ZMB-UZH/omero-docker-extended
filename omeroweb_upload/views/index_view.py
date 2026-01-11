import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

import portalocker
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from omero.model import DatasetI
from omero.rtypes import rstring
from omeroweb.decorators import login_required

logger = logging.getLogger(__name__)

_IMPORT_LOCKS = {}
_IMPORT_LOCKS_GUARD = threading.Lock()

UPLOAD_ROOT_ENV = "OMERO_WEB_UPLOAD_DIR"
DEFAULT_UPLOAD_ROOT = "/opt/omero-upload-tmp"
JOBS_DIR_ENV = "OMERO_WEB_UPLOAD_JOBS_DIR"
DEFAULT_JOBS_DIR = "/tmp/omero_web_upload_jobs"
UPLOAD_CONCURRENCY_ENV = "OMERO_WEB_UPLOAD_CONCURRENCY"
UPLOAD_BATCH_FILES_ENV = "OMERO_WEB_UPLOAD_BATCH_FILES"
DEFAULT_UPLOAD_CONCURRENCY = 3
DEFAULT_UPLOAD_BATCH_FILES = 5
MAX_IMPORT_LOG_LINES = 1000
INT_SANITIZER = re.compile(r"[^0-9]")


def _current_username(request, conn):
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception:
        pass

    try:
        return request.user.username
    except Exception:
        return None


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
    try:
        with portalocker.Lock(path, "r", timeout=1) as handle:
            return json.load(handle)
    except (portalocker.exceptions.LockException, OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to lock or read job file %s: %s", path, exc)
    try:
        with path.open("r") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read job file %s without lock: %s", path, exc)
    return None


def _save_job(job_dict):
    path = _job_path(job_dict["job_id"])
    try:
        with portalocker.Lock(path, "w", timeout=1) as handle:
            json.dump(job_dict, handle)
        return True
    except (portalocker.exceptions.LockException, OSError) as exc:
        logger.warning("Unable to lock job file %s for writing: %s", path, exc)
    try:
        with path.open("w") as handle:
            json.dump(job_dict, handle)
        return True
    except OSError as exc:
        logger.warning("Unable to write job file %s without lock: %s", path, exc)
    return False


def _safe_relative_path(raw_name: str):
    if not raw_name or not isinstance(raw_name, str):
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


def _append_job_message(job: dict, message: str):
    if not message:
        return
    job.setdefault("messages", [])
    job["messages"].append(message)
    if len(job["messages"]) > MAX_IMPORT_LOG_LINES:
        job["messages"] = job["messages"][-MAX_IMPORT_LOG_LINES:]


def _append_job_error(job: dict, message: str):
    if not message:
        return
    job.setdefault("errors", [])
    job["errors"].append(message)
    if len(job["errors"]) > MAX_IMPORT_LOG_LINES:
        job["errors"] = job["errors"][-MAX_IMPORT_LOG_LINES:]


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


def _get_import_lock(username: str):
    key = username or "__default__"
    with _IMPORT_LOCKS_GUARD:
        lock = _IMPORT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _IMPORT_LOCKS[key] = lock
    return lock


def _process_import_job(job_id: str):
    job = _load_job(job_id)
    if not job:
        return

    try:
        username = job.get("username") or ""
        lock = _get_import_lock(username)

        with lock:
            job = _load_job(job_id)
            if not job:
                return

            if job.get("status") in ("done", "error"):
                return

            job.setdefault("errors", [])
            job.setdefault("messages", [])
            job["status"] = "importing"
            _save_job(job)

            session_key = job.get("session_key")
            host = job.get("host")
            port = job.get("port")
            if not session_key or not host or not port:
                job["status"] = "error"
                job["errors"].append("Missing OMERO connection details for import.")
                _save_job(job)
                return

            upload_root = _get_upload_root() / job_id
            if not upload_root.exists():
                job["status"] = "error"
                job["errors"].append("Upload folder missing on server.")
                _save_job(job)
                return

            dataset_map = job.get("dataset_map") or {}

            for entry in job.get("files", []):
                if entry.get("status") not in ("uploaded", "pending"):
                    continue

                rel_path = entry.get("relative_path")
                if not rel_path:
                    continue

                staged_path = entry.get("staged_path") or rel_path
                file_path = upload_root / staged_path
                if not file_path.exists():
                    error_msg = f"Missing staged file: {rel_path}"
                    entry["status"] = "error"
                    entry.setdefault("errors", []).append(error_msg)
                    _append_job_error(job, error_msg)
                    _append_job_message(job, error_msg)
                    _save_job(job)
                    continue

                dataset_name = _dataset_name_for_path(rel_path)
                dataset_id = dataset_map.get(dataset_name)

                success, stdout, stderr = _import_file(
                    conn=None,
                    session_key=session_key,
                    host=host,
                    port=port,
                    path=file_path,
                    dataset_id=dataset_id,
                )
                if not success:
                    logger.warning(
                        "Import failed for %s (stdout=%r, stderr=%r).",
                        rel_path,
                        stdout.strip(),
                        stderr.strip(),
                    )
                    error_msg = "Import failed. See server logs for details."
                    entry["status"] = "error"
                    entry.setdefault("errors", []).append(error_msg)
                    _append_job_error(job, f"{rel_path}: {error_msg}")
                    _append_job_message(job, f"{rel_path}: {error_msg}")
                    _save_job(job)
                    continue

                entry["status"] = "imported"
                job["imported_bytes"] = job.get("imported_bytes", 0) + entry.get("size", 0)
                _append_job_message(job, f"Imported {rel_path}")
                try:
                    file_path.unlink()
                except OSError as exc:
                    logger.warning("Failed to remove staged file %s: %s", file_path, exc)
                _save_job(job)

            job = _load_job(job_id) or job
            if job.get("errors"):
                job["status"] = "error"
            else:
                job["status"] = "done"
            _save_job(job)
    except Exception as exc:
        logger.exception("Import job %s failed unexpectedly.", job_id)
        job = _load_job(job_id) or {"job_id": job_id}
        _append_job_error(job, f"Unexpected import failure: {exc}")
        job["status"] = "error"
        _save_job(job)


def _start_import_thread(job_id: str):
    job = _load_job(job_id)
    if not job:
        return
    if job.get("status") != "ready":
        return
    if job.get("import_thread_started"):
        return

    job["import_thread_started"] = True
    _save_job(job)
    worker = threading.Thread(target=_process_import_job, args=(job_id,), daemon=True)
    worker.start()


# --------------------------------------------------------------------------
# VIEWS
# --------------------------------------------------------------------------

@login_required()
def index(request, conn=None, url=None, **kwargs):
    username = _current_username(request, conn)
    is_root_user = username == "root"
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
            "is_root_user": is_root_user,
        },
    )


@login_required()
def start_upload(request, conn=None, url=None, **kwargs):
    try:
        return _start_upload(request, conn)
    except Exception:
        logger.exception("Unhandled error while starting upload job.")
        return JsonResponse({"ok": False, "error": "Unexpected server error while starting upload."}, status=500)


def _start_upload(request, conn):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Upload start expects POST."}, status=200)

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root) or not _ensure_dir(_get_jobs_root()):
        logger.warning("Upload folder not writable or job dir missing.")
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
    if not isinstance(payload, dict):
        payload = {}

    files = payload.get("files") or []
    if not isinstance(files, list):
        files = []
    if not files:
        logger.info("Upload start request missing files payload.")
        return JsonResponse({"ok": False, "error": "No files provided."}, status=200)

    session_key = _get_session_key(conn)
    if not session_key:
        logger.warning("Unable to resolve OMERO session key for upload start.")
        return JsonResponse({"ok": False, "error": "Unable to resolve OMERO session."}, status=200)

    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        logger.warning("Unable to resolve OMERO host/port for upload start.")
        return JsonResponse({"ok": False, "error": "Unable to resolve OMERO host/port."}, status=200)

    normalized = []
    total_bytes = 0
    invalid = []

    for entry in files:
        if not isinstance(entry, dict):
            invalid.append(str(entry))
            continue
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
        upload_id = uuid.uuid4().hex
        filename = PurePosixPath(rel_path).name
        staged_path = f"_staged/{upload_id}/{filename}"
        total_bytes += size
        normalized.append(
            {
                "upload_id": upload_id,
                "relative_path": rel_path,
                "staged_path": staged_path,
                "size": size,
                "status": "pending",
                "errors": [],
            }
        )

    if invalid:
        logger.info("Upload start rejected invalid paths: %s", invalid)
        return JsonResponse(
            {"ok": False, "error": f"Invalid file paths: {', '.join(invalid)}."},
            status=200,
        )

    dataset_map = {}
    try:
        dataset_names = set()
        for entry in normalized:
            dataset_name = _dataset_name_for_path(entry["relative_path"])
            if dataset_name:
                dataset_names.add(dataset_name)
        for dataset_name in sorted(dataset_names):
            dataset_id = _get_or_create_dataset(conn, dataset_name, dataset_map)
            if dataset_id is None:
                logger.warning("Unable to resolve dataset for %s", dataset_name)
    except Exception:
        logger.exception("Unable to prepare datasets for upload request.")

    job_id = uuid.uuid4().hex
    username = _current_username(request, conn)
    job = {
        "job_id": job_id,
        "username": username,
        "session_key": session_key,
        "host": host,
        "port": port,
        "files": normalized,
        "total_bytes": total_bytes,
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "status": "uploading",
        "errors": [],
        "created": time.time(),
        "dataset_map": dataset_map,
        "import_index": 0,
        "messages": [],
        "import_thread_started": False,
    }
    _save_job(job)
    logger.info(
        "Upload job %s created for user %s with %d files (%d bytes).",
        job_id,
        username,
        len(normalized),
        total_bytes,
    )

    return JsonResponse(
        {
            "ok": True,
            "job_id": job_id,
            "upload_url": reverse("omeroweb_upload_files", kwargs={"job_id": job_id}),
            "import_step_url": reverse("omeroweb_upload_import_step", kwargs={"job_id": job_id}),
            "status_url": reverse("omeroweb_upload_status", kwargs={"job_id": job_id}),
        }
    )


@login_required()
def upload_files(request, job_id, conn=None, url=None, **kwargs):
    try:
        return _upload_files(request, job_id)
    except Exception:
        logger.exception("Unhandled error while uploading files for job %s.", job_id)
        return JsonResponse({"ok": False, "error": "Unexpected server error while uploading files."}, status=500)


def _upload_files(request, job_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Upload endpoint expects POST."}, status=200)

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root):
        logger.warning("Upload root not writable for job %s.", job_id)
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload folder is not writable. Please configure OMERO_WEB_UPLOAD_DIR.",
            },
            status=200,
        )

    job = _load_job(job_id)
    if not job:
        logger.warning("Upload job %s not found.", job_id)
        return JsonResponse({"ok": False, "error": "Upload job not found."}, status=200)

    files = request.FILES.getlist("files")
    if not files:
        logger.info("Upload job %s received no files.", job_id)
        return JsonResponse({"ok": False, "error": "No files provided."}, status=200)

    relative_paths = request.POST.getlist("relative_paths")
    if relative_paths and len(relative_paths) != len(files):
        logger.warning("Upload payload mismatch for job %s.", job_id)
        return JsonResponse(
            {
                "ok": False,
                "error": "Upload payload mismatch. Please retry the upload.",
            },
            status=200,
        )

    job_root = upload_root / job_id
    if not _ensure_dir(job_root):
        logger.warning("Unable to initialize upload folder for job %s.", job_id)
        return JsonResponse({"ok": False, "error": "Unable to initialize upload folder."}, status=200)

    saved = []
    errors = []
    entries_by_path = {}
    for file_entry in job["files"]:
        if file_entry.get("status") in ("pending", "error"):
            entries_by_path.setdefault(file_entry["relative_path"], []).append(file_entry)

    for index, upload in enumerate(files):
        raw_name = relative_paths[index] if relative_paths else upload.name
        rel_path = _safe_relative_path(raw_name)
        if rel_path is None:
            errors.append(f"Invalid filename: {raw_name}")
            continue

        entry_queue = entries_by_path.get(rel_path) or []
        if not entry_queue:
            errors.append(f"Unexpected file: {rel_path}")
            continue
        entry = entry_queue.pop(0)

        staged_path = entry.get("staged_path") or rel_path
        target = job_root / staged_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            saved.append(rel_path)
            entry["status"] = "uploaded"
        except OSError as exc:
            logger.warning("Failed to save upload %s: %s", rel_path, exc)
            errors.append(f"{rel_path}: {exc}")
            entry["status"] = "error"
            entry.setdefault("errors", []).append(str(exc))

    uploaded_bytes = 0
    for entry in job["files"]:
        if entry["status"] == "uploaded":
            uploaded_bytes += entry.get("size", 0)
    job["uploaded_bytes"] = uploaded_bytes
    if uploaded_bytes >= job.get("total_bytes", 0):
        job["status"] = "ready"

    _save_job(job)

    if job["status"] == "ready":
        _start_import_thread(job_id)
        logger.info("Upload job %s ready; import thread started.", job_id)

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


@login_required()
def import_step(request, job_id, conn=None, url=None, **kwargs):
    try:
        return _import_step(request, job_id)
    except Exception:
        logger.exception("Unhandled error while importing job %s.", job_id)
        return JsonResponse({"ok": False, "error": "Unexpected server error while importing."}, status=500)


def _import_step(request, job_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Import endpoint expects POST."}, status=200)

    job = _load_job(job_id)
    if not job:
        logger.warning("Import job %s not found.", job_id)
        return JsonResponse({"ok": False, "error": "Import job not found."}, status=200)

    if job.get("status") == "ready":
        _start_import_thread(job_id)
        job = _load_job(job_id) or job

    return JsonResponse(
        {
            "ok": True,
            "done": job.get("status") in ("done", "error"),
            "status": job.get("status"),
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
