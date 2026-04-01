from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from omero_plugin_common import process_utils


def test_run_captures_output_env_and_cwd(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = dict(os.environ)
    env["PROCESS_UTILS_TEST_VALUE"] = "from-env"

    result = process_utils.run(
        [
            sys.executable,
            "-c",
            (
                "import os, pathlib; "
                "print(os.environ['PROCESS_UTILS_TEST_VALUE']); "
                "print(pathlib.Path.cwd())"
            ),
        ],
        env=env,
        cwd=workdir,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["from-env", str(workdir)]
    assert result.stderr == ""


def test_run_raises_called_process_error_with_captured_output() -> None:
    with pytest.raises(process_utils.CalledProcessError) as excinfo:
        process_utils.run(
            [
                sys.executable,
                "-c",
                "import sys; print('before-fail'); print('boom', file=sys.stderr); sys.exit(7)",
            ],
            check=True,
        )

    assert excinfo.value.returncode == 7
    assert excinfo.value.stdout == "before-fail\n"
    assert excinfo.value.stderr == "boom\n"


def test_run_raises_timeout_with_partial_output() -> None:
    with pytest.raises(process_utils.TimeoutExpired) as excinfo:
        process_utils.run(
            [
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(5)",
            ],
            timeout=0.2,
        )

    assert excinfo.value.timeout == 0.2
    assert "started" in excinfo.value.stdout


def test_run_streaming_collects_output_and_invokes_tick_callback() -> None:
    ticks: list[tuple[int, float]] = []

    result = process_utils.run_streaming(
        [
            sys.executable,
            "-c",
            (
                "import sys, time; "
                "print('one', flush=True); "
                "time.sleep(0.2); "
                "print('two', flush=True); "
                "time.sleep(0.2); "
                "print('warn', file=sys.stderr, flush=True)"
            ),
        ],
        tick_interval=0.05,
        on_tick=lambda pid, elapsed: ticks.append((pid, elapsed)),
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["one", "two"]
    assert result.stderr == "warn\n"
    assert ticks
    assert all(pid > 0 for pid, _elapsed in ticks)


def test_run_rejects_invalid_command_arguments() -> None:
    with pytest.raises(ValueError, match="non-empty executable"):
        process_utils.run([])

    with pytest.raises(ValueError, match="NUL bytes"):
        process_utils.run(["echo", "bad\0arg"])

    with pytest.raises(TypeError, match="sequence"):
        process_utils.run(Path(sys.executable))


def test_run_rejects_invalid_environment_and_workdir_inputs() -> None:
    with pytest.raises(ValueError, match="Environment variables must not contain NUL bytes"):
        process_utils.run([sys.executable, "-c", "pass"], env={"BAD\0KEY": "value"})

    with pytest.raises(ValueError, match="Working directory must not contain NUL bytes"):
        process_utils.run([sys.executable, "-c", "pass"], cwd="bad\0cwd")


def test_internal_output_helpers_cover_empty_stream_inputs() -> None:
    assert process_utils._decode_output(None) == ""

    destination: list[str] = []
    asyncio.run(process_utils._consume_stream(None, destination))
    assert destination == []


def test_run_streaming_timeout_preserves_partial_output() -> None:
    with pytest.raises(process_utils.TimeoutExpired) as excinfo:
        process_utils.run_streaming(
            [
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(5)",
            ],
            timeout=0.2,
            tick_interval=0.05,
        )

    assert excinfo.value.timeout == 0.2
    assert "started" in excinfo.value.stdout


def test_run_streaming_raises_called_process_error_with_output() -> None:
    with pytest.raises(process_utils.CalledProcessError) as excinfo:
        process_utils.run_streaming(
            [
                sys.executable,
                "-c",
                "import sys; print('before-fail'); print('boom', file=sys.stderr); sys.exit(5)",
            ],
            check=True,
            tick_interval=0.05,
        )

    assert excinfo.value.returncode == 5
    assert excinfo.value.stdout == "before-fail\n"
    assert excinfo.value.stderr == "boom\n"


def test_run_works_inside_running_event_loop() -> None:
    async def _exercise() -> None:
        result = process_utils.run(
            [sys.executable, "-c", "print('loop-ok')"],
        )
        assert result.stdout == "loop-ok\n"

        streaming = process_utils.run_streaming(
            [sys.executable, "-c", "print('stream-ok')"],
            tick_interval=0.05,
        )
        assert streaming.stdout == "stream-ok\n"

    asyncio.run(_exercise())


def test_run_inside_running_event_loop_propagates_command_errors() -> None:
    async def _exercise() -> None:
        with pytest.raises(process_utils.CalledProcessError) as excinfo:
            process_utils.run(
                [sys.executable, "-c", "import sys; sys.exit(9)"],
                check=True,
            )

        assert excinfo.value.returncode == 9

    asyncio.run(_exercise())
