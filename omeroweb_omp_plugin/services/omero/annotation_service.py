"""OMERO annotation services for managing MapAnnotations."""

import json
import logging
import hashlib
import hmac

from django.conf import settings
from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_optional_env
from omero.rtypes import rstring, rlong
from omero.sys import ParametersI

from ...constants import (
    MAP_NS,
    HASH_KEY,
    HASH_PREFIX,
    PLUGIN_ID,
    HASH_HMAC_KEY_ENV,
)
from ...utils.omero_helpers import get_id

logger = logging.getLogger(__name__)


def get_hash_secret():
    """Return secret used to compute/verify plugin hash marker.

    Inputs: none. Output: secret from env or Django settings.
    """
    return get_optional_env(HASH_HMAC_KEY_ENV, env_file=ENV_FILE_OMEROWEB) or str(
        getattr(settings, "SECRET_KEY", "") or ""
    )


def _effective_hash_secret():
    """Return the non-empty secret used for ownership-marker HMAC.

    Inputs: none. Output: secret string. Raises RuntimeError if no private secret exists.
    """
    secret = str(get_hash_secret() or getattr(settings, "SECRET_KEY", "") or "")
    if secret:
        return secret
    raise RuntimeError(  # pragma: no cover - deployment misconfiguration guard
        f"Missing non-empty {HASH_HMAC_KEY_ENV} or Django SECRET_KEY for "
        "OMP annotation ownership hashing."
    )


