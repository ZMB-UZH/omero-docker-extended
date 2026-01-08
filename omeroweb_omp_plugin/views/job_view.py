from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import time
import uuid
import logging
import portalocker
import re
import omero

from omero.model import MapAnnotationI, NamedValue, ImageAnnotationLinkI
from omero.rtypes import rstring

from ..constants import CHUNK_SIZE, MAP_NS, HASH_KEY
from ..services.job_cleanup import cleanup_old_jobs

from ..services.core import (
    load_job,
    save_job,
    _job_lock_path,
    collect_images_in_project,
    get_id,
    get_text,
    parse_filename,
    fetch_images_by_ids,
    compute_plugin_hash,
    delete_existing_annotations,
    extract_acquisition_metadata,
)
from ..services.rate_limit import build_rate_limit_message, check_major_action_rate_limit
from ..views.utils import load_request_data
from ..strings import errors

logger = logging.getLogger(__name__)


def parse_image_ids(raw_ids):
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
    if not password:
        return False, errors.missing_password()

    username = conn.getUser().getName()
    host, port = _resolve_omero_host_port(conn)
    if not host or not port:
        logger.error(
            "Unable to resolve OMERO host/port for password validation (host=%s, port=%s).",
            host,
            port,
        )
        return False, errors.validation_unavailable()

    client = omero.client(host=host, port=port)
    try:
        client.createSession(username, password)
    except Exception as exc:
        logger.warning("Password validation failed for user %s: %s", username, exc)
        return False, errors.wrong_password()
    finally:
        try:
            client.closeSession()
        except Exception:
            pass

    return True, None


def _resolve_image_ids(conn, project_id, selected_image_ids):
    if selected_image_ids:
        return sorted(set(selected_image_ids))

    images = collect_images_in_project(conn, project_id)
    if not images:
        images = list(conn.getObjects("Image"))

    seen = set()
    image_ids = []
    for img in images:
        iid = get_id(img)
        if not iid:
            continue
        iid = int(iid)
        if iid not in seen:
            seen.add(iid)
            image_ids.append(iid)

    image_ids.sort()
    return image_ids


def _save_annotation_link(update, link):
    saved_link = update.saveAndReturnObject(link)
    if saved_link is None:
        return False
    return bool(get_id(saved_link))

