from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from omero_plugin_common import process_utils


def test_run_captures_output_env_and_cwd(tmp_path: Path) -> None:
    """Verify run captures output environment and cwd.

    Inputs: `tmp_path`. Output: None.
    """
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
    """Verify run raises called process error with captured output.

    Inputs: none. Output: None.
    """
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
    assert excinfo.value.cmd[0] == sys.executable
    assert excinfo.value.stdout == "before-fail\n"
    assert excinfo.value.stderr == "boom\n"


def test_run_raises_timeout_with_partial_output() -> None:
    """Verify run raises timeout with partial output.

    Inputs: none. Output: None.
    """
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
    assert excinfo.value.cmd[0] == sys.executable
    assert "started" in excinfo.value.stdout


def test_process_errors_do_not_render_command_values() -> None:
    """Verify process errors do not render command values.

    Inputs: none. Output: None.
    """
    failure = process_utils.CalledProcessError(2, ["tool", "--token", "secret"])
    timeout = process_utils.TimeoutExpired(["tool", "--token", "secret"], 5)

    assert failure.cmd == ("tool", "--token", "secret")
    assert timeout.cmd == ("tool", "--token", "secret")
    assert "secret" not in str(failure)
    assert "secret" not in str(timeout)


def test_run_streaming_collects_output_and_invokes_tick_callback() -> None:
    """Verify run streaming collects output and invokes tick callback.

    Inputs: none. Output: None.
    """
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


def test_run_streaming_rejects_non_positive_tick_interval() -> None:
    """Verify run streaming rejects non positive tick interval.

    Inputs: none. Output: None.
    """
    with pytest.raises(ValueError, match="tick_interval"):
        process_utils.run_streaming(
            [sys.executable, "-c", "print('never-started')"],
            tick_interval=0,
        )


def test_run_rejects_invalid_timeout_before_spawning(monkeypatch) -> None:
    """Verify run rejects invalid timeout before spawning.

    Inputs: `monkeypatch`. Output: None. Raises on invalid or unavailable state.
    """

    def fail_popen(*_args, **_kwargs):
        """Fail popen.

        Inputs: `*_args`, `**_kwargs`. Output: None. Raises on invalid or unavailable
        state.

        state.
        """
        raise AssertionError("invalid timeout must not spawn a process")

    monkeypatch.setattr(process_utils, "_popen", fail_popen)

    with pytest.raises(ValueError, match="timeout"):
        process_utils.run(
            [sys.executable, "-c", "print('never-started')"],
            timeout="invalid",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="greater than or equal"):
        process_utils.run(
            [sys.executable, "-c", "print('never-started')"],
            timeout=-1,
        )


def test_run_streaming_rejects_invalid_timing_before_spawning(monkeypatch) -> None:
    """Verify run streaming rejects invalid timing before spawning.

    Inputs: `monkeypatch`. Output: None. Raises on invalid or unavailable state.
    """

    def fail_popen(*_args, **_kwargs):
        """Fail popen.

        Inputs: `*_args`, `**_kwargs`. Output: None. Raises on invalid or unavailable
        state.

        state.
        """
        raise AssertionError("invalid timing must not spawn a process")

    monkeypatch.setattr(process_utils, "_popen", fail_popen)

    with pytest.raises(ValueError, match="timeout"):
        process_utils.run_streaming(
            [sys.executable, "-c", "print('never-started')"],
            timeout=float("nan"),
        )

    with pytest.raises(ValueError, match="tick_interval"):
        process_utils.run_streaming(
            [sys.executable, "-c", "print('never-started')"],
            tick_interval=float("nan"),
        )


