from django.conf import settings
from django.http import JsonResponse
from omeroweb.decorators import login_required
from omero_plugin_common.logging_utils import sanitize_log_value, sanitized_exc_info
import time
import uuid
import logging
import portalocker
import re
import omero

from omero.model import ImageI, MapAnnotationI, NamedValue, ImageAnnotationLinkI
from omero.rtypes import rstring

from ..constants import CHUNK_SIZE, MAP_NS, HASH_KEY

from ..services.core import (
    load_job,
    save_job,
    _job_lock_path,
    mark_job_lock_held,
    collect_images_in_project,
    get_id,
    get_text,
    parse_filename,
    fetch_images_by_ids,
    compute_plugin_hash,
    delete_existing_annotations,
    extract_acquisition_metadata,
)
from ..services.parsing.filename_parser import is_supported_separator_pattern
from ..services.rate_limit import (
    build_rate_limit_message,
    check_major_action_rate_limit,
)
from ..views.utils import current_username, load_request_data, require_non_root_user
from ..strings import errors as error_messages

logger = logging.getLogger(__name__)


def _is_safe_separator_regex(pattern):
    """Return whether safe separator regex.

    Inputs: `pattern`. Output: `is_supported_separator_pattern` result.
    """
    return is_supported_separator_pattern(pattern)


def _job_owned_by_request(job, request, conn):
    """Return the job owned by request.

    Inputs: `job`, `request` Django request, `conn` OMERO gateway connection. Output:
    `bool`.
    """
    if not isinstance(job, dict):
        return False
    job_username = str(job.get("username") or "").strip()
    if not job_username:
        return False
    username = str(current_username(request, conn) or "").strip()
    return bool(username and job_username == username)


def parse_image_ids(raw_ids):
    """Parse and validate the image IDs input.

    Inputs: `raw_ids`. Output: `image_ids`.
    """
    if not raw_ids:
        return []
    image_ids = []
    if isinstance(raw_ids, str):
        raw_list = [val.strip() for val in raw_ids.split(",") if val.strip()]
    elif isinstance(raw_ids, (list, tuple, set)):
        raw_list = list(raw_ids)
    else:
        raw_list = []
    for val in raw_list:
        try:
            image_ids.append(int(val))
        except (TypeError, ValueError):
            continue
    return image_ids


def _resolve_omero_host_port(conn):
    """Resolve the OMERO host port.

    Inputs: `conn` OMERO gateway connection. Output: `tuple`.
    """
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


def _validate_user_password(conn, password):
    """Validate the user password.

    Inputs: `conn` OMERO gateway connection, `password` password. Output: `tuple`.
    """
    if not password:
        return False, error_messages.missing_password()

    username = conn.getUser().getName()
    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        logger.error(
            "Unable to resolve OMERO host/port for re-authentication (host=%s, port=%s).",
            host,
            port,
        )
        return False, error_messages.validation_unavailable()

    client = omero.client(host=host, port=port)
    try:
        client.createSession(username, password)
    except Exception as exc:
        logger.warning(
            "Re-authentication failed for user %s: %s",
            sanitize_log_value(username),
            sanitize_log_value(exc),
        )
        return False, error_messages.wrong_password()
    finally:
        try:
            client.closeSession()
        except Exception as exc:
            logger.debug("Suppressed non-fatal exception in job_view.py", exc_info=exc)

    return True, None


def _image_ids_from_objects(images):
    """Extract numeric image IDs from OMERO image-like objects.

    Inputs: `images`. Output: `image_ids`.
    """
    seen = set()
    image_ids = []
    for img in images:
        raw_iid = get_id(img)
        if raw_iid is None:
            continue
        try:
            iid = int(raw_iid)
        except (TypeError, ValueError):
            continue
        if iid not in seen:
            seen.add(iid)
            image_ids.append(iid)

    image_ids.sort()
    return image_ids


def _resolve_image_ids(conn, project_id, selected_image_ids):
    """Resolve the image IDs.

    Inputs: `conn` OMERO gateway connection, `project_id` OMERO project ID,
    `selected_image_ids`. Output: `_image_ids_from_objects` result.
    """
    images = collect_images_in_project(conn, project_id)
    project_image_ids = _image_ids_from_objects(images)
    if selected_image_ids:
        allowed_project_image_ids = set(project_image_ids)
        selected = set()
        for raw_iid in selected_image_ids:
            try:
                iid = int(raw_iid)
            except (TypeError, ValueError):
                continue
            if iid in allowed_project_image_ids:
                selected.add(iid)
        return sorted(selected)

    return project_image_ids


