#!/usr/bin/env python3
"""Allow trusted IMS export configuration through OMERO Processor scripts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

ENV_NAMES = (
    "OMERO_IMS_EXPORT_DIR",
    "CONFIG_omero_managed_dir",
)
_ANCHOR = '            "OMERO_TMPDIR",\n'


def patch_processor_env(processor_path: Path) -> bool:
    """Patch the OMERO Processor environment allowlist.

    Inputs: `processor_path` path to `omero/processor.py`. Output: True when the
    file changed, False when already patched. Raises: RuntimeError when the
    expected OMERO Processor allowlist shape is not present.
    """
    text = processor_path.read_text(encoding="utf-8")
    missing_entries = [
        f'            "{env_name}",\n'
        for env_name in ENV_NAMES
        if f'            "{env_name}",\n' not in text
    ]
    if not missing_entries:
        return False
    if _ANCHOR not in text:
        raise RuntimeError(
            "Could not locate OMERO Processor environment allowlist in "
            f"{processor_path}."
        )
    processor_path.write_text(
        text.replace(_ANCHOR, _ANCHOR + "".join(missing_entries), 1),
        encoding="utf-8",
    )
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Patch `omero/processor.py` from a Docker build step.

    Inputs: optional `argv` command arguments. Output: process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("processor_path", type=Path)
    args = parser.parse_args(argv)

    changed = patch_processor_env(args.processor_path)
    status = "patched" if changed else "already patched"
    print(f"OMERO Processor IMS export environment allowlist {status}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
