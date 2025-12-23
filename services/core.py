import os
import json
import re
import logging
import portalocker
import hashlib
import hmac

from omero.model import MapAnnotationI
from omero.model import NamedValue, ImageAnnotationLinkI
from omero.rtypes import rstring, rlong
from omero.sys import ParametersI
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

def fetch_images_by_ids(conn, image_ids):
    if not image_ids:
        return {}

    images = []
    try:
        images = list(conn.getObjects("Image", ids=image_ids))
    except TypeError:
        try:
            images = list(conn.getObjects("Image", obj_ids=image_ids))
        except Exception:
            images = []
    except Exception:
        images = []

    if not images:
        for iid in image_ids:
            try:
                img = conn.getObject("Image", iid)
            except Exception:
                img = None
            if img is not None:
                images.append(img)

    image_map = {}
    for img in images:
        iid = get_id(img)
        if iid is None:
            continue
        try:
            image_map[int(iid)] = img
        except Exception:
            image_map[iid] = img

    return image_map

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


def is_plugin_annotation(map_ann_obj, qs=None, service_opts=None):
    """
    Return True if MapAnnotation was created by this plugin.

    If map values are not preloaded on the MapAnnotation object, a QueryService
    can be provided to fetch the pairs directly from the database.
    The lookup path intentionally prefers preloaded values and only falls back
    to the database when none are available, matching the merged behavior of
    previous iterations of this function.
    """

    def _unwrap(val):
        if callable(getattr(val, "getValue", None)):
            try:
                return val.getValue()
            except Exception:
                pass
        # Some OMERO rtypes expose `.val` instead of `.getValue()`
        val = getattr(val, "val", val)
        return val

    def _extract_pair(nv):
        """Return (name, value) tuple from a NamedValue or (name, value) pair."""

        # NamedValue-like object
        name = getattr(nv, "name", None)
        if name is None and callable(getattr(nv, "getName", None)):
            try:
                name = nv.getName()
            except Exception:
                name = None
        name = _unwrap(name)

        value = getattr(nv, "value", None)
        if value is None and callable(getattr(nv, "getValue", None)):
            try:
                value = nv.getValue()
            except Exception:
                value = None
        value = _unwrap(value)

        # Tuple/list fallback
        if name is None and isinstance(nv, (list, tuple)) and len(nv) == 2:
            name, value = nv
            name = _unwrap(name)
            value = _unwrap(value)

        if name is None:
            return None

        return str(name), "" if value is None else str(value)

    def _load_pairs_from_qs(aid):
        if qs is None or aid is None:
            return []

        try:
            params = ParametersI()
            params.add("aid", rlong(int(aid)))
            hql_kv = (
                "select mv.name, mv.value "
                "from MapAnnotation a "
                "join a.mapValue mv "
                "where a.id = :aid"
            )
            rows = qs.projection(hql_kv, params, service_opts) or []
            return [tuple(rr[:2]) for rr in rows if rr]
        except Exception:
            return []

    mapping = {}

    try:
        mv = map_ann_obj.getMapValue() or []
        if hasattr(mv, "getValue"):
            try:
                mv = mv.getValue()
            except Exception:
                pass

        if not mv:
            aid = None
            try:
                gid = map_ann_obj.getId()
                aid = gid.getValue() if hasattr(gid, "getValue") else gid
            except Exception:
                aid = getattr(map_ann_obj, "id", None)

            mv = _load_pairs_from_qs(aid)

        for nv in mv:
            pair = _extract_pair(nv)
            if not pair:
                continue
            k, v = pair
            mapping[k] = v
    except Exception:
        return False

    marker = mapping.get(HASH_KEY)
    if not marker or not str(marker).startswith(HASH_PREFIX):
        return False

    expected = compute_plugin_hash(mapping)
    return hmac.compare_digest(str(marker), str(expected))


def find_plugin_annotation_ids(conn, image_id, allow_legacy=True):
    """Return MapAnnotation IDs created by this plugin for an image."""

    try:
        iid = int(image_id)
    except Exception:
        return []

    ann_ids = []

    try:
        qs = conn.getQueryService()
        service_opts = getattr(conn, "SERVICE_OPTS", None)

        params = ParametersI()
        params.add("iid", rlong(iid))
        params.add("ns", rstring(str(MAP_NS)))

        hql_ids = (
            "select a.id "
            "from ImageAnnotationLink l "
            "join l.child a "
            "where l.parent.id = :iid and a.ns = :ns"
        )

        rows = qs.projection(hql_ids, params, service_opts) or []
        candidate_ids = [r[0].getValue() for r in rows if r and r[0]]

        for aid in candidate_ids:
            try:
                p_ns = ParametersI()
                p_ns.add("aid", rlong(int(aid)))

                hql_kv = (
                    "select mv.name, mv.value "
                    "from MapAnnotation a "
                    "join a.mapValue mv "
                    "where a.id = :aid"
                )
                kv_rows = qs.projection(hql_kv, p_ns, service_opts) or []

                mapping = {}
                for rr in kv_rows:
                    if not rr or len(rr) < 2:
                        continue
                    k = rr[0].getValue() if rr[0] else None
                    v = rr[1].getValue() if rr[1] else None
                    if k is None:
                        continue
                    mapping[str(k)] = "" if v is None else str(v)

                stored = mapping.get(HASH_KEY)
                if not stored:
                    if allow_legacy:
                        ann_ids.append(int(aid))
                    continue

                expected = compute_plugin_hash(mapping)
                if hmac.compare_digest(str(stored), str(expected)):
                    ann_ids.append(int(aid))

            except Exception:
                logger.warning("Failed to verify annotation %s on image %s", aid, iid)
                continue

    except Exception as e:
        logger.exception("Error locating plugin annotations for image %s: %s", image_id, e)

    return ann_ids


