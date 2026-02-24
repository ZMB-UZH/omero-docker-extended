"""
Upload plugin views.
"""
# Import all helper functions from core_functions
from .core_functions import *
from .utils import require_non_root_user

@login_required()
@require_non_root_user
def index(request, conn=None, url=None, **kwargs):
    try:
        _cleanup_upload_artifacts()
    except Exception:
        logger.exception("Upload cleanup failed.")
    username = current_username(request, conn)
    user_id = _current_user_id(conn)
    upload_root = _get_upload_root()
    upload_enabled = _ensure_dir(upload_root)
    job_dir_ok = _ensure_dir(_get_jobs_root())
    upload_concurrency = _get_env_int(UPLOAD_CONCURRENCY_ENV, DEFAULT_UPLOAD_CONCURRENCY, 1, 10)
    upload_batch_files = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10)
    projects = _collect_project_payload(conn, user_id)
    special_methods_enabled = _special_methods_enabled()
    return render(
        request,
        "omeroweb_upload/index.html",
        {
            "upload_root": str(upload_root),
            "upload_enabled": upload_enabled and job_dir_ok,
            "upload_start_url": reverse("omeroweb_upload_start"),
            "upload_concurrency": upload_concurrency,
            "upload_batch_files": upload_batch_files,
            "special_methods_enabled": special_methods_enabled,
            "user_id": user_id,
            "messages_json": json.dumps(messages.index_messages()),
            "projects": projects,
            "project_list_url": reverse("omeroweb_upload_projects"),
        },
    )


@login_required()
@require_non_root_user
def list_projects(request, conn=None, url=None, **kwargs):
    user_id = _current_user_id(conn)
    payload = _collect_project_payload(conn, user_id)
    return JsonResponse(payload)


@login_required()
@require_non_root_user
def root_status(request, conn=None, url=None, **kwargs):
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})


@login_required()
@require_non_root_user
def start_upload(request, conn=None, url=None, **kwargs):
    try:
        return _start_upload(request, conn)
    except Exception:
        logger.exception("Unhandled error while starting upload job.")
        return json_error(errors.unexpected_server_error_start_upload(), status=500)


