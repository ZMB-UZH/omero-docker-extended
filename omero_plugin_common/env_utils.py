"""Shared environment variable helpers for OMERO plugins."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TypeVar

ENV_FILE_OMEROWEB = "env/omeroweb.env"
ENV_FILE_OMEROSERVER = "env/omeroserver.env"
ENV_FILE_OMERO_CELERY = "env/omero-celery.env"

_BOOL_VALUES = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}
_T = TypeVar("_T")


def _env_reference(env_file: str, docs_url: str | None) -> str:
    """Return the environment reference.

    Inputs: `env_file` (str) environment file path, `docs_url` (str | None). Output:
    `str`.
    """
    reference = f"Set it in {env_file} (referenced by docker-compose.yml)."
    return f"{reference} See {docs_url}." if docs_url else reference


def _missing_env_message(
    name: str,
    env_file: str,
    *,
    hint: str | None = None,
    docs_url: str | None = None,
) -> str:
    """Build the operator-facing message for a missing environment variable.

    Inputs: `name`, `env_file`, `hint`, `docs_url`. Output: `str`.
    """
    message = (
        f"Missing required environment variable: {name}. "
        f"{_env_reference(env_file, docs_url)}"
    )
    return f"{message} {hint}" if hint else message


def _invalid_env_message(
    name: str,
    value: str,
    env_file: str,
    *,
    expected: str,
    docs_url: str | None = None,
) -> str:
    """Build the operator-facing message for an invalid environment value.

    Inputs: `name`, `value`, `env_file`, `expected`, `docs_url`. Output: `str`.
    """
    return (
        f"Invalid value for {name} in {env_file}: {value!r}. Expected {expected}. "
        f"{_env_reference(env_file, docs_url)}"
    )


def _read_env(name: str, *, env_file: str, allow_empty: bool) -> str | None:
    """Read the environment.

    Inputs: `name` (str) name, `env_file` (str) environment file path, `allow_empty`
    (bool). Output: `str | None`. Raises: ValueError for the exercised failure path.
    """
    if not env_file:
        raise ValueError("env_file must identify the configuration contract.")
    value = os.environ.get(name)
    return None if value is None or (not allow_empty and value.strip() == "") else value


def _coerce(
    name: str,
    value: str,
    *,
    env_file: str,
    expected: str,
    parser: Callable[[str], _T],
    docs_url: str | None = None,
) -> _T:
    """Coerce the coerce.

    Inputs: `name` (str) name, `value` (str) input value, `env_file` (str) environment
    file path, `expected` (str), `parser` (Callable[[str], _T]), `docs_url` (str |
    None). Output: `_T`. Raises: ValueError when validation or the called operation fails.
    """
    try:
        return parser(value)
    except (LookupError, TypeError, ValueError) as exc:
        raise ValueError(
            _invalid_env_message(
                name,
                value,
                env_file,
                expected=expected,
                docs_url=docs_url,
            )
        ) from exc


def get_env(
    name: str,
    *,
    env_file: str,
    allow_empty: bool = False,
    hint: str | None = None,
    docs_url: str | None = None,
) -> str:
    """Return a required environment variable.

    Inputs: `name`, `env_file`, `allow_empty`, `hint`, `docs_url`. Output: `str`.
    """
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
    """Return an environment variable or None when unset.

    Inputs: `name`, `env_file`, `allow_empty`. Output: `str | None`.
    """
    return _read_env(name, env_file=env_file, allow_empty=allow_empty)


def require_env(
    name: str,
    *,
    env_file: str,
    allow_empty: bool = False,
    hint: str | None = None,
    docs_url: str | None = None,
) -> str:
    """Return a required environment variable or raise.

    Inputs: `name` (str) name, `env_file` (str) environment file path, `allow_empty`
    (bool), `hint` (str | None), `docs_url` (str | None). Output: `str`. Raises:
    RuntimeError when validation or the called operation fails.
    """
    value = _read_env(name, env_file=env_file, allow_empty=allow_empty)
    if value is None:
        raise RuntimeError(
            _missing_env_message(name, env_file, hint=hint, docs_url=docs_url)
        )
    return value


def get_int_env(name: str, *, env_file: str, docs_url: str | None = None) -> int:
    """Return a required integer environment variable with validation.

    Inputs: `name`, `env_file`, `docs_url`. Output: `int`.
    """
    return _coerce(
        name,
        require_env(name, env_file=env_file, docs_url=docs_url),
        env_file=env_file,
        expected="an integer",
        parser=int,
        docs_url=docs_url,
    )


def get_float_env(name: str, *, env_file: str, docs_url: str | None = None) -> float:
    """Return a required float environment variable with validation.

    Inputs: `name`, `env_file`, `docs_url`. Output: `float`.
    """
    return _coerce(
        name,
        require_env(name, env_file=env_file, docs_url=docs_url),
        env_file=env_file,
        expected="a number",
        parser=float,
        docs_url=docs_url,
    )


def get_bool_env(name: str, *, env_file: str, docs_url: str | None = None) -> bool:
    """Return a required boolean environment variable with validation.

    Inputs: `name`, `env_file`, `docs_url`. Output: `bool`.
    """
    raw = require_env(name, env_file=env_file, docs_url=docs_url)
    return _coerce(
        name,
        raw,
        env_file=env_file,
        expected="a boolean (true/false)",
        parser=lambda value: _BOOL_VALUES[value.strip().lower()],
        docs_url=docs_url,
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
    """Return a required sanitized integer environment variable with bounds.

    Inputs: `name` (str) name, `env_file` (str) environment file path, `sanitizer`
    (Callable[[str], str]), `min_value` (int), `max_value` (int), `docs_url` (str |
    None). Output: `int`. Raises: ValueError when validation or external operations
    fail.
    """
    raw = require_env(name, env_file=env_file, docs_url=docs_url)
    sanitized = sanitizer(raw)
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
    value = _coerce(
        name,
        sanitized,
        env_file=env_file,
        expected="an integer",
        parser=int,
        docs_url=docs_url,
    )
    return max(min_value, min(max_value, value))