def find_annotation_link_ids(conn, annotation_id):
    """Return ImageAnnotationLink IDs for an annotation."""
    try:
        aid = int(annotation_id)
    except Exception:
        return []

    try:
        qs = conn.getQueryService()
        service_opts = getattr(conn, "SERVICE_OPTS", None)

        params = ParametersI()
        params.add("aid", rlong(aid))

        hql = "select l.id from ImageAnnotationLink l where l.child.id = :aid"

        rows = qs.projection(hql, params, service_opts) or []
        return [r[0].getValue() for r in rows if r and r[0]]
    except Exception as e:
        logger.exception("Error locating annotation links for %s: %s", annotation_id, e)
        return []


def find_map_annotation_ids(conn, image_id):
    """Return MapAnnotation IDs linked to an image (key-value pairs)."""
    try:
        iid = int(image_id)
    except Exception:
        return []

    try:
        qs = conn.getQueryService()
        service_opts = getattr(conn, "SERVICE_OPTS", None)

        params = ParametersI()
        params.add("iid", rlong(iid))

        hql_ids = (
            "select distinct a.id "
            "from ImageAnnotationLink l "
            "join l.child a "
            "join a.mapValue mv "
            "where l.parent.id = :iid"
        )

        rows = qs.projection(hql_ids, params, service_opts) or []
        return [r[0].getValue() for r in rows if r and r[0]]
    except Exception as e:
        logger.exception("Error locating map annotations for image %s: %s", image_id, e)
        return []

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
# DATASET-SELECTION COLLECTION
# --------------------------------------------------------------------------
def collect_images_by_selected_datasets(conn, project_id, dataset_ids, limit=None):
    """
    Returns:
        [(dataset_obj, [image_obj_sorted_by_ID]), ...]
    Only includes datasets from dataset_ids, preserving project dataset order.
    """
    out = []
    total = 0
    if not dataset_ids:
        return out

    try:
        wanted = {int(ds_id) for ds_id in dataset_ids}
    except Exception:
        wanted = set()

    if not wanted:
        return out

    try:
        prj = conn.getObject("Project", int(project_id))
        if prj is None:
            return out

        for ds in prj.listChildren():
            ds_id = get_id(ds)
            if ds_id is None:
                continue
            try:
                ds_id_int = int(ds_id)
            except Exception:
                continue
            if ds_id_int not in wanted:
                continue

            imgs = list(ds.listChildren())
            imgs_sorted = sorted(
                imgs, key=lambda img: int(get_id(img)) if get_id(img) else 999999999
            )

            total += len(imgs_sorted)
            if limit and total > limit:
                remaining = limit - (total - len(imgs_sorted))
                imgs_sorted = imgs_sorted[:remaining]
                out.append((ds, imgs_sorted))
                return out

            out.append((ds, imgs_sorted))

    except Exception as e:
        logger.exception("Error collecting selected datasets: %s", e)

    return out


