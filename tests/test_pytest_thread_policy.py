"""Prove that the shared pytest policy rejects unhandled worker exceptions."""

from pathlib import Path
import os
import subprocess
import sys


def test_unhandled_worker_exception_is_a_failed_test(tmp_path):
    """Inputs: joined worker raising outside its caller. Output: nested pytest fails using the real repository configuration."""
    root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "test_thread_failure.py"
    fixture.write_text(
        "import threading\n"
        "def test_worker():\n"
        "    def fail():\n"
        "        raise RuntimeError('thread-failure-fixture')\n"
        "    worker = threading.Thread(target=fail)\n"
        "    worker.start()\n"
        "    worker.join()\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "pytest.ini"),
            "--basetemp",
            str(tmp_path / "inner"),
            "-q",
            "--tb=short",
            str(fixture),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTEST_ADDOPTS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PytestUnhandledThreadExceptionWarning" in result.stdout
    assert "thread-failure-fixture" in result.stdout
    assert "1 failed" in result.stdout
