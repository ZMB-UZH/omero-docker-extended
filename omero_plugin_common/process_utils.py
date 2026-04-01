"""Hardened helpers for running fixed argv command lines without a shell."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


CommandArg = str | os.PathLike[str]
TickCallback = Callable[[int, float], None]


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
        super().__init__(
            f"Command {self.cmd!r} returned non-zero exit status {self.returncode}."
        )


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
        super().__init__(f"Command {self.cmd!r} timed out after {timeout} seconds.")


def _normalize_command(args: Sequence[CommandArg]) -> tuple[str, ...]:
    if isinstance(args, (str, bytes, os.PathLike)):
        raise TypeError("Command arguments must be a sequence, not a single path.")
    normalized = tuple(os.fsdecode(os.fspath(part)) for part in args)
    if not normalized or not normalized[0]:
        raise ValueError("Command must include a non-empty executable path.")
    for part in normalized:
        if "\x00" in part:
            raise ValueError("Command arguments must not contain NUL bytes.")
    return normalized


def _normalize_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    normalized: dict[str, str] = {}
    for key, value in env.items():
        normalized_key = os.fsdecode(os.fspath(key))
        normalized_value = os.fsdecode(os.fspath(value))
        if "\x00" in normalized_key or "\x00" in normalized_value:
            raise ValueError("Environment variables must not contain NUL bytes.")
        normalized[normalized_key] = normalized_value
    return normalized


def _normalize_cwd(cwd: CommandArg | None) -> str | None:
    if cwd is None:
        return None
    normalized = os.fsdecode(os.fspath(cwd))
    if "\x00" in normalized:
        raise ValueError("Working directory must not contain NUL bytes.")
    return normalized


def _decode_output(payload: bytes | None) -> str:
    if not payload:
        return ""
    return payload.decode("utf-8", errors="replace")


async def _run_async(
    command: tuple[str, ...],
    *,
    timeout: float | int | None,
    env: dict[str, str] | None,
    cwd: str | None,
    check: bool,
) -> CompletedProcess:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_task = asyncio.create_task(_consume_stream(process.stdout, stdout_lines))
    stderr_task = asyncio.create_task(_consume_stream(process.stderr, stderr_lines))
    try:
        if timeout is None:
            await process.wait()
        else:
            await asyncio.wait_for(process.wait(), timeout)
    except asyncio.TimeoutError as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task)
        raise TimeoutExpired(
            command,
            timeout,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
        ) from exc
    await asyncio.gather(stdout_task, stderr_task)

    completed = CompletedProcess(
        args=command,
        returncode=int(process.returncode or 0),
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )
    if check and completed.returncode != 0:
        raise CalledProcessError(
            completed.returncode,
            completed.args,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


async def _consume_stream(
    stream: asyncio.StreamReader | None, destination: list[str]
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.readline()
        if not chunk:
            return
        destination.append(_decode_output(chunk))


async def _run_streaming_async(
    command: tuple[str, ...],
    *,
    timeout: float | int | None,
    env: dict[str, str] | None,
    cwd: str | None,
    check: bool,
    tick_interval: float,
    on_tick: TickCallback | None,
) -> CompletedProcess:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_task = asyncio.create_task(_consume_stream(process.stdout, stdout_lines))
    stderr_task = asyncio.create_task(_consume_stream(process.stderr, stderr_lines))
    started_at = time.monotonic()

    if on_tick is not None:
        on_tick(process.pid, 0.0)

    while process.returncode is None:
        elapsed = time.monotonic() - started_at
        if timeout is not None and elapsed > timeout:
            process.kill()
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            raise TimeoutExpired(
                command,
                timeout,
                stdout="".join(stdout_lines),
                stderr="".join(stderr_lines),
            )
        if on_tick is not None and elapsed > 0:
            on_tick(process.pid, elapsed)
        try:
            await asyncio.wait_for(process.wait(), timeout=tick_interval)
        except asyncio.TimeoutError:
            continue

    await asyncio.gather(stdout_task, stderr_task)

    completed = CompletedProcess(
        args=command,
        returncode=int(process.returncode or 0),
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )
    if check and completed.returncode != 0:
        raise CalledProcessError(
            completed.returncode,
            completed.args,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}
    done = threading.Event()

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - mirrored into caller
            error["exc"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    done.wait()
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


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
    return _run_coro_sync(
        _run_async(
            command,
            timeout=timeout,
            env=_normalize_env(env),
            cwd=_normalize_cwd(cwd),
            check=check,
        )
    )


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
    """Run a fixed argv command while streaming stdout/stderr and polling state."""

    command = _normalize_command(args)
    return _run_coro_sync(
        _run_streaming_async(
            command,
            timeout=timeout,
            env=_normalize_env(env),
            cwd=_normalize_cwd(cwd),
            check=check,
            tick_interval=float(tick_interval),
            on_tick=on_tick,
        )
    )
