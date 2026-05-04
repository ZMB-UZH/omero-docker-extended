"""
Core services module - backward compatibility layer.

This module re-exports functions from specialized service modules
to maintain backward compatibility with existing imports.

New code should import directly from the specialized modules:
- utils.omero_helpers: get_id, get_text, get_owner_id, is_owned_by_user
- services.jobs.job_storage: load_job, save_job, get_job_path, get_job_lock_path
- services.omero.image_service: fetch_images_by_ids, collect_*, etc.
- services.omero.annotation_service: *_annotation* functions, compute_plugin_hash
- services.omero.metadata_service: extract_acquisition_metadata
- services.parsing.filename_parser: parse_filename
"""

import inspect

from omero.model import ImageAnnotationLinkI, MapAnnotationI
from omero.rtypes import rlong

# Job storage functions
from .jobs.job_storage import (
    load_job,
    save_job,
    get_job_path as _job_path,
    get_job_lock_path as _job_lock_path,
    mark_job_lock_held,
)

# OMERO helper functions (commonly used)
from ..utils.omero_helpers import (
    get_id,
    get_text,
    get_owner_id as _get_owner_id,
    is_owned_by_user as _is_owned_by_user,
)

# Image service functions
from .omero.image_service import (
    fetch_images_by_ids,
    collect_images_by_dataset_sorted,
    collect_images_by_selected_datasets,
    collect_dataset_summaries,
    collect_images_in_project,
)

# Annotation service functions
from .omero import annotation_service as _annotation_service

# Metadata service functions
from .omero.metadata_service import extract_acquisition_metadata

# Parsing functions
from .parsing.filename_parser import parse_filename


def _get_hash_secret():
    """Return hash secret.

    Inputs: none. Output: `get_hash_secret` result.
    """
    return _annotation_service.get_hash_secret()


def _canonicalize_mapping(mapping):
    """Return the canonicalize mapping.

    Inputs: `mapping`. Output: `canonicalize_mapping` result.
    """
    return _annotation_service.canonicalize_mapping(mapping)


def compute_plugin_hash(mapping):
    """Compute the plugin hash.

    Inputs: `mapping`. Output: `compute_plugin_hash` result.
    """
    return _annotation_service.compute_plugin_hash(mapping)


def is_plugin_annotation(annotation):
    """Return whether plugin annotation.

    Inputs: `annotation`. Output: `is_plugin_annotation` result.
    """
    return _annotation_service.is_plugin_annotation(annotation)


def find_plugin_annotation_ids(conn, image_id, allow_legacy=False):
    """Find the plugin annotation IDs.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID, `allow_legacy`.
    Output: `find_plugin_annotation_ids` result.
    """
    return _annotation_service.find_plugin_annotation_ids(
        conn, image_id, allow_legacy=allow_legacy
    )


def find_annotation_link_ids(conn, annotation_ids):
    """Find the annotation link IDs.

    Inputs: `conn` OMERO gateway connection, `annotation_ids`. Output:
    `find_annotation_link_ids` result.
    """
    return _annotation_service.find_annotation_link_ids(conn, annotation_ids)


def find_map_annotation_ids(conn, image_id):
    """Find the map annotation IDs.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID. Output:
    `find_map_annotation_ids` result.
    """
    return _annotation_service.find_map_annotation_ids(conn, image_id)


def _supports_legacy_annotation_kwargs() -> bool:
    """Return whether legacy annotation kwargs.

    Inputs: none. Output: `bool`.
    """
    try:
        parameters = inspect.signature(
            _annotation_service.delete_existing_annotations
        ).parameters.values()
    except (TypeError, ValueError):
        return False

    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return True
    parameter_names = {parameter.name for parameter in parameters}
    return {"annotation_ids", "link_ids", "allow_legacy"} <= parameter_names


def _legacy_annotation_delete_callable():
    """Return the legacy annotation delete callable.

    Inputs: none. Output: `delete_existing_annotations`.
    """
    return _annotation_service.delete_existing_annotations


def _call_dynamic(callable_obj, *args, **kwargs):
    """Return the call dynamic.

    Inputs: `callable_obj`, `*args` positional arguments, `**kwargs` keyword arguments.
    Output: `callable_obj` result.
    """
    return callable_obj(*args, **kwargs)


def _call_legacy_annotation_delete(
    conn,
    image_id,
    annotation_ids=None,
    link_ids=None,
    allow_legacy=False,
):
    """Return the call legacy annotation delete.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID,
    `annotation_ids`, `link_ids`, `allow_legacy`. Output: `_call_dynamic` result.
    """
    legacy_delete_existing_annotations = _legacy_annotation_delete_callable()
    legacy_kwargs = {
        "annotation_ids": annotation_ids,
        "link_ids": link_ids,
        "allow_legacy": allow_legacy,
    }
    return _call_dynamic(
        legacy_delete_existing_annotations,
        conn,
        image_id,
        **legacy_kwargs,
    )


