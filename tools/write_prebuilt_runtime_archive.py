#!/usr/bin/env python3
"""Write a compressed Docker save archive while recording raw byte count."""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path
from typing import BinaryIO, Sequence


def write_archive(
    *,
    input_stream: BinaryIO,
    archive_path: Path,
    raw_bytes_path: Path,
) -> int:
    """Stream stdin to a deterministic gzip archive and return raw byte count.

    Inputs: binary stream and two output paths. Output: compressed archive,
    raw-byte-count file, and the raw byte count.
    """
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes_path.parent.mkdir(parents=True, exist_ok=True)
    archive_tmp = archive_path.with_name(f".{archive_path.name}.tmp")
    raw_bytes_tmp = raw_bytes_path.with_name(f".{raw_bytes_path.name}.tmp")
    raw_bytes = 0

    try:
        with archive_tmp.open("wb") as output:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=output,
                compresslevel=1,
                mtime=0,
            ) as compressed:
                while True:
                    chunk = input_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    raw_bytes += len(chunk)
                    compressed.write(chunk)

        raw_bytes_tmp.write_text(f"{raw_bytes}\n", encoding="utf-8")
        archive_tmp.replace(archive_path)
        raw_bytes_tmp.replace(raw_bytes_path)
        return raw_bytes
    finally:
        archive_tmp.unlink(missing_ok=True)
        raw_bytes_tmp.unlink(missing_ok=True)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments for the archive writer.

    Inputs: CLI argument sequence. Output: parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--raw-bytes-file", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the archive writer CLI.

    Inputs: optional CLI argument sequence and standard input. Output: status code.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    write_archive(
        input_stream=sys.stdin.buffer,
        archive_path=args.archive,
        raw_bytes_path=args.raw_bytes_file,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
