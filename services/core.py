import os
import json
import re
import logging
import portalocker
import hashlib
import hmac

from omero.model import MapAnnotationI
from omero.model import NamedValue, ImageAnnotationLinkI
from omero.rtypes import rstring
from ..constants import (
    JOBS_DIR,
    MAP_NS,
    HASH_KEY,
    HASH_PREFIX,
    PLUGIN_ID,
    HASH_SECRET_ENV,
)


logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# JOB STORAGE
# --------------------------------------------------------------------------
def _job_path(job_id):
    return os.path.join(JOBS_DIR, f"{job_id}.json")

def _job_lock_path(job_id):
    return os.path.join(JOBS_DIR, f"{job_id}.lock")

def load_job(job_id):
    path = _job_path(job_id)
    if not os.path.exists(path):
        return None
    with portalocker.Lock(path, "r", timeout=1) as f:
        return json.load(f)

def save_job(job_dict):
    path = _job_path(job_dict["job_id"])
    with portalocker.Lock(path, "w", timeout=1) as f:
        json.dump(job_dict, f)

# --------------------------------------------------------------------------
# GENERAL HELPERS
# --------------------------------------------------------------------------
def get_text(value_obj):
    try:
        return value_obj.getValue() if hasattr(value_obj, "getValue") else getattr(
            value_obj, "val", str(value_obj)
        )
    except Exception:
        return str(value_obj)

def get_id(obj):
    try:
        return obj._obj.id.val
    except:
        pass
    try:
        gid = obj.getId()
        return gid.getValue() if hasattr(gid, "getValue") else gid
    except:
        return None

# --------------------------------------------------------------------------
# PLUGIN HASH MARKER HELPERS
# --------------------------------------------------------------------------
def _get_hash_secret():
    """Return secret used to compute/verify plugin hash marker."""
    return os.environ.get(HASH_SECRET_ENV, "")


def _canonicalize_mapping(mapping):
    """
    Return deterministic JSON payload for hashing.
    HASH_KEY itself is excluded to avoid recursion.
    """
    data = {}
    for k, v in (mapping or {}).items():
        if k == HASH_KEY:
            continue
        data[str(k)] = "" if v is None else str(v)

    payload = {
        "plugin": PLUGIN_ID,
        "version": "1",
        "data": data,
    }

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_plugin_hash(mapping):
    """
    Compute the value stored under HASH_KEY.
    """
    payload = _canonicalize_mapping(mapping)
    secret = _get_hash_secret()

    if secret:
        digest = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    else:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return f"{HASH_PREFIX}{digest}"


def is_plugin_annotation(map_ann_obj):
    """
    Return True if MapAnnotation was created by this plugin.
    """
    try:
        mv = map_ann_obj.getMapValue() or []
        mapping = {
            str(nv.name): "" if nv.value is None else str(nv.value)
            for nv in mv
        }
    except Exception:
        return False

    marker = mapping.get(HASH_KEY)
    if not marker or not str(marker).startswith(HASH_PREFIX):
        return False

    expected = compute_plugin_hash(mapping)
    return hmac.compare_digest(str(marker), str(expected))

# --------------------------------------------------------------------------
# DATASET-FIRST + IMAGE-ID-SORTED COLLECTION
# --------------------------------------------------------------------------
def collect_images_by_dataset_sorted(conn, project_id, limit=None):
    """
    Returns:
        [(dataset_obj, [image_obj_sorted_by_ID]), ...]
    Dataset ordering is preserved as OMERO returns it.
    Image ordering is strictly numeric ascending by image ID.
    """
    out = []
    total = 0
    try:
        prj = conn.getObject("Project", int(project_id))
        if prj is None:
            return out

        for ds in prj.listChildren():   # dataset order preserved
            imgs = list(ds.listChildren())
            # sort by numeric ID
            imgs_sorted = sorted(
                imgs, key=lambda img: int(get_id(img)) if get_id(img) else 999999999
            )

            total += len(imgs_sorted)
            if limit and total > limit:
                # truncate to satisfy limit
                remaining = limit - (total - len(imgs_sorted))
                imgs_sorted = imgs_sorted[:remaining]
                out.append((ds, imgs_sorted))
                return out

            out.append((ds, imgs_sorted))

    except Exception as e:
        logger.exception("Error collecting dataset-sorted images: %s", e)

    return out

# --------------------------------------------------------------------------
# Legacy collector
# --------------------------------------------------------------------------
def collect_images_in_project(conn, project_id, limit=None):
    images = []
    try:
        project = conn.getObject("Project", int(project_id))
        if project is None:
            logger.warning("Project %s not found", project_id)
            return images

        for ds in project.listChildren():
            for img in ds.listChildren():
                images.append(img)
                if limit and len(images) >= limit:
                    return images
    except Exception as e:
        logger.exception("Error collecting images: %s", e)

    return images

# --------------------------------------------------------------------------
# FILENAME PARSING
# --------------------------------------------------------------------------
def parse_filename(filename, sep_pattern):
    m = re.search(r"\[(.+?)\]", filename)
    if m:
        base_name = m.group(1)
    else:
        f = filename.replace("\t", " ")
        m2 = re.search(r".*\s+(.+?)\s*$", f)
        if m2:
            base_name = m2.group(1).rsplit(".", 1)[0]
        else:
            base_name = filename.rsplit(".", 1)[0]

    parts = [p for p in re.split(sep_pattern, base_name) if p]
    return parts

# --------------------------------------------------------------------------
# EXTRACT ACQUISITION METADATA AND COPY AS KEY-VALUE PAIRS
# --------------------------------------------------------------------------
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
        try:
            store.setFileId(of.getId().getValue())
            store.write(binary, 0, len(binary))
            store.save()
        finally:
            try:
                store.close()
            except Exception:
                pass

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

# --------------------------------------------------------------------------
# DELETE ALL EXISTING KEY-VALUE PAIRS
# --------------------------------------------------------------------------
def delete_existing_annotations(conn, update, img, var_names, mode):
    """
    Delete MapAnnotations depending on deletion mode.

    Modes:
        keep    – keep everything
        all     – delete all MapAnnotations
        plugin  – delete ONLY MapAnnotations created by this plugin
    """
    if mode == "keep":
        return

    try:
        annotations = list(img.listAnnotations())
    except Exception as e:
        logger.warning(
            "Cannot list annotations for image %s: %s",
            get_id(img),
            e,
        )
        return

    for ann in annotations:
        try:
            obj = getattr(ann, "_obj", None)
            if not isinstance(obj, MapAnnotationI):
                continue

            # Best-effort namespace check
            ns = None
            try:
                ns_obj = ann.getNs()
                ns = ns_obj.getValue() if ns_obj else None
            except Exception:
                pass

            # --------------------------------------------------
            # MODE: all (same behavior as before, but safe)
            # --------------------------------------------------
            if mode == "all":
                update.deleteObject(obj)
                continue

            # --------------------------------------------------
            # MODE: plugin (HASH-VERIFIED)
            # --------------------------------------------------
            if mode == "plugin":
                if ns != MAP_NS:
                    continue
                if is_plugin_annotation(obj):
                    update.deleteObject(obj)
                continue

        except Exception as e:
            logger.warning(
                "Error deleting annotation on image %s: %s",
                get_id(img),
                e,
            )
            continue
