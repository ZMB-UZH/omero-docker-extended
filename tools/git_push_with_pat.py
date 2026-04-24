#!/usr/bin/env python3
"""Push to GitHub over HTTPS using a one-shot, no-echo PAT prompt."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
TokenReader = Callable[[str], str]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run git push with a temporary askpass helper so GitHub PATs never "
            "appear in argv, remotes, logs, or long-lived credential stores."
        )
    )
    parser.add_argument("remote", help="Git remote name or URL.")
    parser.add_argument("refspec", help="Branch or refspec to push.")
    parser.add_argument(
        "--username",
        default="x-access-token",
        help="Username supplied to GitHub's HTTPS password prompt.",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Read the PAT from this environment variable before prompting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate authentication flow without updating the remote.",
    )
    return parser.parse_args(argv)


def _validate_git_argument(name: str, value: str) -> None:
    if not value or value.startswith("-") or "\x00" in value:
        raise SystemExit(f"{name} must be a non-option Git argument")
    if any(ord(character) < 32 for character in value):
        raise SystemExit(f"{name} must not contain control characters")


def _read_token(env: Mapping[str, str], env_name: str, reader: TokenReader) -> str:
    token = env.get(env_name, "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise SystemExit(f"{env_name} is required")
    token = reader("GitHub PAT: ").strip()
    if not token:
        raise SystemExit(f"{env_name} is required")
    return token


def _write_secret_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_askpass(path: Path) -> None:
    path.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                'case "$1" in',
                "  *sername*) printf '%s\\n' \"${GIT_PAT_USERNAME:?}\" ;;",
                '  *assword*) cat "${GIT_PAT_FILE:?}" ;;',
                "  *) exit 1 ;;",
                "esac",
                "",
            )
        ),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def run_push(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None = None,
    token_reader: TokenReader = getpass.getpass,
    runner: RunCommand = subprocess.run,
) -> int:
    _validate_git_argument("remote", args.remote)
    _validate_git_argument("refspec", args.refspec)
    _validate_git_argument("username", args.username)

    base_env = dict(os.environ if env is None else env)
    token = _read_token(base_env, args.token_env, token_reader)
    git_bin = shutil.which("git")
    if git_bin is None:
        raise SystemExit("git is required")

    temp_root = Path(tempfile.mkdtemp(prefix="git-pat-askpass-"))
    temp_root.chmod(stat.S_IRWXU)
    askpass_path = temp_root / "askpass.sh"
    token_path = temp_root / "token"
    try:
        _write_secret_file(token_path, token)
        _write_askpass(askpass_path)
        push_env = base_env.copy()
        push_env.update(
            {
                "GIT_ASKPASS": str(askpass_path),
                "GIT_PAT_FILE": str(token_path),
                "GIT_PAT_USERNAME": args.username,
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        command = [
            git_bin,
            "-c",
            "credential.helper=",
            "-c",
            "credential.https://github.com.helper=",
            "push",
        ]
        if args.dry_run:
            command.append("--dry-run")
        command.extend([args.remote, args.refspec])
        result = runner(command, env=push_env, check=False)
        return result.returncode
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    return run_push(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
