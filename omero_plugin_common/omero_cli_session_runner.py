"""Run OMERO CLI commands with a session key supplied on stdin."""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse wrapper arguments before the OMERO CLI subcommand.

    Inputs: wrapper argv. Output: parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description="Run an OMERO CLI command without exposing -k in process argv.",
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    if parsed.command and parsed.command[0] == "--":
        parsed.command = parsed.command[1:]
    if not parsed.command:
        parser.error("missing OMERO CLI command")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Run the OMERO CLI using a session key read from standard input.

    Inputs: optional argv override. Output: process-style return code.
    """
    parsed = _parse_args(list(sys.argv[1:] if argv is None else argv))
    session_key = sys.stdin.readline().rstrip("\r\n")
    if not session_key:
        print("ERROR: OMERO session key was not provided on stdin.", file=sys.stderr)
        return 2

    from omero.cli import CLI

    cli = CLI()
    cli_args = [
        "-k",
        session_key,
        "-s",
        parsed.host,
        "-p",
        str(parsed.port),
        *parsed.command,
    ]
    try:
        cli.invoke(cli_args)
    except SystemExit as exc:
        try:
            return int(exc.code or 0)
        except (TypeError, ValueError):
            return 1
    try:
        return int(getattr(cli, "rv", 0) or 0)
    except (TypeError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
