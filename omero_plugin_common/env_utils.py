"""Shared environment variable helpers for OMERO plugins."""

from __future__ import annotations

import os
from typing import Callable

ENV_FILE_OMEROWEB = "env/omeroweb.env"
ENV_FILE_OMEROSERVER = "env/omeroserver.env"
ENV_FILE_OMERO_CELERY = "env/omero-celery.env"


def _env_reference(env_file: str, docs_url: str | None) -> str:
    reference = f"Set it in {env_file} (referenced by docker-compose.yml)."
    if docs_url:
        reference = f"{reference} See {docs_url}."
    return reference


def _missing_env_message(
    name: str,
    env_file: str,
    *,
    hint: str | None = None,
    docs_url: str | None = None,
) -> str:
    message = f"Missing required environment variable: {name}. "
    message += _env_reference(env_file, docs_url)
    if hint:
        message = f"{message} {hint}"
    return message


def _invalid_env_message(
    name: str,
    value: str,
    env_file: str,
    *,
    expected: str,
    docs_url: str | None = None,
) -> str:
    message = (
        f"Invalid value for {name} in {env_file}: {value!r}. Expected {expected}. "
        f"{_env_reference(env_file, docs_url)}"
    )
    return message


def get_env(
    name: str,
    *,
    env_file: str,
    allow_empty: bool = False,
    hint: str | None = None,
    docs_url: str | None = None,
) -> str:
    """Return a required environment variable."""
    return require_env(
        name,
        env_file=env_file,
        allow_empty=allow_empty,
        hint=hint,
        docs_url=docs_url,
    )


def get_optional_env(
    name: str,
    *,
    env_file: str,
    allow_empty: bool = False,
) -> str | None:
    """Return an environment variable or None when unset."""
    value = os.environ.get(name)
    if value is None:
        return None
    if not allow_empty and str(value).strip() == "":
        return None
    return value


def require_env(
    name: str,
    *,
    env_file: str,
    allow_empty: bool = False,
    hint: str | None = None,
    docs_url: str | None = None,
) -> str:
    """Return a required environment variable or raise."""
    value = os.environ.get(name)
    if value is None or (not allow_empty and str(value).strip() == ""):
        raise RuntimeError(
            _missing_env_message(name, env_file, hint=hint, docs_url=docs_url)
        )
    return value


def get_int_env(
    name: str,
    *,
    env_file: str,
    docs_url: str | None = None,
) -> int:
    """Return a required integer environment variable with validation."""
    raw = require_env(name, env_file=env_file, docs_url=docs_url)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            _invalid_env_message(
                name,
                raw,
                env_file,
                expected="an integer",
                docs_url=docs_url,
            )
        ) from exc


def get_float_env(
    name: str,
    *,
    env_file: str,
    docs_url: str | None = None,
) -> float:
    """Return a required float environment variable with validation."""
    raw = require_env(name, env_file=env_file, docs_url=docs_url)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            _invalid_env_message(
                name,
                raw,
                env_file,
                expected="a number",
                docs_url=docs_url,
            )
        ) from exc


def get_bool_env(
    name: str,
    *,
    env_file: str,
    docs_url: str | None = None,
) -> bool:
    """Return a required boolean environment variable with validation."""
    raw = require_env(name, env_file=env_file, docs_url=docs_url)
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        _invalid_env_message(
            name,
            raw,
            env_file,
            expected="a boolean (true/false)",
            docs_url=docs_url,
        )
    )


def get_sanitized_int_env(
    name: str,
    *,
    env_file: str,
    sanitizer: Callable[[str], str],
    min_value: int,
    max_value: int,
    docs_url: str | None = None,
) -> int:
    """Return a required sanitized integer environment variable with bounds."""
    raw = require_env(name, env_file=env_file, docs_url=docs_url)
    sanitized = sanitizer(str(raw))
    if sanitized.strip() == "":
        raise ValueError(
            _invalid_env_message(
                name,
                raw,
                env_file,
                expected="a non-empty integer",
                docs_url=docs_url,
            )
        )
    try:
        value = int(sanitized)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            _invalid_env_message(
                name,
                raw,
                env_file,
                expected="an integer",
                docs_url=docs_url,
            )
        ) from exc
    return max(min_value, min(max_value, value))
