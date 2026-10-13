"""Exercise coverage collection in real child interpreters, not mocked reports."""

import configparser
import os
from pathlib import Path
import select
import signal
import subprocess
import sys

import coverage
import pytest

from tools import run_local_workflow_gates as gates


@pytest.mark.parametrize("collect_on_termination", [False, True])
def test_linux_service_termination_saves_only_executed_lines(
    tmp_path, collect_on_termination
):
    """Inputs: a real service child and SIGTERM. Output: enabled collection preserves executed lines, not unrun branches."""
    repository_config = configparser.ConfigParser()
    repository_config.read(Path(__file__).resolve().parents[1] / ".coveragerc")
    assert repository_config.getboolean("run", "sigterm", fallback=False)
    source = tmp_path / "application"
    source.mkdir()
    module = source / "runtime.py"
    module.write_text(
        "import time\n"
        "def live():\n"
        "    print('ready', flush=True)\n"
        "    while True:\n"
        "        time.sleep(1)\n"
        "def never_called():\n"
        "    return 99\n"
        "live()\n"
    )
    config = tmp_path / ".coveragerc"
    config.write_text(
        "[run]\nsource = ./application\nrelative_files = true\n"
        f"sigterm = {str(collect_on_termination).lower()}\n"
    )
    data_file = tmp_path / ".coverage.service"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COVERAGE_")
    }
    environment["COVERAGE_FILE"] = str(data_file)
    process = subprocess.Popen(
        [sys.executable, "-m", "coverage", "run", str(module)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "Service did not reach its running state."
        assert process.stdout.readline().strip() == "ready"
        process.terminate()
        output, errors = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
    assert process.returncode == -signal.SIGTERM
    assert not output and not errors
    measured = coverage.Coverage(data_file=str(data_file), config_file=str(config))
    measured.load()
    lines = set(measured.get_data().lines("application/runtime.py") or [])
    if collect_on_termination:
        assert {1, 2, 3, 6, 8} <= lines
        assert 7 not in lines
    else:
        assert not lines


def test_split_runner_measures_children_and_rejects_stale_coverage(tmp_path):
    """Inputs: isolated suites and stale data. Output: honest gaps and preserved raw data."""
    source = tmp_path / "application"
    source.mkdir()
    module = source / "runtime.py"
    module.write_text("def child():\n    return 42\n\ndef old_only():\n    return 99\n")
    config = tmp_path / ".coveragerc"
    config.write_text(
        "[run]\nsource = ./application\npatch = subprocess\nrelative_files = true\n"
        "[report]\nfail_under = 100\ninclude_namespace_packages = true\n"
    )
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(tmp_path / ".coverage.stale")
    old = tmp_path / "old.py"
    old.write_text(
        "from application.runtime import old_only\nassert old_only() == 99\n"
    )
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", str(old)],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        timeout=30,
    )
    for suite in (
        "tests",
        "omero_plugin_common/tests",
        "omero_imaris_connector/tests",
        "omeroweb_admin_tools/tests",
        "omeroweb_omp_plugin/tests",
        "omeroweb_import/tests",
        "omeroweb_tools/tests",
        "omero_web_zarr/tests",
    ):
        directory = tmp_path / suite
        directory.mkdir(parents=True)
        (directory / "test_child.py").write_text(
            "import subprocess, sys\n"
            "def test_child():\n"
            "    result = subprocess.run([sys.executable, '-c', "
            "'from application.runtime import child; print(child())'], "
            "capture_output=True, text=True, check=True, timeout=10)\n"
            "    assert result.stdout.strip() == '42'\n"
        )
    context = gates.GateContext(
        repo_root=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        tool_venv=Path(sys.prefix),
        python=sys.executable,
        keep_going=True,
    )
    with pytest.raises(gates.GateError, match="coverage xml failed"):
        gates.run_tests(context)
    combined = next((tmp_path / "artifacts").glob("coverage-*/.coverage"))
    measured = coverage.Coverage(data_file=str(combined), config_file=str(config))
    measured.load()
    assert measured.get_data().lines("application/runtime.py") == [1, 2, 4]
    report = (tmp_path / "coverage.xml").read_text()
    assert 'number="2" hits="1"' in report
    assert 'number="5" hits="0"' in report
    assert list(tmp_path.glob(".coverage.stale.*"))
    assert len(list((tmp_path / "artifacts").glob("coverage-*/.coverage.*"))) >= 16
