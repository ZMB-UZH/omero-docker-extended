"""Environment-backed temporary directory management for OMERO plugins."""

from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

TMP_PATH_ENV = "OMERO_TMP_PATH"
_PLUGIN_PACKAGE_PREFIXES = ("omeroweb_", "omero_")
_NON_PLUGIN_PACKAGES = {"omero_plugin_common"}


def _validate_path_component(value: str, *, label: str) -> str:
    """Validate the path component.

    Inputs: `value` (str) input value, `label` (str). Output: `str`. Raises: ValueError
    when validation or the called operation fails.
    """
    if value in {"", ".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} must be a single safe path component.")
    return value


def _append_components(base: Path, components: Iterable[str]) -> Path:
    """Append the components.

    Inputs: `base` (Path), `components` (Iterable[str]). Output: `Path`.
    """
    path = base
    for component in components:
        path /= _validate_path_component(str(component), label="temporary subdirectory")
    return path


def get_tmp_base() -> Path:
    """Return the configured root temporary directory.

    Inputs: none. Output: `Path`. Raises: RuntimeError for the exercised failure path.
    """
    value = os.environ.get(TMP_PATH_ENV)
    if not value or value.strip() == "":
        raise RuntimeError(
            f"{TMP_PATH_ENV} environment variable is not set. "
            "Ensure it is defined via installation_paths.env and passed into the "
            "container environment through docker-compose env_file loading."
        )
    return Path(value)


def get_plugin_tmp_dir(
    subdir: str | None = None,
    *,
    create: bool = False,
    plugin: str | None = None,
) -> Path:
    """Return a caller-namespaced temp path, creating it only on request.

    Inputs: `subdir`, `create`, optional plugin namespace. Output: `Path`.
    """
    caller_plugin = _validate_path_component(
        plugin or _detect_caller_plugin(),
        label="plugin temporary directory",
    )
    path = get_tmp_base() / caller_plugin
    if subdir:
        path = _append_components(path, Path(subdir).parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _detect_caller_plugin() -> str:
    """Return the hyphenated top-level OMERO plugin caller package.

    Inputs: none. Output: `str`.
    """
    for frame_info in inspect.stack():
        module = inspect.getmodule(frame_info[0])
        if module is None:
            continue
        top_package = module.__name__.split(".")[0]
        if top_package in _NON_PLUGIN_PACKAGES:
            continue
        if top_package.startswith(_PLUGIN_PACKAGE_PREFIXES):
            return top_package.replace("_", "-")
    return "unknown"