def _start_upload(request, conn):
    try:
        _cleanup_upload_artifacts()
    except Exception:
        logger.exception("Upload cleanup failed.")
    if request.method != "POST":
        return json_error(errors.upload_start_post_required())

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root) or not _ensure_dir(_get_jobs_root()):
        logger.warning("Upload folder not writable or job dir missing.")
        return json_error(errors.upload_folder_not_writable())

    payload = load_json_body(request)
    if not isinstance(payload, dict):
        payload = {}

    raw_project_id = (payload.get("project_id") or "").strip()
    project_id = None
    project_name = ""
    if raw_project_id:
        try:
            project_id = int(raw_project_id)
        except (TypeError, ValueError):
            return json_error(errors.invalid_project_selection(), status=400)
        try:
            project = conn.getObject("Project", project_id)
        except Exception:
            project = None
        if project is None or not (
            _is_owned_by_user(project, _current_user_id(conn)) or _has_read_write_permissions(project)
        ):
            return json_error(errors.invalid_project_selection(), status=400)
        project_name = _get_text(project.getName())

    files = payload.get("files") or []
    if not isinstance(files, list):
        files = []
    if not files:
        logger.info("Upload start request missing files payload.")
        return json_error(errors.no_files_provided())
    special_upload = (payload.get("special_upload") or "").strip()
    compatibility_enabled = payload.get("compatibility_enabled")
    if compatibility_enabled is None:
        compatibility_enabled = True
    else:
        compatibility_enabled = bool(compatibility_enabled)
    raw_sem_edx_associations = payload.get("sem_edx_associations") or {}
    raw_sem_edx_settings = payload.get("sem_edx_settings") or {}
    if not _special_methods_enabled():
        special_upload = ""
        raw_sem_edx_associations = {}
        raw_sem_edx_settings = {}
    if special_upload != "sem_edx_spectra":
        raw_sem_edx_associations = {}
        raw_sem_edx_settings = {}
    default_batch_size = _get_env_int(UPLOAD_BATCH_FILES_ENV, DEFAULT_UPLOAD_BATCH_FILES, 1, 10)
    batch_size = _normalize_job_batch_size(payload.get("batch_size"), default_batch_size)

    session_key = _get_session_key(conn)
    if not session_key:
        logger.warning("Unable to resolve OMERO session key for upload start.")
        return json_error(errors.unable_resolve_session())

    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        logger.warning("Unable to resolve OMERO host/port for upload start.")
        return json_error(errors.unable_resolve_host_port())

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
        compatibility_skip = bool(entry.get("compatibility_skip"))
        import_skip = bool(entry.get("import_skip"))

        filename = PurePosixPath(rel_path).name

        # SEM-EDX: TXT files must NEVER be imported or compatibility-checked
        if special_upload == "sem_edx_spectra" and filename.lower().endswith(".txt"):
            import_skip = True
            compatibility_skip = True

        # Auto-skip OS junk files (Thumbs.db, .DS_Store, macOS resource
        # forks, lost+found contents, etc.).  All other files are left to OMERO.
        if _should_auto_skip_import(rel_path):
            import_skip = True
            compatibility_skip = True

        staged_path = f"_staged/{upload_id}/{filename}"

        total_bytes += size
        if total_bytes > MAX_UPLOAD_BATCH_BYTES:
            logger.info(
                "Upload start rejected batch exceeding %d GB for user %s.",
                MAX_UPLOAD_BATCH_GB,
                current_username(request, conn),
            )
            return json_error(errors.upload_batch_too_large(MAX_UPLOAD_BATCH_GB))
        normalized.append(
            {
                "upload_id": upload_id,
                "relative_path": rel_path,
                "staged_path": staged_path,
                "size": size,
                "status": "pending",
                "errors": [],
                "compatibility_skip": compatibility_skip,
                "import_skip": import_skip,
            }
        )

    if invalid:
        logger.info("Upload start rejected invalid paths: %s", invalid)
        return json_error(errors.invalid_file_paths(invalid))

    sem_edx_associations = _normalize_sem_edx_associations(raw_sem_edx_associations, normalized)
    sem_edx_settings = (
        _normalize_sem_edx_settings(raw_sem_edx_settings)
        if special_upload == "sem_edx_spectra"
        else {}
    )

    dataset_map = {}
    orphan_dataset_name = None
    try:
        dataset_names = set()
        if any(_dataset_name_for_path(entry["relative_path"]) is None for entry in normalized):
            orphan_dataset_name = _generate_orphan_dataset_name()
        for entry in normalized:
            dataset_name = _dataset_name_for_path(entry["relative_path"], orphan_dataset_name)
            if dataset_name:
                dataset_names.add(dataset_name)
        for dataset_name in sorted(dataset_names):
            dataset_id = _get_or_create_dataset(conn, dataset_name, dataset_map, project_id=project_id)
            if dataset_id is None:
                logger.warning("Unable to resolve dataset for %s", dataset_name)
    except Exception:
        logger.exception("Unable to prepare datasets for upload request.")

    job_id = uuid.uuid4().hex
    username = current_username(request, conn)
    current_group_id = None
    try:
        # CRITICAL FIX: Get the user's actual group, not -1 (all groups)
        # The -1 group causes OptimisticLockException when job-service tries to save annotations
        event_context = conn.getEventContext()
        current_group_id = event_context.groupId
        logger.debug("Captured user's group_id: %s for user: %s", current_group_id, username)
    except Exception as exc:
        logger.warning("Unable to get user's group context: %s", exc)
        current_group_id = None
    job = {
        "job_id": job_id,
        "username": username,
        "session_key": session_key,
        "group_id": current_group_id,
        "host": host,
        "port": port,
        "project_id": project_id,
        "project_name": project_name,
        "files": normalized,
        "total_bytes": total_bytes,
        "uploaded_bytes": 0,
        "imported_bytes": 0,
        "status": "uploading",
        "errors": [],
        "created": time.time(),
        "dataset_map": dataset_map,
        "orphan_dataset_name": orphan_dataset_name,
        "import_index": 0,
        "messages": [],
        "import_thread_started": False,
        "job_batch_size": batch_size,
        "compatibility_status": "pending",
        "compatibility_enabled": compatibility_enabled,
        "incompatible_files": [],
        "compatibility_thread_active": False,
        "compatibility_confirmed": False,
        "special_upload": special_upload,
        "sem_edx_associations": sem_edx_associations,
        "sem_edx_settings": sem_edx_settings,
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
            "confirm_url": reverse("omeroweb_upload_confirm", kwargs={"job_id": job_id}),
            "prune_url": reverse("omeroweb_upload_prune", kwargs={"job_id": job_id}),
        }
    )