def _normalize_annotation_ids(values):
    """Normalize the annotation IDs.

    Inputs: `values`. Output: `normalized`.
    """
    normalized = []
    seen = set()
    for value in values or []:
        item_id = _try_normalize_annotation_id(value)
        if item_id is None:
            continue
        if item_id in seen:
            continue
        seen.add(item_id)
        normalized.append(item_id)
    return normalized


def _try_normalize_annotation_id(value):
    """Return the try normalize annotation ID.

    Inputs: `value` input value. Output: `int`.
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _delete_object_by_id(conn, update, object_type, stub_type, object_id):
    """Delete the object by ID.

    Inputs: `conn` OMERO gateway connection, `update`, `object_type`, `stub_type`,
    `object_id`. Output: `bool`.
    """
    if object_type == "MapAnnotation":
        conn.deleteObjects("Annotation", [int(object_id)], wait=True)
        return True

    try:
        obj = conn.getObject(object_type, int(object_id))
    except Exception:
        obj = None
    if obj is not None:
        update.deleteObject(getattr(obj, "_obj", obj))
        return True

    stub = stub_type()
    stub.setId(rlong(int(object_id)))
    update.deleteObject(stub)
    return True


def _delete_existing_annotations_by_ids(
    conn, image_id, *, annotation_ids=None, link_ids=None, allow_legacy=False
):
    """Delete the existing annotations by IDs.

    Inputs: `conn` OMERO gateway connection, `image_id` OMERO image ID,
    `annotation_ids`, `link_ids`, `allow_legacy`. Output: `tuple`.
    """
    resolved_annotation_ids = _normalize_annotation_ids(
        annotation_ids
        if annotation_ids is not None
        else find_plugin_annotation_ids(conn, image_id, allow_legacy=allow_legacy)
    )

    if link_ids is None:
        derived_link_ids = []
        for annotation_id in resolved_annotation_ids:
            derived_link_ids.extend(find_annotation_link_ids(conn, annotation_id))
        resolved_link_ids = _normalize_annotation_ids(derived_link_ids)
    else:
        resolved_link_ids = _normalize_annotation_ids(link_ids)

    update = conn.getUpdateService()
    deleted_links = 0
    for link_id in resolved_link_ids:
        if _delete_object_by_id(
            conn,
            update,
            "ImageAnnotationLink",
            ImageAnnotationLinkI,
            link_id,
        ):
            deleted_links += 1

    deleted_annotations = 0
    for annotation_id in resolved_annotation_ids:
        if _delete_object_by_id(
            conn,
            update,
            "MapAnnotation",
            MapAnnotationI,
            annotation_id,
        ):
            deleted_annotations += 1

    return deleted_annotations, deleted_links, len(resolved_annotation_ids)


def delete_existing_annotations(
    conn, *args, annotation_ids=None, link_ids=None, allow_legacy=False
):
    """Delete the existing annotations.

    Inputs: `conn` OMERO gateway connection, `*args` positional arguments,
    `annotation_ids`, `link_ids`, `allow_legacy`. Output: `delete_existing_annotations`
    Raises: TypeError when validation or the called operation fails.
    """
    uses_legacy_id_api = (
        annotation_ids is not None or link_ids is not None or len(args) == 1
    )
    if uses_legacy_id_api:
        if len(args) != 1:
            raise TypeError(
                "Legacy delete_existing_annotations calls require exactly one "
                "image_id positional argument."
            )
        image_id = args[0]
        if _supports_legacy_annotation_kwargs():
            return _call_legacy_annotation_delete(
                conn,
                image_id,
                annotation_ids=annotation_ids,
                link_ids=link_ids,
                allow_legacy=allow_legacy,
            )
        return _delete_existing_annotations_by_ids(
            conn,
            image_id,
            annotation_ids=annotation_ids,
            link_ids=link_ids,
            allow_legacy=allow_legacy,
        )

    if len(args) != 4:
        raise TypeError(
            "delete_existing_annotations expects either "
            "(conn, image_id, *, annotation_ids=..., link_ids=..., allow_legacy=...) "
            "or (conn, update, img, var_names, mode)."
        )
    update, img, var_names, mode = args
    return _annotation_service.delete_existing_annotations(
        conn,
        update,
        img,
        var_names,
        mode,
    )


# Export all for backward compatibility
__all__ = [
    # Job storage
    "load_job",
    "save_job",
    "_job_path",
    "_job_lock_path",
    "mark_job_lock_held",
    # OMERO helpers
    "get_id",
    "get_text",
    "_get_owner_id",
    "_is_owned_by_user",
    # Image service
    "fetch_images_by_ids",
    "collect_images_by_dataset_sorted",
    "collect_images_by_selected_datasets",
    "collect_dataset_summaries",
    "collect_images_in_project",
    # Annotation service
    "_get_hash_secret",
    "_canonicalize_mapping",
    "compute_plugin_hash",
    "is_plugin_annotation",
    "find_plugin_annotation_ids",
    "find_annotation_link_ids",
    "find_map_annotation_ids",
    "delete_existing_annotations",
    # Metadata service
    "extract_acquisition_metadata",
    # Parsing
    "parse_filename",
]
