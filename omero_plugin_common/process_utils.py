"""Hardened helpers for running fixed argv command lines without a shell."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from math import isfinite
from typing import Callable, Mapping, Sequence


CommandArg = str | os.PathLike[str]
TickCallback = Callable[[int, float], None]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompletedProcess:
    """Minimal completed-process result for shell-free command execution."""

    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CalledProcessError(RuntimeError):
    """Raised when a checked command exits non-zero."""

    def __init__(
        self,
        returncode: int,
        cmd: Sequence[str],
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Create `CalledProcessError` with `returncode` and `cmd`.

        Inputs: `returncode`, `cmd`, `stdout`, `stderr`. Output: None.
        """
        self.returncode = int(returncode)
        self.cmd = tuple(cmd)
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Command returned non-zero exit status {self.returncode}.")


class TimeoutExpired(TimeoutError):
    """Raised when a command exceeds its configured timeout."""

    def __init__(
        self,
        cmd: Sequence[str],
        timeout: float | int,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Create `TimeoutExpired` with `cmd` and `timeout`.

        Inputs: `cmd`, `timeout`, `stdout`, `stderr`. Output: None.
        """
        self.cmd = tuple(cmd)
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Command timed out after {timeout} seconds.")


def _normalize_command(args: Sequence[CommandArg]) -> tuple[str, ...]:
    """Normalize the command.

    Inputs: `args` (Sequence[CommandArg]) positional arguments. Output: `tuple[str,
    ...]`. Raises: TypeError, ValueError when validation or the called operation fails.
    """
    if isinstance(args, (str, bytes, os.PathLike)):
        raise TypeError("Command arguments must be a sequence, not a single path.")
    normalized = tuple(os.fsdecode(os.fspath(part)) for part in args)
    if not normalized or not normalized[0]:
        raise ValueError("Command must include a non-empty executable path.")
    if any("\x00" in part for part in normalized):
        raise ValueError("Command arguments must not contain NUL bytes.")
    return normalized


def _normalize_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    """Normalize the environment.

    Inputs: `env` (Mapping[str, str] | None) environment mapping. Output: `dict[str,
    str] | None`. Raises: ValueError when validation or the called operation fails.
    """
    if env is None:
        return None
    normalized = {
        os.fsdecode(os.fspath(key)): os.fsdecode(os.fspath(value))
        for key, value in env.items()
    }
    if any("\x00" in key or "\x00" in value for key, value in normalized.items()):
        raise ValueError("Environment variables must not contain NUL bytes.")
    return normalized


def _normalize_cwd(cwd: CommandArg | None) -> str | None:
    """Normalize the cwd.

    Inputs: `cwd` (CommandArg | None) working directory. Output: `str | None`. Raises:
    ValueError when validation or the called operation fails.
    """
    if cwd is None:
        return None
    normalized = os.fsdecode(os.fspath(cwd))
    if "\x00" in normalized:
        raise ValueError("Working directory must not contain NUL bytes.")
    return normalized


def _normalize_stdin_text(stdin_text: str | bytes | None) -> bytes | None:
    """Normalize optional subprocess stdin payload.

    Inputs: optional text or bytes. Output: bytes or None.
    """
    if stdin_text is None:
        return None
    if isinstance(stdin_text, bytes):
        payload = stdin_text
    else:
        payload = str(stdin_text).encode("utf-8")
    if b"\x00" in payload:
        raise ValueError("Standard input payload must not contain NUL bytes.")
    return payload


def _finite_seconds(value: float | int, label: str) -> float:
    """Return the finite seconds.

    Inputs: `value` (float | int) input value, `label` (str). Output: `float`. Raises:
    ValueError when validation or the called operation fails.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number of seconds.") from exc
    if not isfinite(seconds):
        raise ValueError(f"{label} must be a finite number of seconds.")
    return seconds


def _normalize_timeout(timeout: float | int | None) -> float | None:
    """Normalize the timeout.

    Inputs: `timeout` (float | int | None) timeout seconds. Output: `float | None`.
    Raises: ValueError when validation or the called operation fails.
    """
    if timeout is None:
        return None
    seconds = _finite_seconds(timeout, "timeout")
    if seconds < 0:
        raise ValueError("timeout must be greater than or equal to zero.")
    return seconds


def _normalize_tick_interval(tick_interval: float | int) -> float:
    """Normalize the tick interval.

    Inputs: `tick_interval` (float | int). Output: `float`. Raises: ValueError when validation
    or the called operation fails.
    """
    seconds = _finite_seconds(tick_interval, "tick_interval")
    if seconds <= 0:
        raise ValueError("tick_interval must be greater than zero.")
    return seconds


def _decode_output(payload: bytes | None) -> str:
    """Decode the output.

    Inputs: `payload` (bytes | None) payload. Output: `str`.
    """
    return "" if not payload else payload.decode("utf-8", errors="replace")


def _completed(
    command: tuple[str, ...],
    returncode: int | None,
    stdout: bytes | None,
    stderr: bytes | None,
    *,
    check: bool,
) -> CompletedProcess:
    """Return the completed.

    Inputs: `command` (tuple[str, ...]), `returncode` (int | None), `stdout` (bytes |
    None), `stderr` (bytes | None), `check` (bool). Output: `CompletedProcess`. Raises:
    CalledProcessError when validation or the called operation fails.
    """
    completed = CompletedProcess(
        args=command,
        returncode=int(returncode or 0),
        stdout=_decode_output(stdout),
        stderr=_decode_output(stderr),
    )
    if check and completed.returncode != 0:
        raise CalledProcessError(
            completed.returncode,
            completed.args,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def _popen(
    command: tuple[str, ...],
    *,
    env: dict[str, str] | None,
    cwd: str | None,
    stdin_pipe: bool = False,
    start_new_session: bool = False,
) -> subprocess.Popen[bytes]:
    """Return the popen.

    Inputs: `command` (tuple[str, ...]), `env` (dict[str, str] | None) environment
    mapping, `cwd` (str | None) working directory. Output: `subprocess.Popen[bytes]`.
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        start_new_session=start_new_session,
    )
    setattr(process, "_process_utils_start_new_session", bool(start_new_session))
    return process


def _terminate(process: subprocess.Popen[bytes]) -> tuple[bytes | None, bytes | None]:
    """Return the terminate.

    Inputs: `process` (subprocess.Popen[bytes]). Output: `tuple[bytes | None, bytes |
    None]`.
    """
    if process.poll() is None:
        try:
            if getattr(process, "_process_utils_start_new_session", False):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            logger.debug(
                "Process exited before it could be killed during subprocess cleanup.",
                exc_info=True,
            )
    return process.communicate()


def _notify_tick(
    process: subprocess.Popen[bytes],
    on_tick: TickCallback | None,
    elapsed: float,
) -> None:
    """Invoke the streaming progress callback for the current process tick.

    Inputs: `process` (subprocess.Popen[bytes]), `on_tick` (TickCallback | None),
    `elapsed` (float). Output: None.
    """
    if on_tick is None:
        return
    try:
        on_tick(process.pid, elapsed)
    except Exception:
        _terminate(process)
        raise


def run(
    args: Sequence[CommandArg],
    *,
    check: bool = False,
    timeout: float | int | None = None,
    env: Mapping[str, str] | None = None,
    cwd: CommandArg | None = None,
    stdin_text: str | bytes | None = None,
    start_new_session: bool = False,
) -> CompletedProcess:
    """A fixed argv command with captured text output and no shell.

    Inputs: `args` (Sequence[CommandArg]) positional arguments, `check` (bool),
    `timeout` (float | int | None) timeout seconds, `env` (Mapping[str, str] | None)
    environment mapping, `cwd` (CommandArg | None) working directory. Output:
    `CompletedProcess`. Raises: TimeoutExpired when validation or external operations
    fail.
    """
    command = _normalize_command(args)
    timeout_seconds = _normalize_timeout(timeout)
    stdin_payload = _normalize_stdin_text(stdin_text)
    process = _popen(
        command,
        env=_normalize_env(env),
        cwd=_normalize_cwd(cwd),
        stdin_pipe=stdin_payload is not None,
        start_new_session=start_new_session,
    )
    try:
        stdout, stderr = process.communicate(
            input=stdin_payload,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout, partial_stderr = _terminate(process)
        raise TimeoutExpired(
            command,
            exc.timeout,
            stdout=_decode_output(partial_stdout),
            stderr=_decode_output(partial_stderr),
        ) from exc
    return _completed(command, process.returncode, stdout, stderr, check=check)


def run_streaming(
    args: Sequence[CommandArg],
    *,
    timeout: float | int | None = None,
    env: Mapping[str, str] | None = None,
    cwd: CommandArg | None = None,
    stdin_text: str | bytes | None = None,
    check: bool = False,
    tick_interval: float = 0.5,
    on_tick: TickCallback | None = None,
    start_new_session: bool = False,
) -> CompletedProcess:
    """A fixed argv command while polling state and capturing output.

    Inputs: `args` (Sequence[CommandArg]) positional arguments, `timeout` (float | int |
    None) timeout seconds, `env` (Mapping[str, str] | None) environment mapping, `cwd`
    (CommandArg | None) working directory, `check` (bool), `tick_interval` (float),
    `on_tick` (TickCallback | None). Output: `CompletedProcess`. Raises: TimeoutExpired
    when validation or the called operation fails.
    """
    command = _normalize_command(args)
    timeout_seconds = _normalize_timeout(timeout)
    tick_interval = _normalize_tick_interval(tick_interval)
    stdin_payload = _normalize_stdin_text(stdin_text)

    process = _popen(
        command,
        env=_normalize_env(env),
        cwd=_normalize_cwd(cwd),
        stdin_pipe=stdin_payload is not None,
        start_new_session=start_new_session,
    )
    if stdin_payload is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_payload)
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.stdin = None
    started_at = time.monotonic()
    _notify_tick(process, on_tick, 0.0)

    while True:
        elapsed = time.monotonic() - started_at
        remaining = None
        if timeout_seconds is not None:
            remaining = timeout_seconds - elapsed
        if timeout_seconds is not None and remaining is not None and remaining <= 0:
            try:
                stdout, stderr = process.communicate(timeout=0)
                break
            except subprocess.TimeoutExpired:
                partial_stdout, partial_stderr = _terminate(process)
                raise TimeoutExpired(
                    command,
                    timeout_seconds,
                    stdout=_decode_output(partial_stdout),
                    stderr=_decode_output(partial_stderr),
                ) from None
        if elapsed > 0:
            _notify_tick(process, on_tick, elapsed)
        wait_seconds = (
            tick_interval if remaining is None else min(tick_interval, remaining)
        )
        try:
            stdout, stderr = process.communicate(timeout=wait_seconds)
            break
        except subprocess.TimeoutExpired:
            continue
    return _completed(command, process.returncode, stdout, stderr, check=check)
