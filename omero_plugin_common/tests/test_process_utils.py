from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from omero_plugin_common import process_utils


def test_run_captures_output_env_and_cwd(tmp_path: Path) -> None:
    """Verify run captures output env and cwd.

    Inputs: pytest provides `tmp_path`. Output: fails on regressions in run captures output env and cwd.
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
    """Confirm run raises called process error with captured output exposes the expected failure.

    Inputs: helper fakes. Output: fails on regressions when run raises called process error with captured output stops reporting the expected error.
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
    """Confirm run raises timeout with partial output exposes the expected failure.

    Inputs: helper fakes. Output: fails on regressions when run raises timeout with partial output stops reporting the expected error.
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
    """Verify the process errors do not render command values execution contract.

    Inputs: helper fakes. Output: fails on regressions in process errors do not render command values integration.
    """
    failure = process_utils.CalledProcessError(2, ["tool", "--token", "secret"])
    timeout = process_utils.TimeoutExpired(["tool", "--token", "secret"], 5)

    assert failure.cmd == ("tool", "--token", "secret")
    assert timeout.cmd == ("tool", "--token", "secret")
    assert "secret" not in str(failure)
    assert "secret" not in str(timeout)


def test_run_streaming_collects_output_and_invokes_tick_callback() -> None:
    """Verify run streaming collects output and invokes tick callback.

    Inputs: helper fakes. Output: fails on regressions in run streaming collects output and invokes tick callback.
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
    """Confirm run streaming rejects non positive tick interval is rejected at the boundary.

    Inputs: helper fakes. Output: fails on regressions in run streaming rejects non positive tick interval.
    """
    with pytest.raises(ValueError, match="tick_interval"):
        process_utils.run_streaming(
            [sys.executable, "-c", "print('never-started')"],
            tick_interval=0,
        )


def test_run_rejects_invalid_timeout_before_spawning(monkeypatch) -> None:
    """Confirm run rejects invalid timeout before spawning is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run rejects invalid timeout before spawning.
    AssertionError when validation or the called operation fails.
    """

    def fail_popen(*_args, **_kwargs):
        """Fail immediately when an unexpected branch invokes this helper.

        Inputs: `*_args`, `**_kwargs`. Output: None. Raises: AssertionError when validation or the called operation fails.
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
    """Confirm run streaming rejects invalid timing before spawning is rejected at the boundary.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run streaming rejects invalid timing before spawning.
    AssertionError when validation or the called operation fails.
    """

    def fail_popen(*_args, **_kwargs):
        """Fail immediately when an unexpected branch invokes this helper.

        Inputs: `*_args`, `**_kwargs`. Output: None. Raises: AssertionError when validation or the called operation fails.
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
    """Confirm run streaming terminates process when tick callback fails exposes the expected failure.

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run streaming terminates process when tick callback fails.
    when validation or the called operation fails.
    """

    class TickFailProcess:
        """Test double for tick fail process behavior in this module."""

        pid = 1234
        returncode = None

        def __init__(self) -> None:
            """Create `TickFailProcess` with its default state.

            Inputs: constructor receives no public arguments. Output: initializes fake state.
            """
            self.killed = False

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        def kill(self):
            """Terminate the process.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
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
        """Simulate popen so the surrounding test controls that dependency.

        Inputs: `*_args`, `**_kwargs`. Output: `process`.
        """
        return process

    def fail_on_second_tick(_pid: int, _elapsed: float) -> None:
        """Fail immediately when an unexpected branch invokes this helper.

        Inputs: `_pid` (int), `_elapsed` (float). Output: None. Raises: RuntimeError
        when validation or the called operation fails.
        """
        nonlocal tick_count
        tick_count += 1
        if tick_count > 1:
            raise RuntimeError("tick failed")

    def fake_monotonic() -> float:
        """Simulate monotonic so the surrounding test controls that dependency.

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
    """Confirm run rejects invalid command arguments is rejected at the boundary.

    Inputs: helper fakes. Output: fails on regressions in run rejects invalid command arguments integration.
    """
    with pytest.raises(ValueError, match="non-empty executable"):
        process_utils.run([])

    with pytest.raises(ValueError, match="NUL bytes"):
        process_utils.run(["echo", "bad\0arg"])

    with pytest.raises(TypeError, match="sequence"):
        process_utils.run(Path(sys.executable))


