#!/usr/bin/env python3
"""Push to GitHub over HTTPS using a one-shot, no-echo PAT prompt."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
TokenReader = Callable[[str], str]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for `tools.git_push_with_pat`.

    Inputs: `argv` (Sequence[str] | None) command-line arguments. Output:
    `argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run git push with a socket-backed askpass helper so GitHub PATs "
            "never appear in argv, remotes, logs, temp files, or long-lived "
            "credential stores."
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
    parser.add_argument(
        "--force-with-lease",
        metavar="REF:SHA",
        help=(
            "Pass a single explicit --force-with-lease=<ref>:<sha> guard to "
            "git push. The value must contain a fully qualified ref and the "
            "expected remote object ID."
        ),
    )
    return parser.parse_args(argv)


def _validate_git_argument(name: str, value: str) -> None:
    """Validate the git argument.

    Inputs: `name` (str) name, `value` (str) input value. Output: None. Raises:
    SystemExit when validation or the called operation fails.
    """
    if not value or value.startswith("-") or "\x00" in value:
        raise SystemExit(f"{name} must be a non-option Git argument")
    if any(ord(character) < 32 for character in value):
        raise SystemExit(f"{name} must not contain control characters")


def _is_direct_remote_url(remote: str) -> bool:
    """Return whether a remote argument is a URL rather than a configured name.

    Inputs: `remote` (str). Output: `bool`.
    """
    return "://" in remote or remote.startswith("git@") or remote.startswith("ssh://")


def _resolve_remote_url(
    git_bin: str,
    remote: str,
    *,
    env: Mapping[str, str],
    runner: RunCommand,
) -> str:
    """Resolve a remote name or URL to its configured push URL.

    Inputs: `git_bin` (str), `remote` (str), `env`, `runner`. Output: remote URL.
    Raises: SystemExit when the configured remote cannot be resolved.
    """
    if _is_direct_remote_url(remote):
        return remote

    for args in (
        [git_bin, "remote", "get-url", "--push", remote],
        [git_bin, "remote", "get-url", remote],
    ):
        result = runner(
            args,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            remote_url = (result.stdout or "").strip().splitlines()
            if remote_url:
                return remote_url[0].strip()

    raise SystemExit(f"Could not resolve Git remote URL for {remote!r}")


def _validate_github_https_remote(remote_url: str) -> None:
    """Validate that a PAT-backed push targets GitHub over HTTPS.

    Inputs: `remote_url` (str). Output: None. Raises: SystemExit on unsafe remotes.
    """
    parsed = urlparse(remote_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise SystemExit(
            "PAT-backed pushes are allowed only to https://github.com remotes"
        )
    if parsed.password:
        raise SystemExit("GitHub remote URL must not embed credentials")


def _validate_force_with_lease(value: str | None) -> str | None:
    """Validate the force with lease.

    Inputs: `value` (str | None) input value. Output: `str | None`. Raises: SystemExit
    when validation or the called operation fails.
    """
    if value is None:
        return None
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise SystemExit("force-with-lease must not contain control characters")
    ref, separator, expected = value.partition(":")
    if separator != ":" or not ref.startswith("refs/") or not expected:
        raise SystemExit("force-with-lease must be REF:SHA")
    if ref.startswith("-") or expected.startswith("-"):
        raise SystemExit("force-with-lease must not contain option-like values")
    if not all(character in "0123456789abcdefABCDEF" for character in expected):
        raise SystemExit("force-with-lease expected object ID must be hex")
    return f"--force-with-lease={ref}:{expected}"


def _read_token(env: Mapping[str, str], env_name: str, reader: TokenReader) -> str:
    """Read the token.

    Inputs: `env` (Mapping[str, str]) environment mapping, `env_name` (str), `reader`
    (TokenReader). Output: `str`. Raises: SystemExit for the exercised failure path.
    """
    token = env.get(env_name, "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise SystemExit(f"{env_name} is required")
    token = reader("GitHub PAT: ").strip()
    if not token:
        raise SystemExit(f"{env_name} is required")
    return token


def _write_askpass(path: Path) -> None:
    """Write the askpass.

    Inputs: `path` (Path) path. Output: None.
    """
    executable = sys.executable or "/usr/bin/env python3"
    path.write_text(
        "\n".join(
            (
                f"#!{executable}",
                "from __future__ import annotations",
                "",
                "import os",
                "import socket",
                "import sys",
                "",
                "prompt = sys.argv[1] if len(sys.argv) > 1 else ''",
                "allowed_host = os.environ.get('GIT_PAT_ALLOWED_HOST', '')",
                "if allowed_host and allowed_host not in prompt:",
                "    raise SystemExit(1)",
                "if 'sername' in prompt:",
                "    username = os.environ.get('GIT_PAT_USERNAME', '')",
                "    if not username:",
                "        raise SystemExit(1)",
                "    print(username)",
                "elif 'assword' in prompt:",
                "    socket_path = os.environ.get('GIT_PAT_SOCKET', '')",
                "    if not socket_path:",
                "        raise SystemExit(1)",
                "    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:",
                "        client.connect(socket_path)",
                "        chunks = []",
                "        while True:",
                "            chunk = client.recv(4096)",
                "            if not chunk:",
                "                break",
                "            chunks.append(chunk)",
                "    if not chunks:",
                "        raise SystemExit(1)",
                "    sys.stdout.buffer.write(b''.join(chunks))",
                "else:",
                "    raise SystemExit(1)",
                "",
            )
        ),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _serve_credential_once(
    socket_path: Path,
    credential: str,
) -> tuple[threading.Event, threading.Thread]:
    """Return the serve credential once.

    Inputs: `socket_path` (Path), `credential` (str). Output: `tuple[threading.Event,
    threading.Thread]`.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    socket_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    server.listen(1)
    server.settimeout(0.2)

    stop = threading.Event()
    payload = f"{credential}\n".encode("utf-8")

    def serve() -> None:
        """Serve the temporary Git credential helper until the push completes.

        Inputs: no caller arguments. Output: performs the documented action and returns None.
        """
        try:
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.sendall(payload)
                return
        finally:
            server.close()

    thread = threading.Thread(
        target=serve,
        name="git-pat-askpass",
        daemon=True,
    )
    thread.start()
    return stop, thread


