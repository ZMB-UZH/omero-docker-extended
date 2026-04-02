#!/usr/bin/env python3
"""Atheris fuzz target for the filename parser separator handling."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import atheris

REPO_ROOT = Path(__file__).resolve().parents[1]
PARSER_MODULE_PATH = (
    REPO_ROOT / "omeroweb_omp_plugin" / "services" / "parsing" / "filename_parser.py"
)

_spec = importlib.util.spec_from_file_location(
    "fuzz_filename_parser_target", PARSER_MODULE_PATH
)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Could not load parser module from {PARSER_MODULE_PATH}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
parse_filename = _module.parse_filename


def _consume_text(data: atheris.FuzzedDataProvider, max_length: int) -> str:
    return data.ConsumeUnicodeNoSurrogates(
        min(max_length, data.ConsumeIntInRange(0, max_length))
    )


def TestOneInput(data: bytes) -> None:
    provider = atheris.FuzzedDataProvider(data)
    filename = _consume_text(provider, 256)
    separator_pattern = _consume_text(provider, 32)
    try:
        parse_filename(filename, separator_pattern)
    except ValueError:
        # Invalid separator patterns are part of the parser contract.
        return


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
