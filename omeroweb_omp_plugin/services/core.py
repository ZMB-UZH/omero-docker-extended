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

# Job storage functions
from .jobs.job_storage import (
    load_job,
    save_job,
    get_job_path as _job_path,
    get_job_lock_path as _job_lock_path,
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
from .omero.annotation_service import (
    get_hash_secret as _get_hash_secret,
    canonicalize_mapping as _canonicalize_mapping,
    compute_plugin_hash,
    is_plugin_annotation,
    find_plugin_annotation_ids,
    find_annotation_link_ids,
    find_map_annotation_ids,
    delete_existing_annotations,
)

# Metadata service functions
from .omero.metadata_service import extract_acquisition_metadata

# Parsing functions
from .parsing.filename_parser import parse_filename

# Export all for backward compatibility
__all__ = [
    # Job storage
    "load_job",
    "save_job",
    "_job_path",
    "_job_lock_path",
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