def _save_annotation_link(update, link):
    """Save the annotation link.

    Inputs: `update`, `link`. Output: `bool`.
    """
    saved_link = update.saveAndReturnObject(link)
    if saved_link is None:
        return False
    return bool(get_id(saved_link))


def _unique_annotation_key(existing_mapping, base_key):
    """Return the unique annotation key.

    Inputs: `existing_mapping`, `base_key`. Output: `key`.
    """
    key_root = str(base_key or "").strip() or "Var"
    key = key_root
    suffix = 2
    while key == HASH_KEY or key in existing_mapping:
        key = f"{key_root}_{suffix}"
        suffix += 1
    return key


def _with_plugin_hash(mapping):
    """Return the with plugin hash.

    Inputs: `mapping`. Output: `annotation_mapping`.
    """
    annotation_mapping = dict(mapping)
    if annotation_mapping:
        annotation_mapping[HASH_KEY] = compute_plugin_hash(annotation_mapping)
    return annotation_mapping


def _save_image_map_annotation(update, img, mapping):
    """Save the image map annotation.

    Inputs: `update`, `img`, `mapping`. Output: `_save_annotation_link` result.
    """
    image_id = get_id(img)
    if image_id is None:
        return False
    try:
        image_parent = ImageI(int(image_id), False)
    except (TypeError, ValueError, OverflowError):
        return False

    ann = MapAnnotationI()
    ann.setNs(rstring(MAP_NS))
    ann.setMapValue([NamedValue(k, v) for k, v in mapping.items()])

    link = ImageAnnotationLinkI()
    link.setParent(image_parent)
    link.setChild(ann)
    return _save_annotation_link(update, link)


# ==============================================================================
# START JOB
# ==============================================================================
@login_required()
@require_non_root_user
def start_job(request, conn=None, _url=None, **kwargs):
    """Start the job.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    try:
        if request.method != "POST":
            return JsonResponse(
                {"error": error_messages.method_post_required()}, status=400
            )

        data = load_request_data(request)

        project_id = data.get("project_id")
        raw_seps = data.get("separator", "_")
        separator_mode = data.get("separator_mode", "chars")
        var_names = data.get("var_names") or []
        delete_mode = data.get("delete_mode")
        selected_image_ids = parse_image_ids(data.get("image_ids"))

        # Read user's chunk size
        user_chunk_size = data.get("chunk_size")
        try:
            chunk_size = int(user_chunk_size) if user_chunk_size else CHUNK_SIZE
            if chunk_size < 1 or chunk_size > 100:
                chunk_size = CHUNK_SIZE
        except (ValueError, TypeError):
            chunk_size = CHUNK_SIZE

        if separator_mode not in ("chars", "regex", "ai_regex"):
            separator_mode = "chars"

        if separator_mode in ("regex", "ai_regex") and not _is_safe_separator_regex(
            raw_seps
        ):
            return JsonResponse(
                {"error": error_messages.invalid_regex_pattern_title()},
                status=400,
            )

        if delete_mode not in ("keep", "all", "plugin"):
            delete_mode = "keep"

        if not project_id:
            return JsonResponse(
                {"error": error_messages.missing_project_id_lower()}, status=400
            )

        image_ids = _resolve_image_ids(conn, project_id, selected_image_ids)
        if not image_ids:
            return JsonResponse({"error": error_messages.no_images_found()}, status=400)

        if delete_mode in ("all", "plugin"):
            valid, error = _validate_user_password(conn, data.get("password"))
            if not valid:
                return JsonResponse({"error": error}, status=403)

        allowed, remaining = check_major_action_rate_limit(request, conn)
        if not allowed:
            return JsonResponse(
                {"error": build_rate_limit_message(remaining)},
                status=429,
            )

        job_id = uuid.uuid4().hex

        # Preserve user-selected parsing and deletion settings.
        job = {
            "job_id": job_id,
            "username": current_username(request, conn),
            "project_id": int(project_id),
            "separator": raw_seps,
            "var_names": var_names,
            "delete_mode": delete_mode,
            "image_ids": image_ids,
            "total": len(image_ids),
            "index": 0,
            "started": time.time(),
            "separator_mode": separator_mode,
            "chunk_size": chunk_size,
        }

        save_job(job)

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.error(
            "start_job() error: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": error_messages.unexpected_error()}, status=500)


@login_required()
@require_non_root_user
def start_acq_job(request, conn=None, _url=None, **kwargs):
    """Start the acq job.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    try:
        if request.method != "POST":
            return JsonResponse(
                {"error": error_messages.method_post_required()}, status=400
            )

        data = load_request_data(request)

        project_id = data.get("project_id")
        selected_image_ids = parse_image_ids(data.get("image_ids"))

        # Read user's chunk size
        user_chunk_size = data.get("chunk_size")
        try:
            chunk_size = int(user_chunk_size) if user_chunk_size else CHUNK_SIZE
            if chunk_size < 1 or chunk_size > 100:
                chunk_size = CHUNK_SIZE
        except (ValueError, TypeError):
            chunk_size = CHUNK_SIZE

        if not project_id:
            return JsonResponse(
                {"error": error_messages.missing_project_id_lower()}, status=400
            )
        image_ids = _resolve_image_ids(conn, project_id, selected_image_ids)

        allowed, remaining = check_major_action_rate_limit(request, conn)
        if not allowed:
            return JsonResponse(
                {"error": build_rate_limit_message(remaining)},
                status=429,
            )

        job_id = uuid.uuid4().hex

        job = {
            "job_id": job_id,
            "username": current_username(request, conn),
            "type": "acq",  # <-- DO NOT CHANGE THIS
            "project_id": int(project_id),
            "image_ids": image_ids,
            "total": len(image_ids),
            "index": 0,
            "started": time.time(),
            # ensure keys expected by job_progress also exist for acq jobs
            "separator": "",
            "var_names": [],
            "delete_mode": "keep",
            "chunk_size": chunk_size,
        }

        save_job(job)

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.error(
            "start_acq_job() error: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": error_messages.unexpected_error()}, status=500)