@login_required()
@require_non_root_user
def upload_files(request, job_id, conn=None, url=None, **kwargs):
    try:
        return _upload_files(request, job_id)
    except Exception:
        logger.exception("Unhandled error while uploading files for job %s.", job_id)
        return json_error(errors.unexpected_server_error_uploading_files(), status=500)


def _upload_files(request, job_id):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.upload_endpoint_post_required())

    upload_root = _get_upload_root()
    if not _ensure_dir(upload_root):
        logger.warning("Upload root not writable for job %s.", job_id)
        return json_error(errors.upload_folder_not_writable())

    job = _load_job(job_id)
    if not job:
        logger.warning("Upload job %s not found.", job_id)
        return json_error(errors.upload_job_not_found())

    files = request.FILES.getlist("files")
    if not files:
        logger.info("Upload job %s received no files.", job_id)
        return json_error(errors.no_files_provided())

    relative_paths = request.POST.getlist("relative_paths")
    if relative_paths and len(relative_paths) != len(files):
        logger.warning("Upload payload mismatch for job %s.", job_id)
        return json_error(errors.upload_payload_mismatch())

    job_root = upload_root / job_id
    if not _ensure_dir(job_root):
        logger.warning("Unable to initialize upload folder for job %s.", job_id)
        return json_error(errors.unable_initialize_upload_folder())

    saved = []
    upload_errors = []
    entries_by_path = {}
    updates = []
    for file_entry in job["files"]:
        if file_entry.get("status") in ("pending", "error"):
            entries_by_path.setdefault(file_entry["relative_path"], []).append(file_entry)

    for index, upload in enumerate(files):
        raw_name = relative_paths[index] if relative_paths else upload.name
        rel_path = _safe_relative_path(raw_name)
        if rel_path is None:
            upload_errors.append(errors.invalid_filename(raw_name))
            continue

        entry_queue = entries_by_path.get(rel_path) or []
        if not entry_queue:
            upload_errors.append(errors.unexpected_file(rel_path))
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
            updates.append({"upload_id": entry.get("upload_id"), "status": "uploaded"})
        except OSError as exc:
            logger.warning("Failed to save upload %s: %s", rel_path, exc)
            upload_errors.append(f"{rel_path}: {exc}")
            entry["status"] = "error"
            entry.setdefault("errors", []).append(str(exc))
            updates.append(
                {"upload_id": entry.get("upload_id"), "status": "error", "errors": [str(exc)]}
            )

    updated_job = _apply_upload_updates(job_id, updates, upload_errors)
    if not updated_job:
        return json_error(errors.unable_update_upload_job_state())

    if _should_start_compatibility_check(updated_job):
        _start_compatibility_check_thread(job_id)
        logger.info("Upload job %s checking compatibility.", job_id)
    if updated_job["status"] == "ready":
        _start_import_thread(job_id)
        logger.info("Upload job %s ready; import thread started.", job_id)

    return JsonResponse(
        {
            "ok": len(upload_errors) == 0,
            "saved": saved,
            "errors": upload_errors,
            "error": upload_errors[0] if upload_errors else None,
            "uploaded_bytes": updated_job.get("uploaded_bytes", 0),
            "total_bytes": updated_job.get("total_bytes", 0),
            "ready": updated_job.get("status") == "ready",
        }
    )


@login_required()
@require_non_root_user
def import_step(request, job_id, conn=None, url=None, **kwargs):
    try:
        return _import_step(request, job_id)
    except Exception:
        logger.exception("Unhandled error while importing job %s.", job_id)
        return json_error(errors.unexpected_server_error_importing(), status=500)