def test_run_streaming_terminates_process_when_tick_callback_fails(monkeypatch) -> None:
    """Verify run streaming terminates process when tick callback fails.

    Inputs: `monkeypatch`. Output: None. Raises on invalid or unavailable state.
    """

    class TickFailProcess:
        """Represent tick fail process."""

        pid = 1234
        returncode = None

        def __init__(self) -> None:
            """Initialize the instance.

            Inputs: none. Output: None.
            """
            self.killed = False

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: none. Output: None.
            """
            return None

        def kill(self):
            """Terminate the process.

            Inputs: none. Output: None.
            """
            self.killed = True
            self.returncode = -9

        @staticmethod
        def communicate(timeout=None):
            """Return process output.

            Inputs: `timeout`. Output: tuple.
            """
            _ = timeout
            return b"", b""

    process = TickFailProcess()
    tick_count = 0
    monotonic_values = iter((100.0, 100.1))

    def fake_popen(*_args, **_kwargs):
        """Fake popen.

        Inputs: `*_args`, `**_kwargs`. Output: `process`.
        """
        return process

    def fail_on_second_tick(_pid: int, _elapsed: float) -> None:
        """Fail on second tick.

        Inputs: `_pid`, `_elapsed`. Output: None. Raises on invalid or unavailable
        state.

        state.
        """
        nonlocal tick_count
        tick_count += 1
        if tick_count > 1:
            raise RuntimeError("tick failed")

    def fake_monotonic() -> float:
        """Fake monotonic.

        Inputs: none. Output: `float`.
        """
        try:
            return next(monotonic_values)
        except StopIteration:
            return 100.1

    monkeypatch.setattr(process_utils, "_popen", fake_popen)
    monkeypatch.setattr(process_utils.time, "monotonic", fake_monotonic)

    with pytest.raises(RuntimeError, match="tick failed"):
        process_utils.run_streaming(
            [sys.executable, "-c", "print('unused')"],
            tick_interval=0.01,
            on_tick=fail_on_second_tick,
        )

    assert process.killed is True


def test_run_rejects_invalid_command_arguments() -> None:
    """Verify run rejects invalid command arguments.

    Inputs: none. Output: None.
    """
    with pytest.raises(ValueError, match="non-empty executable"):
        process_utils.run([])

    with pytest.raises(ValueError, match="NUL bytes"):
        process_utils.run(["echo", "bad\0arg"])

    with pytest.raises(TypeError, match="sequence"):
        process_utils.run(Path(sys.executable))


def test_run_rejects_invalid_environment_and_workdir_inputs() -> None:
    """Verify run rejects invalid environment and workdir inputs.

    Inputs: none. Output: None.
    """
    with pytest.raises(
        ValueError, match="Environment variables must not contain NUL bytes"
    ):
        process_utils.run([sys.executable, "-c", "pass"], env={"BAD\0KEY": "value"})

    with pytest.raises(
        ValueError, match="Working directory must not contain NUL bytes"
    ):
        process_utils.run([sys.executable, "-c", "pass"], cwd="bad\0cwd")


def test_internal_output_helpers_cover_empty_stream_inputs() -> None:
    """Verify internal output helpers cover empty stream inputs.

    Inputs: none. Output: None.
    """
    assert process_utils._decode_output(None) == ""
    assert process_utils._decode_output(b"invalid-\xff") == "invalid-\ufffd"


def test_terminate_handles_process_exit_race() -> None:
    """Verify terminate handles process exit race.

    Inputs: none. Output: None. Raises on invalid or unavailable state.
    """

    class RacingProcess:
        """Represent racing process."""

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: none. Output: None.
            """
            return None

        @staticmethod
        def kill():
            """Terminate the process.

            Inputs: none. Output: None. Raises on invalid or unavailable state.
            """
            raise ProcessLookupError

        @staticmethod
        def communicate():
            """Return process output.

            Inputs: none. Output: tuple.
            """
            return b"out", b"err"

    assert process_utils._terminate(RacingProcess()) == (b"out", b"err")  # type: ignore[arg-type]


def test_run_streaming_timeout_preserves_partial_output() -> None:
    """Verify run streaming timeout preserves partial output.

    Inputs: none. Output: None.
    """
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


def test_run_streaming_collects_process_finished_at_timeout_boundary(
    monkeypatch,
) -> None:
    """Verify run streaming collects process finished at timeout boundary.

    Inputs: `monkeypatch`. Output: None.
    """

    class FinishedProcess:
        """Represent finished process."""

        pid = 12345
        returncode = 0

        @staticmethod
        def communicate(timeout=None):
            """Return process output.

            Inputs: `timeout`. Output: tuple.
            """
            assert timeout == 0
            return b"done\n", b""

    ticks: list[tuple[int, float]] = []
    times = iter([0.0, 1.0])

    monkeypatch.setattr(
        process_utils,
        "_popen",
        lambda _command, *, env, cwd: FinishedProcess(),
    )

    def monotonic() -> float:
        """Monotonic.

        Inputs: none. Output: `float`.
        """
        try:
            return next(times)
        except StopIteration:
            return 1.0

    monkeypatch.setattr(process_utils.time, "monotonic", monotonic)

    result = process_utils.run_streaming(
        [sys.executable, "-c", "print('done')"],
        timeout=1,
        tick_interval=0.5,
        on_tick=lambda pid, elapsed: ticks.append((pid, elapsed)),
    )

    assert result.returncode == 0
    assert result.stdout == "done\n"
    assert ticks == [(12345, 0.0)]


def test_run_streaming_raises_called_process_error_with_output() -> None:
    """Verify run streaming raises called process error with output.

    Inputs: none. Output: None.
    """
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


def test_run_handles_large_unbroken_output() -> None:
    """Verify run handles large unbroken output.

    Inputs: none. Output: None.
    """
    payload_size = 200_000

    result = process_utils.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.stdout.write('x' * {payload_size})",
        ],
        check=True,
    )

    assert result.stdout == "x" * payload_size
    assert result.stderr == ""


def test_run_streaming_handles_large_unbroken_output() -> None:
    """Verify run streaming handles large unbroken output.

    Inputs: none. Output: None.
    """
    payload_size = 200_000

    result = process_utils.run_streaming(
        [
            sys.executable,
            "-c",
            (
                f"import sys; sys.stdout.write('x' * {payload_size}); "
                f"sys.stderr.write('y' * {payload_size})"
            ),
        ],
        check=True,
        tick_interval=0.05,
    )

    assert result.stdout == "x" * payload_size
    assert result.stderr == "y" * payload_size


def test_run_works_inside_running_event_loop() -> None:
    """Verify run works inside running event loop.

    Inputs: none. Output: None.
    """

    async def _exercise() -> None:
        """Exercise.

        Inputs: none. Output: None.
        """
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
    """Verify run inside running event loop propagates command errors.

    Inputs: none. Output: None.
    """

    async def _exercise() -> None:
        """Exercise.

        Inputs: none. Output: None.
        """
        with pytest.raises(process_utils.CalledProcessError) as excinfo:
            process_utils.run(
                [sys.executable, "-c", "import sys; sys.exit(9)"],
                check=True,
            )

        assert excinfo.value.returncode == 9

    asyncio.run(_exercise())