@login_required()
@require_non_root_user
def start_delete_all_job(request, conn=None, _url=None, **kwargs):
    """Start the delete all job.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    try:
        if request.method != "POST":
            return JsonResponse(
                {"error": error_messages.method_post_required()}, status=400
            )

        data = load_request_data(request)

        project_id = data.get("project_id")
        selected_image_ids = parse_image_ids(data.get("image_ids"))
        password = data.get("password")

        # Read user's chunk size
        user_chunk_size = data.get("chunk_size")
        try:
            chunk_size = int(user_chunk_size) if user_chunk_size else CHUNK_SIZE
            if chunk_size < 1 or chunk_size > 100:
                chunk_size = CHUNK_SIZE
        except (ValueError, TypeError):
            chunk_size = CHUNK_SIZE

        if not project_id:
            return JsonResponse(
                {"error": error_messages.missing_project_id_lower()}, status=400
            )

        valid, error = _validate_user_password(conn, password)
        if not valid:
            return JsonResponse({"error": error}, status=403)

        image_ids = _resolve_image_ids(conn, project_id, selected_image_ids)

        allowed, remaining = check_major_action_rate_limit(request, conn)
        if not allowed:
            return JsonResponse(
                {"error": build_rate_limit_message(remaining)},
                status=429,
            )

        job_id = uuid.uuid4().hex

        job = {
            "job_id": job_id,
            "username": current_username(request, conn),
            "type": "del_all",
            "project_id": int(project_id),
            "image_ids": image_ids,
            "total": len(image_ids),
            "index": 0,
            "started": time.time(),
            # ensure keys expected by job_progress also exist
            "separator": "",
            "var_names": [],
            "delete_mode": "all",
            "chunk_size": chunk_size,
        }

        save_job(job)

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.error(
            "start_delete_all_job() error: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": error_messages.unexpected_error()}, status=500)


@login_required()
@require_non_root_user
def start_delete_plugin_job(request, conn=None, _url=None, **kwargs):
    """Start the delete plugin job.

    Inputs: `request` Django request, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    try:
        if request.method != "POST":
            return JsonResponse(
                {"error": error_messages.method_post_required()}, status=400
            )

        data = load_request_data(request)

        project_id = data.get("project_id")
        selected_image_ids = parse_image_ids(data.get("image_ids"))
        password = data.get("password")

        # Read user's chunk size
        user_chunk_size = data.get("chunk_size")
        try:
            chunk_size = int(user_chunk_size) if user_chunk_size else CHUNK_SIZE
            if chunk_size < 1 or chunk_size > 100:
                chunk_size = CHUNK_SIZE
        except (ValueError, TypeError):
            chunk_size = CHUNK_SIZE

        if not project_id:
            return JsonResponse(
                {"error": error_messages.missing_project_id_lower()}, status=400
            )

        valid, error = _validate_user_password(conn, password)
        if not valid:
            return JsonResponse({"error": error}, status=403)

        image_ids = _resolve_image_ids(conn, project_id, selected_image_ids)

        allowed, remaining = check_major_action_rate_limit(request, conn)
        if not allowed:
            return JsonResponse(
                {"error": build_rate_limit_message(remaining)},
                status=429,
            )

        job_id = uuid.uuid4().hex

        job = {
            "job_id": job_id,
            "username": current_username(request, conn),
            "type": "del_plugin",
            "project_id": int(project_id),
            "image_ids": image_ids,
            "total": len(image_ids),
            "index": 0,
            "started": time.time(),
            # ensure keys expected by job_progress also exist
            "separator": "",
            "var_names": [],
            "delete_mode": "plugin",
            "chunk_size": chunk_size,
        }

        save_job(job)

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.error(
            "start_delete_plugin_job() error: %s",
            sanitize_log_value(e),
            exc_info=sanitized_exc_info(e),
        )
        return JsonResponse({"error": error_messages.unexpected_error()}, status=500)