def run_push(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None = None,
    token_reader: TokenReader = getpass.getpass,
    runner: RunCommand = subprocess.run,
) -> int:
    """Push a refspec with a PAT-backed HTTPS remote.

    Inputs: `args` (argparse.Namespace) positional arguments, `env` (Mapping[str, str] |
    None) environment mapping, `token_reader` (TokenReader), `runner` (RunCommand).
    Output: `int`. Raises: SystemExit when validation or the called operation fails.
    """
    _validate_git_argument("remote", args.remote)
    _validate_git_argument("refspec", args.refspec)
    _validate_git_argument("username", args.username)
    force_with_lease = _validate_force_with_lease(args.force_with_lease)

    base_env = dict(os.environ if env is None else env)
    git_bin = shutil.which("git")
    if git_bin is None:
        raise SystemExit("git is required")
    remote_url = _resolve_remote_url(
        git_bin,
        args.remote,
        env=base_env,
        runner=runner,
    )
    _validate_github_https_remote(remote_url)
    token = _read_token(base_env, args.token_env, token_reader)

    temp_root = Path(tempfile.mkdtemp(prefix="git-pat-askpass-"))
    temp_root.chmod(stat.S_IRWXU)
    askpass_path = temp_root / "askpass.py"
    socket_path = temp_root / "credential.sock"
    stop_server: threading.Event | None = None
    server_thread: threading.Thread | None = None
    try:
        _write_askpass(askpass_path)
        stop_server, server_thread = _serve_credential_once(socket_path, token)
        push_env = base_env.copy()
        push_env.update(
            {
                "GIT_ASKPASS": str(askpass_path),
                "GIT_PAT_ALLOWED_HOST": "github.com",
                "GIT_PAT_SOCKET": str(socket_path),
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
        if force_with_lease is not None:
            command.append(force_with_lease)
        command.extend([args.remote, args.refspec])
        result = runner(command, env=push_env, check=False)
        return result.returncode
    finally:
        if stop_server is not None:
            stop_server.set()
        if server_thread is not None:
            server_thread.join(timeout=2)
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `tools.git_push_with_pat` command entrypoint.

    Inputs: `argv`. Output: `int`.
    """
    return run_push(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
