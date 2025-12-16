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
    compute_plugin_hash,
    delete_existing_annotations,
    extract_acquisition_metadata,
)

logger = logging.getLogger(__name__)

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
                var_names = data.get("var_names") or []
                delete_mode = data.get("delete_mode")

                if delete_mode not in ("keep", "all"):
                        delete_mode = "keep"

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
                        "started": time.time()
                }

                save_job(job)

                return JsonResponse({"job_id": job_id, "total": len(image_ids)})

        except Exception as e:
                logger.exception("start_job() error: %s", e)
                return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@login_required()
def start_acq_job(request, conn=None, url=None, **kwargs):
    logger.error("ACQ DEBUG 1: start_acq_job called")

    try:
        if request.method != "POST":
            logger.error("ACQ DEBUG 2: not POST")
            return JsonResponse({"error": "POST required"}, status=400)

        logger.error(f"ACQ DEBUG 3: request.body={request.body}")

        try:
            data = json.loads(request.body.decode("utf-8"))
            logger.error(f"ACQ DEBUG 4: parsed JSON={data}")
        except Exception as e:
            logger.error(f"ACQ DEBUG 5: JSON parse failed: {e}")
            data = request.POST
            logger.error(f"ACQ DEBUG 6: request.POST={data}")

        project_id = data.get("project_id")
        logger.error(f"ACQ DEBUG 7: project_id={project_id}")

        if not project_id:
            logger.error("ACQ DEBUG 8: project_id missing")
            return JsonResponse({"error": "missing project_id"}, status=400)

        logger.error("ACQ DEBUG 9: before collect_images_in_project")
        images = collect_images_in_project(conn, project_id)
        logger.error(f"ACQ DEBUG 10: collect_images_in_project returned type={type(images)}")

        if not images:
            logger.error("ACQ DEBUG 11: images empty -> fallback to all images")
            images = list(conn.getObjects("Image"))

        seen = set()
        image_ids = []

        logger.error("ACQ DEBUG 12: starting loop over images")
        for img in images:
            try:
                iid = get_id(img)
                if iid and iid not in seen:
                    seen.add(iid)
                    image_ids.append(int(iid))
            except Exception as e:
                logger.error(f"ACQ DEBUG 13: error reading image id: {e}")

        image_ids.sort()
        logger.error(f"ACQ DEBUG 14: total unique images={len(image_ids)}")

        job_id = uuid.uuid4().hex
        logger.error(f"ACQ DEBUG 15: job_id={job_id}")

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

        logger.error(f"ACQ DEBUG 16: saving job={job}")
        save_job(job)

        logger.error(f"ACQ DEBUG 17: returning JSON job_id={job_id}")

        return JsonResponse({"job_id": job_id, "total": len(image_ids)})

    except Exception as e:
        logger.exception("start_acq_job() error")
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
        sep_pattern = f"[{seps_escaped}]+"

        end = min(idx + CHUNK_SIZE, total)
        batch_ids = image_ids[idx:end]

        update = conn.getUpdateService()
        batch_logs = []

        for iid in batch_ids:
            try:
                img = conn.getObject("Image", iid)
                if img is None:
                    batch_logs.append(f"Image {iid}: not found.")
                    continue

                # ---------------------------------------------------------
                # ACQUISITION METADATA MODE (NO DELETION – ONLY APPEND)
                # ---------------------------------------------------------
                if job.get("type") == "acq":
                    logger.error("ACQ DEBUG: calling extractor for image %s", iid)
                    mapping = extract_acquisition_metadata(img)
                    logger.error("ACQ DEBUG RESULT for image %s: %s", iid, mapping)

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
                            f"Image {iid}: saved {len(mapping)} acquisition entries."
                        )
                    else:
                        batch_logs.append(
                            f"Image {iid}: no acquisition metadata."
                        )

                    # IMPORTANT: skip filename-processing logic
                    continue

                filename = get_text(img.getName())
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