def collect_dataset_summaries(conn, project_id):
    """
    Returns list of dataset summaries for a project.
    """
    summaries = []

    def _format_name_from_image(img):
        try:
            pixels = img.getPrimaryPixels()
        except Exception:
            pixels = None

        if pixels:
            try:
                fmt = pixels.getFormat()
            except Exception:
                fmt = None
            fmt_name = get_text(fmt) if fmt else ""
            if fmt_name:
                return fmt_name

            try:
                pixels_type = pixels.getPixelsType()
            except Exception:
                pixels_type = None
            pixels_type_name = get_text(pixels_type) if pixels_type else ""
            if pixels_type_name:
                return pixels_type_name

        if hasattr(img, "getFormat"):
            try:
                fmt = img.getFormat()
            except Exception:
                fmt = None
            fmt_name = get_text(fmt) if fmt else ""
            if fmt_name:
                return fmt_name

        if hasattr(img, "getName"):
            try:
                name = get_text(img.getName())
            except Exception:
                name = ""
            if name and "." in name:
                ext = name.rsplit(".", 1)[-1]
                if ext:
                    return ext.upper()

        return ""

    try:
        prj = conn.getObject("Project", int(project_id))
        if prj is None:
            return summaries

        for ds in prj.listChildren():
            ds_id = get_id(ds)
            ds_name = get_text(ds.getName())
            try:
                images = list(ds.listChildren())
                image_count = len(images)
            except Exception:
                images = []
                image_count = 0

            format_names = set()
            for img in images:
                fmt_name = _format_name_from_image(img)
                if fmt_name:
                    format_names.add(fmt_name)

            format_list = ", ".join(
                sorted(format_names, key=lambda name: name.lower())
            )

            summaries.append(
                {
                    "id": str(ds_id),
                    "name": ds_name,
                    "image_count": image_count,
                    "formats": format_list,
                }
            )
    except Exception as e:
        logger.exception("Error collecting dataset summaries: %s", e)

    return summaries

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

    Returns:
        (confirmed_sets_deleted, confirmed_pairs_deleted, attempted_sets)
    """
    if mode == "keep":
        return 0, 0, 0

    try:
        annotations = list(img.listAnnotations())
    except Exception as e:
        logger.warning(
            "Cannot list annotations for image %s: %s",
            get_id(img),
            e,
        )
        return 0, 0, 0

    qs = conn.getQueryService()
    service_opts = getattr(conn, "SERVICE_OPTS", None)

    def _delete_links_for_annotation(aid):
        if aid is None:
            return True
        try:
            link_ids = find_annotation_link_ids(conn, aid)
            for lid in link_ids:
                try:
                    link_obj = conn.getObject("ImageAnnotationLink", int(lid))
                except Exception:
                    link_obj = None
                if link_obj is not None:
                    obj = getattr(link_obj, "_obj", link_obj)
                    update.deleteObject(obj)
                    continue

                try:
                    link_stub = ImageAnnotationLinkI()
                    link_stub.setId(rlong(int(lid)))
                    update.deleteObject(link_stub)
                except Exception:
                    logger.warning("Failed to build link stub for %s", lid)
            remaining = find_annotation_link_ids(conn, aid)
            if remaining:
                logger.warning(
                    "Annotation %s still has %s link(s) after delete attempt: %s",
                    aid,
                    len(remaining),
                    remaining,
                )
                return False
            return True
        except Exception as e:
            logger.warning("Failed to delete annotation links for %s: %s", aid, e)
            return False

    def _annotation_exists(aid):
        if aid is None:
            return False
        try:
            params = ParametersI()
            params.add("aid", rlong(int(aid)))
            rows = qs.projection(
                "select a.id from MapAnnotation a where a.id = :aid",
                params,
                service_opts,
            )
            return bool(rows)
        except Exception:
            return True

    def _delete_by_id(aid):
        if aid is None:
            return False
        try:
            links_deleted = _delete_links_for_annotation(aid)
        except Exception as e:
            logger.warning("Failed to delete links for annotation %s: %s", aid, e)
            links_deleted = False
        if not links_deleted:
            logger.warning(
                "Skipping annotation %s delete because links still exist.",
                aid,
            )
            return False
        try:
            ann_obj = conn.getObject("MapAnnotation", int(aid))
        except Exception:
            ann_obj = None
        if ann_obj is None:
            return True
        obj = getattr(ann_obj, "_obj", ann_obj)
        update.deleteObject(obj)
        return not _annotation_exists(aid)

    target_ids = set()

    for ann in annotations:
        try:
            obj = getattr(ann, "_obj", ann)
            if not hasattr(obj, "getMapValue"):
                continue

            ann_id = get_id(ann)
            if ann_id is None:
                continue

            # Best-effort namespace check
            ns = None
            try:
                ns_obj = ann.getNs() if hasattr(ann, "getNs") else obj.getNs()
                ns = ns_obj.getValue() if ns_obj else None
            except Exception:
                pass

            if mode == "all":
                target_ids.add(ann_id)
                continue

            if mode == "plugin":
                if ns != MAP_NS:
                    continue
                if is_plugin_annotation(obj, qs=qs, service_opts=service_opts):
                    target_ids.add(ann_id)
                continue

        except Exception as e:
            logger.warning(
                "Error deleting annotation on image %s: %s",
                get_id(img),
                e,
            )
            continue

    if mode == "all":
        try:
            target_ids.update(find_map_annotation_ids(conn, get_id(img)))
        except Exception:
            logger.warning("Failed to delete map annotations for image %s", get_id(img))

    if mode == "plugin":
        try:
            target_ids.update(find_plugin_annotation_ids(conn, get_id(img), allow_legacy=True))
        except Exception:
            logger.warning("Failed to delete plugin annotations for image %s", get_id(img))

    deleted_sets = 0
    deleted_pairs = 0
    for aid in target_ids:
        try:
            ann_obj = conn.getObject("MapAnnotation", int(aid))
        except Exception:
            ann_obj = None
        pair_count = 0
        if ann_obj is not None:
            try:
                map_values = ann_obj.getMapValue() if hasattr(ann_obj, "getMapValue") else None
                if map_values:
                    pair_count = len(map_values)
            except Exception:
                logger.warning("Failed to read map values for annotation %s", aid)
        deleted = _delete_by_id(aid)
        if deleted:
            deleted_sets += 1
            deleted_pairs += pair_count

    return deleted_sets, deleted_pairs, len(target_ids)
