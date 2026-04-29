"""Environment-backed temporary directory management for OMERO plugins."""

from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

TMP_PATH_ENV = "OMERO_TMP_PATH"


def _validate_path_component(value: str, *, label: str) -> str:
    """Handle validate path component."""
    if value in {"", ".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} must be a single safe path component.")
    return value


def _append_components(base: Path, components: Iterable[str]) -> Path:
    """Handle append components."""
    path = base
    for component in components:
        path /= _validate_path_component(str(component), label="temporary subdirectory")
    return path


def get_tmp_base() -> Path:
    """Return the configured root temporary directory."""
    value = os.environ.get(TMP_PATH_ENV)
    if not value or value.strip() == "":
        raise RuntimeError(
            f"{TMP_PATH_ENV} environment variable is not set. "
            "Ensure it is defined via installation_paths.env and passed into the "
            "container environment through docker-compose env_file loading."
        )
    return Path(value)


def get_plugin_tmp_dir(subdir: str | None = None, *, create: bool = False) -> Path:
    """Return a caller-namespaced temp path, creating it only on request."""
    caller_plugin = _validate_path_component(
        _detect_caller_plugin(),
        label="plugin temporary directory",
    )
    path = get_tmp_base() / caller_plugin
    if subdir:
        path = _append_components(path, Path(subdir).parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _detect_caller_plugin() -> str:
    """Return the hyphenated top-level ``omeroweb_*`` caller package."""
    for frame_info in inspect.stack():
        module = inspect.getmodule(frame_info[0])
        if module is None:
            continue
        top_package = module.__name__.split(".")[0]
        if top_package.startswith("omeroweb_"):
            return top_package.replace("_", "-")
    return "unknown"
