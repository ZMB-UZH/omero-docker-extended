from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import time
import uuid
import logging
import portalocker
import re
import json

from omero.model import MapAnnotationI, NamedValue, ImageAnnotationLinkI
from omero.rtypes import rstring

from ..constants import CHUNK_SIZE, MAP_NS, HASH_KEY

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

# ==============================================================================
# START JOB
# ==============================================================================
@csrf_exempt
@login_required()
def start_job(request, conn=None, url=None, **kwargs):
        try:
                if request.method != "POST":
                        return JsonResponse({"error": "POST required"}, status=400)

                try:
                        data = json.loads(request.body.decode("utf-8"))
                except:
                        data = request.POST

                project_id = data.get("project_id")
                raw_seps = data.get("separator", "_")
                separator_mode = data.get("separator_mode", "chars")
                var_names = data.get("var_names") or []
                delete_mode = data.get("delete_mode")
                selected_image_ids = parse_image_ids(data.get("image_ids"))

                if separator_mode not in ("chars", "regex"):
                        separator_mode = "chars"

                if separator_mode == "regex":
                        try:
                                re.compile(raw_seps)
                        except re.error as e:
                                return JsonResponse({"error": f"Invalid regex pattern: {e}"}, status=400)

                if delete_mode not in ("keep", "all", "plugin"):
                        delete_mode = "keep"

                if selected_image_ids:
                        image_ids = sorted(set(selected_image_ids))
                else:
                        images = collect_images_in_project(conn, project_id)
                        if not images:
                                images = list(conn.getObjects("Image"))

                        # Remove duplicates
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
                }

                save_job(job)

                return JsonResponse({"job_id": job_id, "total": len(image_ids)})

        except Exception as e:
                logger.exception("start_job() error: %s", e)
                return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@login_required()
def start_acq_job(request, conn=None, url=None, **kwargs):
    try:
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception as e:
            data = request.POST

        project_id = data.get("project_id")
        selected_image_ids = parse_image_ids(data.get("image_ids"))

        if not project_id:
            return JsonResponse({"error": "missing project_id"}, status=400)
        if selected_image_ids:
            image_ids = sorted(set(selected_image_ids))
        else:
            images = collect_images_in_project(conn, project_id)

            if not images:
                images = list(conn.getObjects("Image"))

            seen = set()
            image_ids = []
            for img in images:
                try:
                    iid = get_id(img)
                    if iid and iid not in seen:
                        seen.add(iid)
                        image_ids.append(int(iid))
                except Exception as e:
                    logger.warning("Could not read image id: %s", e)

            image_ids.sort()

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
        }

        save_job(job)

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.exception("start_acq_job() error")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@login_required()
def start_delete_all_job(request, conn=None, url=None, **kwargs):
    try:
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = request.POST

        project_id = data.get("project_id")
        selected_image_ids = parse_image_ids(data.get("image_ids"))

        if not project_id:
            return JsonResponse({"error": "missing project_id"}, status=400)

        if selected_image_ids:
            image_ids = sorted(set(selected_image_ids))
        else:
            images = collect_images_in_project(conn, project_id)

            if not images:
                images = list(conn.getObjects("Image"))

            seen = set()
            image_ids = []
            for img in images:
                try:
                    iid = get_id(img)
                    if iid and iid not in seen:
                        seen.add(iid)
                        image_ids.append(int(iid))
                except Exception as e:
                    logger.warning("Could not read image id: %s", e)

            image_ids.sort()

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
        }

        save_job(job)

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.exception("start_delete_all_job() error")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@login_required()
def start_delete_plugin_job(request, conn=None, url=None, **kwargs):
    try:
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=400)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = request.POST

        project_id = data.get("project_id")
        selected_image_ids = parse_image_ids(data.get("image_ids"))

        if not project_id:
            return JsonResponse({"error": "missing project_id"}, status=400)

        if selected_image_ids:
            image_ids = sorted(set(selected_image_ids))
        else:
            images = collect_images_in_project(conn, project_id)

            if not images:
                images = list(conn.getObjects("Image"))

            seen = set()
            image_ids = []
            for img in images:
                try:
                    iid = get_id(img)
                    if iid and iid not in seen:
                        seen.add(iid)
                        image_ids.append(int(iid))
                except Exception as e:
                    logger.warning("Could not read image id: %s", e)

            image_ids.sort()

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
    try:
        job = load_job(job_id)
        if job is None:
            return JsonResponse({"error": "unknown job", "finished": True}, status=404)

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
        if separator_mode == "regex":
            sep_pattern = raw_seps
        else:
            seps_escaped = "".join(re.escape(c) for c in raw_seps)
            sep_pattern = f"[{seps_escaped}]+"

        end = min(idx + CHUNK_SIZE, total)
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
                        deleted_count = delete_existing_annotations(
                            conn,
                            update,
                            img,
                            var_names,
                            "all",
                        )
                        if deleted_count:
                            batch_logs.append(
                                f"Image {iid} ({filename}): deleted ALL key-value pairs."
                            )
                        else:
                            batch_logs.append(
                                f"Image {iid} ({filename}): no key-value pairs to delete found."
                            )
                    except Exception as e:
                        batch_logs.append(f"Image {iid} ({filename}): ERROR deleting ALL key-value pairs: {e}")
                    continue

                if job.get("type") == "del_plugin":
                    try:
                        deleted_count = delete_existing_annotations(
                            conn,
                            update,
                            img,
                            var_names,
                            "plugin",
                        )
                        if deleted_count:
                            batch_logs.append(
                                f"Image {iid} ({filename}): deleted ONLY plugin key-value pairs."
                            )
                        else:
                            batch_logs.append(
                                f"Image {iid} ({filename}): no key-value pairs to delete found."
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
                        update.saveAndReturnObject(link)

                        batch_logs.append(
                            f"Image {iid} ({filename}): saved {len(mapping)} acquisition entries."
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
                    if i >= len(var_names):
                        break
                    mapping[var_names[i]] = str(part)
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

                    update.saveAndReturnObject(link)

                    batch_logs.append(
                        f"Image {iid} ({filename}): saved {len(mapping)} variables."
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
