#!/usr/bin/env python3
"""Patch OMERO.web to keep top-logo context keys defined when unset."""

from __future__ import annotations

import sys
from pathlib import Path


OLD_BLOCK = """        if settings.TOP_LOGO:\n            context[\"ome\"][\"logo_src\"] = settings.TOP_LOGO\n        if settings.TOP_LOGO_LINK:\n            context[\"ome\"][\"logo_href\"] = settings.TOP_LOGO_LINK\n"""

NEW_BLOCK = """        context[\"ome\"].setdefault(\"logo_src\", \"\")\n        context[\"ome\"].setdefault(\"logo_href\", \"\")\n        if settings.TOP_LOGO:\n            context[\"ome\"][\"logo_src\"] = settings.TOP_LOGO\n        if settings.TOP_LOGO_LINK:\n            context[\"ome\"][\"logo_href\"] = settings.TOP_LOGO_LINK\n"""


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_omeroweb_logo_context.py <decorators.py>")

    target_path = Path(sys.argv[1])
    original_text = target_path.read_text(encoding="utf-8")

    if NEW_BLOCK in original_text:
        return 0

    if OLD_BLOCK not in original_text:
        raise SystemExit(f"expected OMERO.web logo block not found in {target_path}")

    target_path.write_text(original_text.replace(OLD_BLOCK, NEW_BLOCK), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
