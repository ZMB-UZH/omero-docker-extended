"""Backward-compatible import-workflow helpers.

The production planner/executor lives in ``omeroweb_import.views.core_functions``.
Expose the same helpers here so older imports keep following the canonical
workflow implementation.
"""

from ...views import core_functions as _core

OMERO_CLI = _core.OMERO_CLI
process_utils = _core.process_utils
subprocess = _core.process_utils

_build_sem_edx_associations_from_entries = (
    _core._build_sem_edx_associations_from_entries
)
_check_import_compatibility = _core._check_import_compatibility
_classify_compatibility_output = _core._classify_compatibility_output
_extract_import_candidates = _core._extract_import_candidates
_has_import_candidates_in_output = _core._has_import_candidates_in_output
_import_job_entry = _core._import_job_entry
_normalize_sem_edx_associations = _core._normalize_sem_edx_associations
_parse_candidate_path_line = _core._parse_candidate_path_line
_process_import_job = _core._process_import_job
_run_compatibility_check = _core._run_compatibility_check
_start_compatibility_check_thread = _core._start_compatibility_check_thread
_start_import_thread = _core._start_import_thread

__all__ = [
    "OMERO_CLI",
    "process_utils",
    "subprocess",
    "_classify_compatibility_output",
    "_has_import_candidates_in_output",
    "_extract_import_candidates",
    "_parse_candidate_path_line",
    "_check_import_compatibility",
    "_run_compatibility_check",
    "_start_compatibility_check_thread",
    "_import_job_entry",
    "_process_import_job",
    "_start_import_thread",
    "_normalize_sem_edx_associations",
    "_build_sem_edx_associations_from_entries",
]
