"""Hardened helpers for running fixed argv command lines without a shell."""

from __future__ import annotations

import logging
import os
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
        self.cmd = tuple(cmd)
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Command timed out after {timeout} seconds.")


def _normalize_command(args: Sequence[CommandArg]) -> tuple[str, ...]:
    """Handle normalize command."""
    if isinstance(args, (str, bytes, os.PathLike)):
        raise TypeError("Command arguments must be a sequence, not a single path.")
    normalized = tuple(os.fsdecode(os.fspath(part)) for part in args)
    if not normalized or not normalized[0]:
        raise ValueError("Command must include a non-empty executable path.")
    if any("\x00" in part for part in normalized):
        raise ValueError("Command arguments must not contain NUL bytes.")
    return normalized


def _normalize_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    """Handle normalize env."""
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
    """Handle normalize cwd."""
    if cwd is None:
        return None
    normalized = os.fsdecode(os.fspath(cwd))
    if "\x00" in normalized:
        raise ValueError("Working directory must not contain NUL bytes.")
    return normalized


def _finite_seconds(value: float | int, label: str) -> float:
    """Handle finite seconds."""
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number of seconds.") from exc
    if not isfinite(seconds):
        raise ValueError(f"{label} must be a finite number of seconds.")
    return seconds


def _normalize_timeout(timeout: float | int | None) -> float | None:
    """Handle normalize timeout."""
    if timeout is None:
        return None
    seconds = _finite_seconds(timeout, "timeout")
    if seconds < 0:
        raise ValueError("timeout must be greater than or equal to zero.")
    return seconds


def _normalize_tick_interval(tick_interval: float | int) -> float:
    """Handle normalize tick interval."""
    seconds = _finite_seconds(tick_interval, "tick_interval")
    if seconds <= 0:
        raise ValueError("tick_interval must be greater than zero.")
    return seconds


def _decode_output(payload: bytes | None) -> str:
    """Handle decode output."""
    return "" if not payload else payload.decode("utf-8", errors="replace")


def _completed(
    command: tuple[str, ...],
    returncode: int | None,
    stdout: bytes | None,
    stderr: bytes | None,
    *,
    check: bool,
) -> CompletedProcess:
    """Handle completed."""
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
) -> subprocess.Popen[bytes]:
    """Handle popen."""
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
    )


def _terminate(process: subprocess.Popen[bytes]) -> tuple[bytes | None, bytes | None]:
    """Handle terminate."""
    if process.poll() is None:
        try:
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
    """Handle notify tick."""
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
) -> CompletedProcess:
    """Run a fixed argv command with captured text output and no shell."""
    command = _normalize_command(args)
    timeout_seconds = _normalize_timeout(timeout)
    process = _popen(command, env=_normalize_env(env), cwd=_normalize_cwd(cwd))
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
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
    check: bool = False,
    tick_interval: float = 0.5,
    on_tick: TickCallback | None = None,
) -> CompletedProcess:
    """Run a fixed argv command while polling state and capturing output."""
    command = _normalize_command(args)
    timeout_seconds = _normalize_timeout(timeout)
    tick_interval = _normalize_tick_interval(tick_interval)

    process = _popen(command, env=_normalize_env(env), cwd=_normalize_cwd(cwd))
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