# ==============================================================================
# START JOB
# ==============================================================================
@csrf_exempt
@login_required()
def start_job(request, conn=None, url=None, **kwargs):
    cleanup_old_jobs()
    try:
        if request.method != "POST":
            return JsonResponse({"error": errors.method_post_required()}, status=400)

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

        if separator_mode in ("regex", "ai_regex"):
            try:
                re.compile(raw_seps)
            except re.error as e:
                return JsonResponse({"error": errors.invalid_regex_pattern(e)}, status=400)

        if delete_mode not in ("keep", "all", "plugin"):
            delete_mode = "keep"

        if not project_id:
            return JsonResponse({"error": errors.missing_project_id_lower()}, status=400)

        image_ids = _resolve_image_ids(conn, project_id, selected_image_ids)

        allowed, remaining = check_major_action_rate_limit(request, conn)
        if not allowed:
            return JsonResponse(
                {"error": build_rate_limit_message(remaining)},
                status=429,
            )

        job_id = uuid.uuid4().hex

        # *** FIXED: DO NOT OVERRIDE separator / var_names / delete_mode ***
        job = {
            "job_id": job_id,
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
        logger.exception("start_job() error: %s", e)
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@login_required()
def start_acq_job(request, conn=None, url=None, **kwargs):
    cleanup_old_jobs()
    try:
        if request.method != "POST":
            return JsonResponse({"error": errors.method_post_required()}, status=400)

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
            return JsonResponse({"error": errors.missing_project_id_lower()}, status=400)
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
            "type": "acq",       # <-- DO NOT CHANGE THIS
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
        logger.exception("start_acq_job() error")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@login_required()
def start_delete_all_job(request, conn=None, url=None, **kwargs):
    cleanup_old_jobs()
    try:
        if request.method != "POST":
            return JsonResponse({"error": errors.method_post_required()}, status=400)

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
            return JsonResponse({"error": errors.missing_project_id_lower()}, status=400)

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
        logger.exception("start_delete_all_job() error")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@login_required()
def start_delete_plugin_job(request, conn=None, url=None, **kwargs):
    cleanup_old_jobs()
    try:
        if request.method != "POST":
            return JsonResponse({"error": errors.method_post_required()}, status=400)

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
            return JsonResponse({"error": errors.missing_project_id_lower()}, status=400)

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
        logger.exception("start_delete_plugin_job() error")
        return JsonResponse({"error": str(e)}, status=500)


# ==============================================================================
# JOB PROGRESS
# ==============================================================================
@csrf_exempt
@login_required()
def job_progress(request, job_id, conn=None, url=None, **kwargs):
    cleanup_old_jobs()
    try:
        job = load_job(job_id)
        if job is None:
            return JsonResponse({"error": errors.unknown_job(), "finished": True}, status=404)

        lockfile = _job_lock_path(job_id)
        try:
            lk = portalocker.Lock(lockfile, "w", timeout=0)
            lk.acquire()
        except portalocker.exceptions.LockException:
            done = job["index"]
            total = job["total"]
            percent = (done / total * 100) if total else 0
            return JsonResponse({
                "done": done,
                "total": total,
                "percent": percent,
                "finished": False,
                "eta_seconds": None,
                "last_log": ""
            })

        total = job["total"]
        idx = job["index"]
        var_names = job["var_names"]
        delete_mode = job["delete_mode"]
        raw_seps = job["separator"]
        separator_mode = job.get("separator_mode", "chars")
        image_ids = job["image_ids"]
        started = job["started"]

        if idx >= total:
            return JsonResponse({
                "done": total,
                "total": total,
                "percent": 100.0,
                "finished": True,
                "eta_seconds": 0,
                "last_log": ""
            })

        seps_escaped = "".join(re.escape(c) for c in raw_seps)
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
                        deleted_sets, deleted_pairs, attempted_sets = delete_existing_annotations(
                            conn,
                            update,
                            img,
                            var_names,
                            "all",
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
                        batch_logs.append(f"Image {iid} ({filename}): ERROR deleting ALL key-value pairs: {e}")
                    continue

                if job.get("type") == "del_plugin":
                    try:
                        deleted_sets, deleted_pairs, attempted_sets = delete_existing_annotations(
                            conn,
                            update,
                            img,
                            var_names,
                            "plugin",
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
                        batch_logs.append(f"Image {iid} ({filename}): ERROR deleting plugin key-value pairs: {e}")
                    continue

                # ---------------------------------------------------------
                # ACQUISITION METADATA MODE (NO DELETION – ONLY APPEND)
                # ---------------------------------------------------------
                if job.get("type") == "acq":
                    mapping = extract_acquisition_metadata(img)

                    if mapping:
                        mapping[HASH_KEY] = compute_plugin_hash(mapping)

                    if mapping:
                        ann = MapAnnotationI()
                        ann.setNs(rstring(MAP_NS))
                        nv_list = [NamedValue(k, v) for k, v in mapping.items()]
                        ann.setMapValue(nv_list)

                        link = ImageAnnotationLinkI()
                        link.setParent(img._obj)
                        link.setChild(ann)
                        saved = _save_annotation_link(update, link)
                        if saved:
                            batch_logs.append(
                                f"Image {iid} ({filename}): saved {len(mapping)} acquisition entries."
                            )
                        else:
                            batch_logs.append(
                                f"Image {iid} ({filename}): ERROR confirming acquisition save."
                            )
                    else:
                        batch_logs.append(
                            f"Image {iid}: no acquisition metadata."
                        )

                    # IMPORTANT: skip filename-processing logic
                    continue

                parts = parse_filename(filename, sep_pattern)

                mapping = {}
                for i, part in enumerate(parts):
                    if i < len(var_names) and str(var_names[i]).strip():
                        base_key = str(var_names[i]).strip()
                    else:
                        base_key = f"Var{i + 1}"
                    key = base_key
                    if key in mapping:
                        suffix = 2
                        while f"{base_key}_{suffix}" in mapping:
                            suffix += 1
                        key = f"{base_key}_{suffix}"
                    mapping[key] = str(part)
                if mapping:
                    mapping[HASH_KEY] = compute_plugin_hash(mapping)

                # DELETE FIRST
                delete_existing_annotations(conn, update, img, var_names, delete_mode)

                # -------------------------------
                # FIX: WRITE ONLY ONE ANNOTATION
                # -------------------------------
                if mapping:

                    ann = MapAnnotationI()
                    ann.setNs(rstring(MAP_NS))
                    nv_list = [NamedValue(k, v) for k, v in mapping.items()]
                    ann.setMapValue(nv_list)

                    # Link FIRST -> save once
                    link = ImageAnnotationLinkI()
                    link.setParent(img._obj)
                    link.setChild(ann)

                    saved = _save_annotation_link(update, link)
                    if saved:
                        saved_total = len(parts) + 1
                        batch_logs.append(
                            f"Image {iid} ({filename}): saved {saved_total-1}+1 variables."
                        )
                    else:
                        batch_logs.append(
                            f"Image {iid} ({filename}): ERROR confirming variable save."
                        )
                else:
                    batch_logs.append(f"Image {iid} ({filename}): no variables.")

            except Exception as e:
                batch_logs.append(f"Image {iid}: ERROR {e}")
                logger.exception("Error processing image %s in job %s: %s", iid, job_id, e)

        job["index"] = end
        save_job(job)

        done = end
        elapsed = time.time() - started
        eta = (elapsed / done * (total - done)) if (done > 0 and done < total) else 0
        percent = (done / total * 100) if total else 0
        finished = done >= total

        return JsonResponse({
            "done": done,
            "total": total,
            "percent": percent,
            "eta_seconds": eta,
            "finished": finished,
            "last_log": "\n".join(batch_logs)
        })

    finally:
        try:
            lk.release()
        except:
            pass