def canonicalize_mapping(mapping):
    """Return deterministic JSON payload for hashing.

    Inputs: `mapping`. Output: `json.dumps` result.

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
    """Compute the value stored under HASH_KEY.

    Inputs: `mapping`. Output: `f'{HASH_PREFIX}{digest}'`.
    """
    payload = canonicalize_mapping(mapping)
    secret = _effective_hash_secret()
    digest = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{HASH_PREFIX}{digest}"


def is_plugin_annotation(map_ann_obj, qs=None, service_opts=None):
    """Return True if MapAnnotation was created by this plugin.

    Inputs: `map_ann_obj`, `qs`, `service_opts`. Output: `compare_digest` result.
    """

    def _unwrap(val):
        """Return the unwrap.

        Inputs: `val`. Output: `val`.
        """
        if callable(getattr(val, "getValue", None)):
            try:
                return val.getValue()
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in annotation_service.py",
                    exc_info=exc,
                )
        # Some OMERO rtypes expose `.val` instead of `.getValue()`
        val = getattr(val, "val", val)
        return val

    def _extract_pair(nv):
        """Return (name, value) tuple from a NamedValue or (name, value) pair.

        Inputs: `nv`. Output: tuple or None.
        """
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
        """Load the pairs from qs.

        Inputs: `aid`. Output: `list`.
        """
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
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in annotation_service.py",
                    exc_info=exc,
                )

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


def find_plugin_annotation_ids(conn, image_id, allow_legacy=False):
    """Return plugin-owned MapAnnotation IDs; legacy matching is opt-in.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID, `allow_legacy`.
    Output: `ann_ids`.
    """
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
        logger.exception(
            "Error locating plugin annotations for image %s: %s", image_id, e
        )

    return ann_ids


def find_annotation_link_ids(conn, annotation_id, image_id=None):
    """Return ImageAnnotationLink IDs for an annotation and optional image.

    Inputs: `conn` OMERO gateway connection, `annotation_id`, optional `image_id`.
    Output: ID value list.
    """
    try:
        aid = int(annotation_id)
    except Exception:
        return []
    try:
        iid = None if image_id is None else int(image_id)
    except Exception:
        return []

    try:
        qs = conn.getQueryService()
        service_opts = getattr(conn, "SERVICE_OPTS", None)

        params = ParametersI()
        params.add("aid", rlong(aid))
        if iid is not None:
            params.add("iid", rlong(iid))

        if iid is None:
            hql = "select l.id from ImageAnnotationLink l where l.child.id = :aid"
        else:
            hql = (
                "select l.id from ImageAnnotationLink l "
                "where l.child.id = :aid and l.parent.id = :iid"
            )

        rows = qs.projection(hql, params, service_opts) or []
        return [r[0].getValue() for r in rows if r and r[0]]
    except Exception as e:
        logger.exception("Error locating annotation links for %s: %s", annotation_id, e)
        return []


def find_map_annotation_ids(conn, image_id):
    """Return MapAnnotation IDs linked to an image (key-value pairs).

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID. Output: ID
    value.
    """
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


def delete_existing_annotations(conn, _update, img, var_names, mode):
    """Delete the existing annotations.

    Inputs: `conn` OMERO gateway connection, `_update`, `img`, `var_names`, `mode`.
    Output: `bool`.
    """
    _ = var_names
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

    def _annotation_exists(aid):
        """Return the annotation exists.

        Inputs: `aid`. Output: `bool`.
        """
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

    image_id = get_id(img)

    def _delete_link_by_id(aid, lid):
        """Delete one image-annotation link by ID.

        Inputs: `aid`, `lid`. Output: `bool`.
        """
        try:
            link_obj = conn.getObject("ImageAnnotationLink", int(lid))
        except Exception:
            link_obj = None

        try:
            if link_obj is not None:
                _update.deleteObject(getattr(link_obj, "_obj", link_obj))
            else:
                conn.deleteObjects("ImageAnnotationLink", [int(lid)], wait=True)
        except Exception as e:  # pragma: no cover - OMERO gateway failure guard
            logger.warning(
                "Failed to delete annotation link %s for annotation %s: %s",
                lid,
                aid,
                e,
            )
            return False

        try:
            remaining_links = find_annotation_link_ids(conn, aid, image_id=image_id)
        except Exception as e:  # pragma: no cover - OMERO gateway failure guard
            logger.warning(
                "Failed to confirm annotation link %s cleanup for annotation %s: %s",
                lid,
                aid,
                e,
            )
            return False
        if int(lid) in [int(link_id) for link_id in remaining_links]:
            logger.warning(
                "Annotation %s still has scoped link %s after delete attempt",
                aid,
                lid,
            )
            return False
        return True

    def _delete_annotation_if_unlinked(aid):
        """Delete an annotation only when no image links remain.

        Inputs: `aid`. Output: `bool`.
        """
        try:
            remaining_links = find_annotation_link_ids(conn, aid)
        except Exception as e:  # pragma: no cover - OMERO gateway failure guard
            logger.warning(
                "Failed to load remaining links for annotation %s: %s", aid, e
            )
            return False
        if remaining_links:  # pragma: no cover - defensive OMERO residue guard
            logger.info(
                "Preserving annotation %s because it still has %s link(s)",
                aid,
                len(remaining_links),
            )
            return True

        try:
            conn.deleteObjects("Annotation", [int(aid)], wait=True)
        except Exception as e:  # pragma: no cover - OMERO gateway failure guard
            logger.warning(
                "Failed to delete annotation %s through OMERO delete service: %s",
                aid,
                e,
            )
            return False

        try:
            remaining_links = find_annotation_link_ids(conn, aid)
        except Exception as e:  # pragma: no cover - OMERO gateway failure guard
            logger.warning(
                "Failed to confirm annotation %s link cleanup after delete: %s",
                aid,
                e,
            )
            return False
        if remaining_links:  # pragma: no cover - defensive OMERO residue guard
            logger.warning(
                "Annotation %s still has %s link(s) after delete attempt: %s",
                aid,
                len(remaining_links),
                remaining_links,
            )
            return False

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
            except Exception as exc:
                logger.debug(
                    "Suppressed non-fatal exception in annotation_service.py",
                    exc_info=exc,
                )

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
            target_ids.update(
                find_plugin_annotation_ids(conn, get_id(img), allow_legacy=False)
            )
        except Exception:
            logger.warning(
                "Failed to delete plugin annotations for image %s", get_id(img)
            )

    deleted_sets = 0
    deleted_pairs = 0
    for aid in sorted(target_ids):
        try:
            ann_obj = conn.getObject("MapAnnotation", int(aid))
        except Exception:
            ann_obj = None
        pair_count = 0
        if ann_obj is not None:
            try:
                map_values = (
                    ann_obj.getMapValue() if hasattr(ann_obj, "getMapValue") else None
                )
                if map_values:
                    pair_count = len(map_values)
            except Exception:
                logger.warning("Failed to read map values for annotation %s", aid)
        try:
            scoped_links = find_annotation_link_ids(conn, aid, image_id=image_id)
        except Exception as e:
            logger.warning(
                "Failed to load scoped annotation links for annotation %s on image %s: %s",
                aid,
                image_id,
                e,
            )
            continue
        if not scoped_links:  # pragma: no cover - defensive OMERO residue guard
            logger.warning(
                "No image-scoped annotation links found for annotation %s on image %s",
                aid,
                image_id,
            )
            continue

        links_deleted = True
        for lid in scoped_links:
            links_deleted = _delete_link_by_id(aid, lid) and links_deleted
        if not links_deleted:
            continue

        try:
            remaining_scoped_links = find_annotation_link_ids(
                conn, aid, image_id=image_id
            )
        except Exception as e:  # pragma: no cover - OMERO gateway failure guard
            logger.warning(
                "Failed to confirm scoped annotation cleanup for annotation %s on image %s: %s",
                aid,
                image_id,
                e,
            )
            continue
        if remaining_scoped_links:  # pragma: no cover - defensive OMERO residue guard
            logger.warning(
                "Annotation %s still has %s scoped link(s) on image %s: %s",
                aid,
                len(remaining_scoped_links),
                image_id,
                remaining_scoped_links,
            )
            continue

        deleted = _delete_annotation_if_unlinked(aid)
        if deleted:
            deleted_sets += 1
            deleted_pairs += pair_count

    return deleted_sets, deleted_pairs, len(target_ids)