# ==============================================================================
# JOB PROGRESS
# ==============================================================================
@login_required()
@require_non_root_user
def job_progress(request, job_id, conn=None, _url=None, **kwargs):
    """Return the job progress.

    Inputs: `request` Django request, `job_id`, `conn` OMERO gateway connection, `_url`,
    `**kwargs` keyword arguments. Output: Django `JsonResponse`.
    """
    lk = None
    try:
        job = load_job(job_id)
        if job is None:
            return JsonResponse(
                {"error": error_messages.unknown_job(), "finished": True}, status=404
            )
        if not _job_owned_by_request(job, request, conn):
            return JsonResponse(
                {"error": error_messages.unknown_job(), "finished": True}, status=404
            )

        lockfile = _job_lock_path(job_id)
        try:
            lk = portalocker.Lock(lockfile, "w", timeout=0)
            lk.acquire()
        except portalocker.exceptions.LockException:
            done = job["index"]
            total = job["total"]
            percent = (done / total * 100) if total else 0
            return JsonResponse(
                {
                    "done": done,
                    "total": total,
                    "percent": percent,
                    "finished": False,
                    "eta_seconds": None,
                    "last_log": "",
                }
            )

        total = job["total"]
        idx = job["index"]
        var_names = job["var_names"]
        delete_mode = job["delete_mode"]
        raw_seps = job["separator"]
        separator_mode = job.get("separator_mode", "chars")
        image_ids = job["image_ids"]
        started = job["started"]

        if idx >= total:
            return JsonResponse(
                {
                    "done": total,
                    "total": total,
                    "percent": 100.0,
                    "finished": True,
                    "eta_seconds": 0,
                    "last_log": "",
                }
            )

        if separator_mode in ("regex", "ai_regex") and not _is_safe_separator_regex(
            raw_seps
        ):
            return JsonResponse(
                {
                    "error": error_messages.invalid_regex_pattern_title(),
                    "finished": True,
                },
                status=400,
            )
        if separator_mode in ("regex", "ai_regex"):
            sep_pattern = raw_seps
        else:
            seps_escaped = "".join(re.escape(c) for c in raw_seps)
            sep_pattern = f"[{seps_escaped}]+"

        job_chunk_size = job.get("chunk_size", CHUNK_SIZE)
        end = min(idx + job_chunk_size, total)
        batch_ids = image_ids[idx:end]

        update = conn.getUpdateService()
        batch_logs = []
        image_map = fetch_images_by_ids(conn, batch_ids)

        for iid in batch_ids:
            try:
                img = image_map.get(iid)
                if img is None:
                    batch_logs.append(f"Image {iid}: not found.")
                    continue

                filename = get_text(img.getName())

                # ---------------------------------------------------------
                # DELETE MODE (ALL / PLUGIN) — JOB-BASED
                # ---------------------------------------------------------
                if job.get("type") == "del_all":
                    try:
                        deleted_sets, deleted_pairs, attempted_sets = (
                            delete_existing_annotations(
                                conn,
                                update,
                                img,
                                var_names,
                                "all",
                            )
                        )
                        if attempted_sets == 0:
                            batch_logs.append(
                                f"Image {iid} ({filename}): no key-value pairs to delete found."
                            )
                        elif deleted_sets:
                            batch_logs.append(
                                f"Image {iid} ({filename}): deleted ALL key-value pairs "
                                f"({deleted_sets} sets, {deleted_pairs} pairs)."
                            )
                            if deleted_sets < attempted_sets:
                                batch_logs.append(
                                    f"Image {iid} ({filename}): warning - only confirmed "
                                    f"{deleted_sets} of {attempted_sets} deletions."
                                )
                        else:
                            batch_logs.append(
                                f"Image {iid} ({filename}): no key-value pairs deleted "
                                "because deletions could not be confirmed."
                            )
                    except Exception as e:
                        logger.error(
                            "Delete-all batch processing failed for image %s in job %s: %s",
                            iid,
                            sanitize_log_value(job_id),
                            sanitize_log_value(e),
                            exc_info=sanitized_exc_info(e),
                        )
                        batch_logs.append(
                            f"Image {iid} ({filename}): ERROR deleting ALL key-value pairs."
                        )
                    continue

                if job.get("type") == "del_plugin":
                    try:
                        deleted_sets, deleted_pairs, attempted_sets = (
                            delete_existing_annotations(
                                conn,
                                update,
                                img,
                                var_names,
                                "plugin",
                            )
                        )
                        if attempted_sets == 0:
                            batch_logs.append(
                                f"Image {iid} ({filename}): no key-value pairs to delete found."
                            )
                        elif deleted_sets:
                            batch_logs.append(
                                f"Image {iid} ({filename}): deleted ONLY plugin key-value pairs "
                                f"({deleted_sets} sets, {deleted_pairs} pairs)."
                            )
                            if deleted_sets < attempted_sets:
                                batch_logs.append(
                                    f"Image {iid} ({filename}): warning - only confirmed "
                                    f"{deleted_sets} of {attempted_sets} deletions."
                                )
                        else:
                            batch_logs.append(
                                f"Image {iid} ({filename}): no key-value pairs deleted "
                                "because deletions could not be confirmed."
                            )
                    except Exception as e:
                        logger.error(
                            "Delete-plugin batch processing failed for image %s in job %s: %s",
                            iid,
                            sanitize_log_value(job_id),
                            sanitize_log_value(e),
                            exc_info=sanitized_exc_info(e),
                        )
                        batch_logs.append(
                            f"Image {iid} ({filename}): ERROR deleting plugin key-value pairs."
                        )
                    continue

                # ---------------------------------------------------------
                # ACQUISITION METADATA MODE (NO DELETION – ONLY APPEND)
                # ---------------------------------------------------------
                if job.get("type") == "acq":
                    metadata_mapping = dict(extract_acquisition_metadata(img) or {})
                    annotation_mapping = _with_plugin_hash(metadata_mapping)

                    if annotation_mapping:
                        saved = _save_image_map_annotation(
                            update, img, annotation_mapping
                        )
                        if saved:
                            batch_logs.append(
                                f"Image {iid} ({filename}): saved "
                                f"{len(metadata_mapping)}+1 acquisition entries."
                            )
                        else:
                            batch_logs.append(
                                f"Image {iid} ({filename}): ERROR confirming acquisition save."
                            )
                    else:
                        batch_logs.append(f"Image {iid}: no acquisition metadata.")

                    # IMPORTANT: skip filename-processing logic
                    continue

                parts = parse_filename(filename, sep_pattern)

                mapping: dict[str, str] = {}
                for i, part in enumerate(parts):
                    if i < len(var_names) and str(var_names[i]).strip():
                        base_key = str(var_names[i]).strip()
                    else:
                        base_key = f"Var{i + 1}"
                    key = _unique_annotation_key(mapping, base_key)
                    mapping[key] = str(part)
                annotation_mapping = _with_plugin_hash(mapping)

                # DELETE FIRST
                delete_existing_annotations(conn, update, img, var_names, delete_mode)

                # Write one annotation containing user keys plus the plugin marker.
                if annotation_mapping:
                    saved = _save_image_map_annotation(update, img, annotation_mapping)
                    if saved:
                        batch_logs.append(
                            f"Image {iid} ({filename}): saved {len(mapping)}+1 variables."
                        )
                    else:
                        batch_logs.append(
                            f"Image {iid} ({filename}): ERROR confirming variable save."
                        )
                else:
                    batch_logs.append(f"Image {iid} ({filename}): no variables.")

            except Exception as e:
                batch_logs.append(f"Image {iid}: ERROR processing image.")
                logger.error(
                    "Error processing image %s in job %s: %s",
                    iid,
                    sanitize_log_value(job_id),
                    sanitize_log_value(e),
                    exc_info=sanitized_exc_info(e),
                )

        job["index"] = end
        with mark_job_lock_held(job_id):
            save_job(job)

        done = end
        elapsed = time.time() - started
        eta = (elapsed / done * (total - done)) if 0 < done < total else 0
        percent = (done / total * 100) if total else 0
        finished = done >= total

        return JsonResponse(
            {
                "done": done,
                "total": total,
                "percent": percent,
                "eta_seconds": eta,
                "finished": finished,
                "last_log": "\n".join(batch_logs),
            }
        )

    finally:
        try:
            if lk is not None:
                lk.release()
        except Exception as exc:
            logger.debug("Suppressed non-fatal exception in job_view.py", exc_info=exc)
