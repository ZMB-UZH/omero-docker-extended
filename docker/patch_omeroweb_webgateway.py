#!/usr/bin/env python3
"""Correct JSON value types and orphan-image lookup in OMERO.web 5.33.1."""

from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


# Exact upstream v5.33.1 file and the reviewed response/lookup corrections.
# A future base-image update must review or remove this compatibility correction.
# Public content hashes, not credentials; provenance: docs/operations/code-scanning.md.
SOURCE_SHA256 = "834e059f3b8b9892e899cbf5e8ee57232903010cf7e99f3fc880a72698a8adb9"  # DevSkim: ignore DS173237 -- public upstream file SHA-256
PATCHED_SHA256 = "423f500164d2ff2466d7db76e7718592573db4bb7905600a65ca79127ef2ea87"  # DevSkim: ignore DS173237 -- corrected file SHA-256
REPLACEMENTS = {
    "save_image_rdef_json": (
        ('json_data = "false"', "json_data = False"),
        ('json_data = "true"', "json_data = True"),
    ),
    "list_compatible_imgs_json": (
        ('json_data = "false"', "json_data = False"),
        (
            "        for ds in img.getProject().listChildren():",
            "        project = img.getProject()\n"
            "        if project is None:\n"
            "            return []\n"
            "        for ds in project.listChildren():",
        ),
        (
            "json_data = json.dumps([x.getId() for x in imgs])",
            "json_data = [x.getId() for x in imgs]",
        ),
    ),
}


def patch_source(source: bytes) -> bytes:
    """Correct response values and empty lookup without changing decorators.

    Inputs: exact upstream source bytes. Output: verified corrected source bytes.
    Raises: ValueError when either source identity or the correction differs.
    """
    digest = hashlib.sha256(source).hexdigest()
    if digest == PATCHED_SHA256:
        return source
    if digest != SOURCE_SHA256:
        raise ValueError("Unrecognized OMERO.web webgateway source; review the upgrade")

    text = source.decode("utf-8")
    functions = {
        node.name: ast.get_source_segment(text, node)
        for node in ast.parse(text).body
        if isinstance(node, ast.FunctionDef) and node.name in REPLACEMENTS
    }
    if functions.keys() != REPLACEMENTS.keys():
        raise ValueError("Expected webgateway functions are missing")
    for name, replacements in REPLACEMENTS.items():
        original = functions[name]
        if original is None or text.count(original) != 1:
            raise ValueError("Expected webgateway function is not unique")
        corrected = original
        for before, after in replacements:
            if corrected.count(before) != 1:
                raise ValueError("Expected webgateway assignment is not unique")
            corrected = corrected.replace(before, after, 1)
        text = text.replace(original, corrected, 1)

    result = text.encode("utf-8")
    if hashlib.sha256(result).hexdigest() != PATCHED_SHA256:
        raise ValueError(
            "Corrected webgateway source does not match the reviewed digest"
        )
    return result


def main() -> int:
    """Apply the build-time correction to one regular source file.

    Inputs: CLI source path. Output: zero after a verified correction.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    target = parser.parse_args().source
    if target.is_symlink() or not target.is_file():
        raise ValueError("Webgateway source must be a regular file, not a symlink")
    original = target.read_bytes()
    corrected = patch_source(original)
    if corrected != original:
        target.write_bytes(corrected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