def extract_acquisition_metadata(img):
    meta = {}

    # ----------------------------------------------------
    # 1. Typed metadata directly from OMERO model
    # ----------------------------------------------------

    # Acquisition date
    try:
        ad = img.getAcquisitionDate()
        if ad:
            try:
                meta["acquisition_date"] = str(ad.getValue())
            except AttributeError:
                # Sometimes gateway returns a datetime or string directly
                meta["acquisition_date"] = str(ad)
    except Exception as e:
        try:
            logger.error("ACQ: error reading acquisition date for image %s: %s", img.getId(), e)
        except Exception:
            logger.error("ACQ: error reading acquisition date: %s", e)

    # Objective settings
    try:
        os = img.getObjectiveSettings()
        if os:
            try:
                oid = os.getID()
                if oid:
                    try:
                        meta["objective_id"] = str(oid.getValue())
                    except AttributeError:
                        meta["objective_id"] = str(oid)
            except Exception:
                pass

            try:
                collar = os.getCorrectionCollar()
                if collar:
                    try:
                        meta["objective_collar"] = str(collar.getValue())
                    except AttributeError:
                        meta["objective_collar"] = str(collar)
            except Exception:
                pass
    except Exception as e:
        try:
            logger.error("ACQ: error reading objective settings for image %s: %s", img.getId(), e)
        except Exception:
            logger.error("ACQ: error reading objective settings: %s", e)

    # Channels
    try:
        for ch in img.getChannels():
            try:
                idx = ch.getIndex()
            except Exception:
                idx = "unknown"

            try:
                lbl = ch.getLabel()
                if lbl:
                    meta[f"channel_{idx}_label"] = str(lbl)
            except Exception:
                pass

            try:
                ew = ch.getEmissionWave()
                if ew:
                    try:
                        meta[f"channel_{idx}_emission"] = str(ew.getValue())
                    except AttributeError:
                        meta[f"channel_{idx}_emission"] = str(ew)
            except Exception:
                pass

            try:
                exw = ch.getExcitationWave()
                if exw:
                    try:
                        meta[f"channel_{idx}_excitation"] = str(exw.getValue())
                    except AttributeError:
                        meta[f"channel_{idx}_excitation"] = str(exw)
            except Exception:
                pass
    except Exception as e:
        try:
            logger.error("ACQ: error reading channel metadata for image %s: %s", img.getId(), e)
        except Exception:
            logger.error("ACQ: error reading channel metadata: %s", e)

    # Detector settings
    try:
        # Not all gateway versions expose getDetectorSettings()
        ds_list = None
        try:
            ds_list = img.getDetectorSettings()
        except Exception:
            ds_list = None

        if ds_list:
            for ds in ds_list:
                try:
                    did = ds.getID().getValue() if ds.getID() else "unknown"
                except Exception:
                    did = "unknown"

                try:
                    binning = ds.getBinning()
                    if binning:
                        try:
                            meta[f"detector_{did}_binning"] = str(binning.getValue())
                        except AttributeError:
                            meta[f"detector_{did}_binning"] = str(binning)
                except Exception:
                    pass

                try:
                    gain = ds.getGain()
                    if gain:
                        try:
                            meta[f"detector_{did}_gain"] = str(gain.getValue())
                        except AttributeError:
                            meta[f"detector_{did}_gain"] = str(gain)
                except Exception:
                    pass
    except Exception as e:
        try:
            logger.error("ACQ: error reading detector settings for image %s: %s", img.getId(), e)
        except Exception:
            logger.error("ACQ: error reading detector settings: %s", e)

    # ----------------------------------------------------
    # 2. Original Metadata imported by Bio-Formats
    #    (This contains MOST of the useful acquisition data)
    #    Use ImageWrapper.loadOriginalMetadata(), NOT MetadataService.
    # ----------------------------------------------------
    try:
        om = img.loadOriginalMetadata()
        # om is typically a tuple: (pixelsId, global_metadata, series_metadata)
        if om:
            try:
                global_md = om[1] if len(om) > 1 and om[1] else []
            except Exception:
                global_md = []
            try:
                series_md = om[2] if len(om) > 2 and om[2] else []
            except Exception:
                series_md = []

            for kv in (global_md + series_md):
                try:
                    # kv is usually (key, value, ...)
                    if len(kv) > 1:
                        k = kv[0]
                        v = kv[1]
                        if k and v:
                            meta[f"BF_{str(k)}"] = str(v)
                except Exception:
                    continue
    except Exception as e:
        try:
            logger.error(
                "ACQ: error loading original metadata for image %s: %s",
                img.getId(),
                e,
            )
        except Exception:
            logger.error("ACQ: error loading original metadata: %s", e)

    # ----------------------------------------------------
    # 3. Separate long values (FileAnnotation)
    # ----------------------------------------------------
    long_values = {}
    cleaned = {}

    for k, v in meta.items():
        v = str(v)
        if len(v) > 250:
            long_values[k] = v
            cleaned[k] = f"[LONG_VALUE_STORED_IN_FILEANNOTATION key={k}]"
        else:
            cleaned[k] = v

    # ----------------------------------------------------
    # 4. If long values exist → create FileAnnotation
    # ----------------------------------------------------
    if long_values:
        from omero.model import FileAnnotationI, OriginalFileI
        from omero.rtypes import rstring, rlong

        text = "\n".join(f"{k} = {v}" for k, v in long_values.items())
        binary = text.encode("utf-8")

        update = img._conn.getUpdateService()

        of = OriginalFileI()
        of.setName(rstring("acquisition_metadata.txt"))
        of.setPath(rstring(f"img_{img.getId()}/"))
        of.setSize(rlong(len(binary)))
        of.setMimetype(rstring("text/plain"))

        of = update.saveAndReturnObject(of)

        store = img._conn.c.sf.createRawFileStore()
        store.setFileId(of.getId().getValue())
        store.write(binary, 0, len(binary))
        store.save()
        store.close()

        fa = FileAnnotationI()
        fa.setNs(rstring("acquisition.fullmetadata"))
        fa.setFile(of)

        link = ImageAnnotationLinkI()
        link.setParent(img._obj)
        link.setChild(fa)

        update.saveAndReturnObject(link)

        cleaned["full_metadata_file"] = f"FileAnnotation:{of.getId().getValue()}"

    # ----------------------------------------------------
    # RETURN CLEANED SEARCHABLE METADATA
    # ----------------------------------------------------
    return cleaned

