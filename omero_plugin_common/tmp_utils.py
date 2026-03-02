"""Centralized temporary directory management for OMERO plugins.

Provides a single mechanism for all plugins to obtain persistent,
automatically namespaced temporary directories on the host-mounted
OMERO_TMP_PATH volume.

The calling plugin is auto-detected from the Python call stack so that
each plugin gets its own subfolder without hardcoding plugin names.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Environment variable name – matches the host-side variable in
# installation_paths.env and the container-side variable in omeroweb.env.
TMP_PATH_ENV = "OMERO_TMP_PATH"


def get_tmp_base() -> Path:
    """Return the root temporary directory from the environment.

    Raises
    ------
    RuntimeError
        If ``OMERO_TMP_PATH`` is not set.
    """
    value = os.environ.get(TMP_PATH_ENV)
    if not value:
        raise RuntimeError(
            f"{TMP_PATH_ENV} environment variable is not set. "
            "Ensure it is defined in env/omeroweb.env and that the "
            "container receives it via env_file in docker-compose.yml."
        )
    return Path(value)


def get_plugin_tmp_dir(subdir: str | None = None) -> Path:
    """Return a plugin-specific temporary directory, creating it if needed.

    The owning plugin is determined automatically from the call stack by
    finding the first module whose top-level package starts with
    ``omeroweb_``.

    Parameters
    ----------
    subdir:
        Optional subdirectory within the plugin's temp folder.
        For example ``"jobs"`` or ``"data"``.

    Returns
    -------
    Path
        Fully resolved path, guaranteed to exist.

    Examples
    --------
    Called from ``omeroweb_upload/utils/file_helpers.py``::

        get_plugin_tmp_dir("data")
        # → /opt/omero/omero_temp/omeroweb-upload/data

    Called from ``omeroweb_omp_plugin/constants.py``::

        get_plugin_tmp_dir("jobs")
        # → /opt/omero/omero_temp/omeroweb-omp-plugin/jobs
    """
    caller_plugin = _detect_caller_plugin()
    path = get_tmp_base() / caller_plugin
    if subdir:
        path = path / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _detect_caller_plugin() -> str:
    """Walk the call stack to find the calling plugin's package name.

    Returns a hyphenated directory-safe name such as ``omeroweb-upload``
    derived from the top-level Python package ``omeroweb_upload``.
    """
    for frame_info in inspect.stack():
        module = inspect.getmodule(frame_info[0])
        if module is None:
            continue
        top_package = module.__name__.split(".")[0]
        if top_package.startswith("omeroweb_"):
            return top_package.replace("_", "-")
    return "unknown"
