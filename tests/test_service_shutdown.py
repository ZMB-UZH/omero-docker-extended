"""Real process tests for service termination and unexpected child exits."""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "docker/omero-server-entrypoint.sh"
MAINTENANCE = ROOT / "maintenance/postgres/pg-maintenance-entrypoint.sh"
BASH = "/bin/bash"


def executable(path, text):
    """Inputs: a path and shell body. Output: an executable private test program."""
    path.write_text("#!/bin/bash\nset -eu\n" + text)
    path.chmod(0o700)
    return path


def wait_file(path, process):
    """Inputs: a readiness file and process. Output: readiness or a bounded failure."""
    deadline = time.monotonic() + 5
    while not path.exists():
        assert process.poll() is None, "Supervisor exited before readiness"
        assert time.monotonic() < deadline, "Child readiness timed out"
        time.sleep(0.01)


def reap(process):
    """Inputs: the owned process session. Output: cleanup only if the test failed."""
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.communicate(timeout=5)


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT])
def test_maintenance_stops_both_children_and_waits(tmp_path, number):
    """Inputs: real cron/tail stand-ins. Output: forwarded signals and reaped PIDs."""
    for name in ("cron", "tail"):
        executable(
            tmp_path / name,
            "name=${0##*/}\n"
            "trap 'printf stopped > \"$TEST_ROOT/$name.stopped\"; exit 0' TERM\n"
            'printf "%s\\n" "$$" > "$TEST_ROOT/$name.pid"\n'
            "while :; do sleep 0.05; done\n",
        )
    env = os.environ | {
        "TEST_ROOT": str(tmp_path),
        "PATH": str(tmp_path) + ":" + os.environ["PATH"],
    }
    process = subprocess.Popen(
        [
            BASH,
            "-c",
            'source "$1"; LOG_FILE="$2"; run_services',
            "test",
            str(MAINTENANCE),
            str(tmp_path / "log"),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        for name in ("cron", "tail"):
            wait_file(tmp_path / f"{name}.pid", process)
        process.send_signal(number)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        for name in ("cron", "tail"):
            assert (tmp_path / f"{name}.stopped").read_text() == "stopped"
            with pytest.raises(ProcessLookupError):
                os.kill(int((tmp_path / f"{name}.pid").read_text()), 0)
    finally:
        reap(process)


@pytest.mark.parametrize("failing", ["cron", "tail"])
@pytest.mark.parametrize("code", [0, 19])
def test_maintenance_exits_if_either_service_dies(tmp_path, failing, code):
    """Inputs: one terminating child. Output: failure, with its sibling stopped."""
    for name in ("cron", "tail"):
        body = f"sleep 0.1\nexit {code}\n" if name == failing else "exec sleep 30\n"
        executable(tmp_path / name, body)
    result = subprocess.run(
        [
            BASH,
            "-c",
            'source "$1"; LOG_FILE="$2"; run_services',
            "test",
            str(MAINTENANCE),
            str(tmp_path / "log"),
        ],
        env=os.environ | {"PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == (code or 1), result.stderr


@pytest.mark.parametrize("stage", ["99-run.sh", "10-bootstrap.sh"])
@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT])
def test_server_requests_orderly_stop_before_terminating_cli(tmp_path, stage, number):
    """Inputs: foreground/startup children. Output: ordered shutdown and child reaping."""
    child = executable(
        tmp_path / stage,
        "trap 'printf terminated >> \"$TEST_ROOT/events\"; exit 0' TERM\n"
        'printf "%s\\n" "$$" > "$TEST_ROOT/child.pid"\n'
        "while :; do sleep 0.05; done\n",
    )
    cli = executable(
        tmp_path / "omero",
        'test "$1 $2" = "admin stop"\nprintf stopped- >> "$TEST_ROOT/events"\n',
    )
    shell = (
        'source "$1"; as_server() { "$@"; }; omero_cli="$2"; run_startup_script "$3"'
    )
    process = subprocess.Popen(
        [BASH, "-c", shell, "test", str(SERVER), str(cli), str(child)],
        env=os.environ | {"TEST_ROOT": str(tmp_path)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        wait_file(tmp_path / "child.pid", process)
        process.send_signal(number)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        expected = "stopped-terminated" if stage == "99-run.sh" else "terminated"
        assert (tmp_path / "events").read_text() == expected
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / "child.pid").read_text()), 0)
    finally:
        reap(process)


@pytest.mark.parametrize("stage", ["50-config.py", "60-database.sh", "99-run.sh"])
def test_startup_stage_retains_status_and_literal_arguments(tmp_path, stage):
    """Inputs: all startup dispatch modes. Output: identical argv and failure status."""
    child = executable(tmp_path / stage, 'printf "%s\\n" "$@"\nexit 23\n')
    argument = "literal spaces; $(must-not-run)"
    result = subprocess.run(
        [
            BASH,
            "-c",
            'source "$1"; as_server() { "$@"; }; run_startup_script "$2" "$3"',
            "test",
            str(SERVER),
            str(child),
            argument,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 23
    assert result.stdout == argument + "\n"
    assert not result.stderr


def test_direct_unprivileged_command_is_not_bootstrapped(tmp_path):
    """Inputs: a non-root identity fixture. Output: literal exec argv and status."""
    executable(tmp_path / "id", "printf '999\\n'\n")
    result = subprocess.run(
        [BASH, str(SERVER), BASH, "-c", "exit 17"],
        env=os.environ | {"PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 17
    assert "skipping root startup bootstrap" in result.stdout
