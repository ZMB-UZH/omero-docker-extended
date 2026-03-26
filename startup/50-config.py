#!/usr/bin/env python3
"""Apply OMERO.web config files and CONFIG_ environment overrides."""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LEGACY_CONFIG_ALIASES = {
    "omeroweb_upload": "omeroweb_import",
    "omeroweb_upload_index": "omeroweb_import_index",
    "/omeroweb_upload/": "/omeroweb_import/",
}


def resolve_omero_bin() -> str:
    explicit = os.environ.get("OMERO_WEB_OMERO_BIN") or os.environ.get("OMERO_BIN")
    if explicit:
        return explicit

    from_path = shutil.which("omero")
    if from_path:
        return from_path

    configured_venv = os.environ.get("OMERO_WEB_VENV")
    candidates: list[Path] = []
    if configured_venv:
        candidates.append(Path("/opt/omero/web") / configured_venv / "bin" / "omero")
    candidates.extend(
        sorted(Path("/opt/omero/web").glob("venv*/bin/omero"), reverse=True)
    )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError("Could not resolve an OMERO CLI binary for OMERO.web startup")


def resolve_web_python_bin(omero_bin: str) -> str:
    explicit = os.environ.get("OMERO_WEB_PYTHON_BIN") or os.environ.get("PYTHON_BIN")
    if explicit:
        return explicit

    omero_path = Path(omero_bin)
    for candidate_name in ("python3", "python"):
        candidate = omero_path.with_name(candidate_name)
        if candidate.is_file():
            return str(candidate)

    configured_venv = os.environ.get("OMERO_WEB_VENV")
    candidates: list[Path] = []
    if configured_venv:
        venv_root = Path("/opt/omero/web") / configured_venv / "bin"
        candidates.extend([venv_root / "python3", venv_root / "python"])
    for venv_root in sorted(Path("/opt/omero/web").glob("venv*/bin"), reverse=True):
        candidates.extend([venv_root / "python3", venv_root / "python"])

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError(
        "Could not resolve an OMERO.web Python binary for startup validation"
    )


def config_env_to_property(env_name: str) -> str:
    prop = env_name[7:]
    prop = re.sub(r"([^_])_([^_])", r"\1.\2", prop)
    prop = re.sub(r"__", "_", prop)
    return prop


def run_omero_command(omero_bin: str, *args: str) -> None:
    subprocess.run([omero_bin, *args], check=True)


def _normalize_aliases(value: object) -> object:
    if isinstance(value, str):
        return LEGACY_CONFIG_ALIASES.get(value, value)
    if isinstance(value, list):
        return [_normalize_aliases(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_aliases(item) for key, item in value.items()}
    return value


def normalize_config_value(env_name: str, raw_value: str) -> str:
    normalized_scalar = LEGACY_CONFIG_ALIASES.get(raw_value)
    if normalized_scalar is not None:
        return normalized_scalar

    stripped = raw_value.strip()
    if not stripped or stripped[0] not in "[{":
        return raw_value

    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value

    normalized = _normalize_aliases(decoded)
    if normalized == decoded:
        return raw_value

    print(
        f"[50-config.py] Normalized legacy aliases in {env_name}",
        file=sys.stderr,
    )
    return json.dumps(normalized, separators=(",", ":"))


def parse_additional_apps(raw_value: str) -> list[str]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "CONFIG_omero_web_apps must be a JSON array of app module names"
        ) from exc

    if not isinstance(parsed, list) or not all(
        isinstance(item, str) for item in parsed
    ):
        raise RuntimeError(
            "CONFIG_omero_web_apps must be a JSON array of app module names"
        )

    return parsed


def validate_additional_apps(python_bin: str, app_modules: list[str]) -> None:
    if not app_modules:
        return

    validation_script = """
import importlib
import sys

missing = []
for module_name in sys.argv[1:]:
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            missing.append(module_name)
        else:
            raise

if missing:
    sys.stderr.write(
        "Missing OMERO.web app modules referenced by CONFIG_omero_web_apps: "
        + ", ".join(missing)
        + "\\n"
    )
    sys.exit(1)
"""
    subprocess.run([python_bin, "-c", validation_script, *app_modules], check=True)


def main() -> int:
    omero_bin = resolve_omero_bin()
    python_bin = resolve_web_python_bin(omero_bin)
    config_glob = os.environ.get(
        "OMERO_WEB_CONFIG_GLOB", "/opt/omero/web/config/*.omero"
    )

    if glob.glob(config_glob):
        run_omero_command(omero_bin, "load", "--glob", config_glob)

    normalized_config: dict[str, str] = {}
    for key in sorted(os.environ):
        if not key.startswith("CONFIG_"):
            continue
        normalized_config[key] = normalize_config_value(key, os.environ[key])

    additional_apps = normalized_config.get("CONFIG_omero_web_apps")
    if additional_apps is not None:
        validate_additional_apps(python_bin, parse_additional_apps(additional_apps))

    for key in sorted(normalized_config):
        run_omero_command(
            omero_bin,
            "config",
            "set",
            "--",
            config_env_to_property(key),
            normalized_config[key],
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - exercised via subprocess
        print(f"[50-config.py] ERROR: {exc}", file=sys.stderr)
        raise