def _import_step(request, job_id):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.import_endpoint_post_required())

    job = _load_job(job_id)
    if not job:
        logger.warning("Import job %s not found.", job_id)
        return json_error(errors.import_job_not_found())

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
@require_non_root_user
def confirm_import(request, job_id, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.method_post_required())

    job = _load_job(job_id)
    if not job:
        return json_error(errors.upload_job_not_found())

    if job.get("status") != "awaiting_confirmation":
        return JsonResponse({"ok": True, "status": job.get("status")})

    job["compatibility_confirmed"] = True
    job["compatibility_thread_active"] = False
    job["status"] = "ready"
    job["updated"] = time.time()
    _save_job(job)
    _start_import_thread(job_id)

    return JsonResponse({"ok": True, "status": "ready"})


@login_required()
@require_non_root_user
def prune_upload(request, job_id, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    if request.method != "POST":
        return json_error(errors.method_post_required())

    job = _load_job(job_id)
    if not job:
        return json_error(errors.upload_job_not_found())

    payload = load_json_body(request)
    if not isinstance(payload, dict):
        payload = {}

    keep_paths = payload.get("keep_paths") or []
    if not isinstance(keep_paths, list):
        keep_paths = []

    keep_set = set()
    for path in keep_paths:
        rel_path = _safe_relative_path(path)
        if rel_path:
            keep_set.add(rel_path)

    upload_root = _get_upload_root() / job_id

    def apply_prune(job_dict):
        removed = []
        kept_entries = []
        for entry in job_dict.get("files", []):
            rel_path = entry.get("relative_path")
            if not rel_path or rel_path not in keep_set:
                removed.append(entry)
                continue
            kept_entries.append(entry)

        for entry in removed:
            staged_path = entry.get("staged_path") or entry.get("relative_path")
            if not staged_path:
                continue
            file_path = upload_root / staged_path
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError as exc:
                logger.warning("Failed to remove staged file %s: %s", file_path, exc)

        job_dict["files"] = kept_entries
        job_dict["total_bytes"] = sum(entry.get("size", 0) for entry in kept_entries)
        job_dict["uploaded_bytes"] = sum(
            entry.get("size", 0) for entry in kept_entries if entry.get("status") == "uploaded"
        )
        job_dict["incompatible_files"] = sorted(
            entry.get("relative_path")
            for entry in kept_entries
            if entry.get("compatibility") == "incompatible" and entry.get("relative_path")
        )

        pending_after = _compatibility_pending_entries(job_dict)
        has_errors = any(entry.get("compatibility") == "error" for entry in kept_entries)
        if job_dict["incompatible_files"]:
            job_dict["compatibility_status"] = "incompatible"
        elif pending_after:
            job_dict["compatibility_status"] = "checking"
        elif has_errors:
            job_dict["compatibility_status"] = "error"
        else:
            job_dict["compatibility_status"] = "compatible"
        _refresh_job_status(job_dict)
        job_dict["updated"] = time.time()
        return job_dict

    job = _update_job(job_id, apply_prune)
    if not job:
        return json_error(errors.unable_update_upload_job_state())

    if job.get("status") == "ready":
        _start_import_thread(job_id)

    return JsonResponse({"ok": True, "status": job.get("status")})


@login_required()
@require_non_root_user
def job_status(request, job_id, conn=None, url=None, **kwargs):
    _cleanup_upload_artifacts()
    job = _load_job(job_id)
    if not job:
        return json_error(errors.upload_job_not_found())

    return JsonResponse(
        {
            "ok": True,
            "status": job.get("status"),
            "uploaded_bytes": job.get("uploaded_bytes", 0),
            "imported_bytes": job.get("imported_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "errors": job.get("errors", []),
            "messages": job.get("messages", []),
            "compatibility_status": job.get("compatibility_status"),
            "compatibility_enabled": bool(job.get("compatibility_enabled", True)),
            "compatibility_checked": sum(
                1 for f in job.get("files", []) if f.get("compatibility")
            ),
            "compatibility_total": sum(
                1
                for f in job.get("files", [])
                if f.get("status") == "uploaded" and not f.get("compatibility_skip")
            ),
            "incompatible_files": job.get("incompatible_files", []),
            "confirmation_required": job.get("status") == "awaiting_confirmation",
        }
    )
