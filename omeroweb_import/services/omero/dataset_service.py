"""Backward-compatible dataset helpers.

The canonical import implementation still lives in
``omeroweb_import.views.core_functions``.  This module intentionally re-exports
those helpers so service-oriented callers use the same code path instead of
carrying a stale duplicate copy.
"""

from ...views.core_functions import (  # noqa: F401
    _build_omero_cli_command,
    _collect_project_payload,
    _dataset_name_for_path,
    _find_project_dataset,
    _generate_orphan_dataset_name,
    _get_or_create_dataset,
    _get_session_key,
    _iter_accessible_projects,
    _link_dataset_to_project,
    _resolve_omero_host_port,
)

__all__ = [
    "_collect_project_payload",
    "_dataset_name_for_path",
    "_generate_orphan_dataset_name",
    "_find_project_dataset",
    "_link_dataset_to_project",
    "_resolve_omero_host_port",
    "_get_session_key",
    "_get_or_create_dataset",
    "_build_omero_cli_command",
    "_iter_accessible_projects",
]