def test_run_rejects_invalid_environment_and_workdir_inputs() -> None:
    """Confirm run rejects invalid environment and workdir inputs is rejected at the boundary.

    Inputs: helper fakes. Output: fails on regressions in run rejects invalid environment and workdir inputs.
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

    Inputs: helper fakes. Output: fails on regressions in internal output helpers cover empty stream inputs.
    """
    assert process_utils._decode_output(None) == ""
    assert process_utils._decode_output(b"invalid-\xff") == "invalid-\ufffd"


def test_terminate_handles_process_exit_race() -> None:
    """Verify terminate handles process exit race.

    Inputs: helper fakes. Output: fails on regressions in terminate handles process exit race.
    """

    class RacingProcess:
        """Test double for racing process behavior in this module."""

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: caller provides no extra arguments. Output: returns the fake value described above.
            """
            return None

        @staticmethod
        def kill():
            """Terminate the process.

            Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
            external operations fail.
            """
            raise ProcessLookupError

        @staticmethod
        def communicate():
            """Return process output.

            Inputs: none. Output: tuple.
            """
            return b"out", b"err"

    assert process_utils._terminate(RacingProcess()) == (b"out", b"err")  # type: ignore[arg-type]


def test_terminate_kills_process_group_for_new_session(monkeypatch) -> None:
    """Verify new-session subprocess cleanup targets the whole process group.

    Inputs: pytest provides `monkeypatch`. Output: fails on subprocess group cleanup
    regressions.
    """
    killed = []

    class GroupProcess:
        """Test double for a new-session process."""

        pid = 4321
        returncode = None
        _process_utils_start_new_session = True

        @staticmethod
        def poll():
            """Return process completion status.

            Inputs: none. Output: None.
            """
            return None

        @staticmethod
        def communicate():
            """Return process output.

            Inputs: none. Output: tuple.
            """
            return b"", b""

    monkeypatch.setattr(
        process_utils.os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    process_utils._terminate(GroupProcess())  # type: ignore[arg-type]

    assert killed == [(4321, process_utils.signal.SIGKILL)]


def test_run_streaming_timeout_preserves_partial_output() -> None:
    """Check that run streaming timeout preserves partial output remains stable.

    Inputs: helper fakes. Output: fails on regressions in run streaming timeout preserves partial output.
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

    Inputs: pytest provides `monkeypatch`. Output: fails on regressions in run streaming collects process finished at timeout boundary.
    """

    class FinishedProcess:
        """Test double for finished process behavior in this module."""

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
        lambda _command, *, env, cwd, start_new_session=False: FinishedProcess(),
    )

    def monotonic() -> float:
        """Return the monotonic.

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
    """Confirm run streaming raises called process error with output exposes the expected failure.

    Inputs: helper fakes. Output: fails on regressions when run streaming raises called process error with output stops reporting the expected error.
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

    Inputs: helper fakes. Output: fails on regressions in run handles large unbroken output.
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

    Inputs: helper fakes. Output: fails on regressions in run streaming handles large unbroken output.
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

    Inputs: helper fakes. Output: fails on regressions in run works inside running event loop.
    """

    async def _exercise() -> None:
        """Record the exercise call on the test double for later assertions.

        Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
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
    """Verify the run inside running event loop propagates command errors execution contract.

    Inputs: helper fakes. Output: fails on regressions in run inside running event loop propagates command errors integration.
    """

    async def _exercise() -> None:
        """Record the exercise call on the test double for later assertions.

        Inputs: caller provides no extra arguments. Output: runs the fake behavior described above.
        """
        with pytest.raises(process_utils.CalledProcessError) as excinfo:
            process_utils.run(
                [sys.executable, "-c", "import sys; sys.exit(9)"],
                check=True,
            )

        assert excinfo.value.returncode == 9

    asyncio.run(_exercise())
