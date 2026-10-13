"""Exercise exporter failure recovery with real files, df and a child process."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "monitoring"
    / "path-usage-exporter"
    / "path_usage_exporter.py"
)


@pytest.fixture
def exporter(tmp_path, monkeypatch):
    """Inputs: isolated environment and host root. Output: independent exporter module."""
    monkeypatch.setenv("PATH_USAGE_EXPORTER_HOST_ROOT", str(tmp_path))
    monkeypatch.setenv("PATH_USAGE_EXPORTER_OUTPUT", str(tmp_path / "metrics.prom"))
    spec = importlib.util.spec_from_file_location("path_usage_runtime", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 30), ("", 30), ("  ", 30), ("invalid", 30), ("0", 1), ("-8", 1), ("2", 2)],
)
def test_interval_configuration_is_bounded(exporter, monkeypatch, value, expected):
    """Inputs: absent, invalid or numeric interval. Output: documented default or bounded integer."""
    key = "PATH_USAGE_TEST_INTERVAL"
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    assert exporter.env_int(key, 30) == expected


def test_env_reader_handles_quotes_comments_and_equals_without_execution(
    exporter, tmp_path
):
    """Inputs: an ordinary env file. Output: literal configured values; no shell evaluation."""
    path = tmp_path / "paths.env"
    assert exporter.parse_env_file(str(path)) == {}
    path.write_text(
        "# comment\n\nnot-an-assignment\n"
        "OMERO_DATA_PATH = '/data with spaces'\n"
        'OMERO_DATABASE_PATH="/db=primary"\n'
        "OMERO_PLUGIN_DATABASE_PATH=/old\n"
        "OMERO_PLUGIN_DATABASE_PATH=/new\n"
        "LITERAL=$(not-a-shell-command)\n",
        encoding="utf-8",
    )
    assert exporter.parse_env_file(str(path)) == {
        "OMERO_DATA_PATH": "/data with spaces",
        "OMERO_DATABASE_PATH": "/db=primary",
        "OMERO_PLUGIN_DATABASE_PATH": "/new",
        "LITERAL": "$(not-a-shell-command)",
    }


@pytest.mark.parametrize(
    ("returncode", "output"),
    [(1, ""), (0, ""), (0, "header\n"), (0, "header\nshort row\n")],
)
def test_failed_or_incomplete_df_has_no_fabricated_usage(
    exporter, monkeypatch, returncode, output
):
    """Inputs: failed or incomplete df output. Output: no usage sample, with bounded subprocess arguments."""
    run = Mock(return_value=subprocess.CompletedProcess(["df"], returncode, output, ""))
    monkeypatch.setattr(exporter.subprocess, "run", run)
    assert exporter.df_usage("/fixture path", timeout_seconds=3) is None
    assert run.call_args.args == (["df", "-kP", "/fixture path"],)
    assert run.call_args.kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 3,
    }


def test_real_df_and_rendering_use_only_accessible_absolute_paths(exporter, tmp_path):
    """Inputs: existing, relative and missing paths. Output: one valid sample matching native df."""
    data = tmp_path / "science data"
    data.mkdir()
    native = exporter.df_usage(str(data))
    assert native is not None
    mountpoint, total, used, ratio = native
    assert mountpoint.startswith("/") and total > 0 and used >= 0
    assert ratio == used / total
    metrics = exporter.render_metrics(
        {
            "OMERO_DATA_PATH": "/science data",
            "OMERO_DATABASE_PATH": "relative",
            "OMERO_PLUGIN_DATABASE_PATH": "/missing",
        }
    )
    samples = [line for line in metrics.splitlines() if not line.startswith("#")]
    assert len(samples) == 3
    assert all('kind="omero_data"' in line for line in samples)
    assert all('path="/science data"' in line for line in samples)
    assert float(samples[1].rsplit(" ", 1)[1]) == total
    assert float(samples[2].rsplit(" ", 1)[1]) >= 0
    assert metrics.endswith("\n")


def test_unavailable_df_omits_only_that_target(exporter, tmp_path, monkeypatch):
    """Inputs: present path whose filesystem query fails. Output: metric declarations without a false zero."""
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(exporter, "df_usage", Mock(return_value=None))
    metrics = exporter.render_metrics({"OMERO_DATA_PATH": "/data"})
    assert len(metrics.splitlines()) == 6
    assert all(line.startswith("#") for line in metrics.splitlines())


@pytest.mark.parametrize("operation", ["fsync", "chmod", "replace"])
def test_atomic_publish_failure_retains_last_complete_sample(
    exporter, monkeypatch, operation
):
    """Inputs: publication failure at each durability step. Output: intact previous sample and no temporary remnants."""
    output = Path(exporter.OUT)
    exporter.write_metrics("sample 1\n")
    inode = output.stat().st_ino
    monkeypatch.setattr(
        exporter.os, operation, Mock(side_effect=OSError("fixture I/O failure"))
    )
    with pytest.raises(OSError, match="fixture I/O failure"):
        exporter.write_metrics("sample 2\n")
    assert output.read_text() == "sample 1\n"
    assert output.stat().st_ino == inode
    assert list(output.parent.iterdir()) == [output]


def test_temp_creation_failure_leaves_existing_output_intact(exporter, monkeypatch):
    """Inputs: unable to create a staging file. Output: old output untouched and original error propagated."""
    output = Path(exporter.OUT)
    exporter.write_metrics("sample 1\n")
    monkeypatch.setattr(
        exporter.tempfile,
        "NamedTemporaryFile",
        Mock(side_effect=PermissionError("fixture denied")),
    )
    with pytest.raises(PermissionError, match="fixture denied"):
        exporter.write_metrics("sample 2\n")
    assert output.read_text() == "sample 1\n"
    assert list(output.parent.iterdir()) == [output]


def test_disappearing_staging_file_preserves_original_failure(exporter, monkeypatch):
    """Inputs: staging file lost during publication. Output: original I/O failure, not a cleanup error."""
    output = Path(exporter.OUT)
    exporter.write_metrics("sample 1\n")

    def lose_staging(source, destination):
        """Inputs: staging and final paths. Output: simulate a lost staging inode without touching destination."""
        assert Path(destination) == output
        Path(source).unlink()
        raise OSError("fixture staging disappeared")

    monkeypatch.setattr(exporter.os, "replace", lose_staging)
    with pytest.raises(OSError, match="fixture staging disappeared"):
        exporter.write_metrics("sample 2\n")
    assert output.read_text() == "sample 1\n"
    assert list(output.parent.iterdir()) == [output]


def _wait_for(predicate, process, timeout=8):
    """Inputs: observable condition and owned child. Output: bounded wait that fails on premature process exit."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert process.poll() is None, "Exporter exited before publishing the sample."
        assert time.monotonic() < deadline, (
            "Exporter did not recover before the deadline."
        )
        time.sleep(0.02)


def test_exporter_process_recovers_after_unreadable_config_without_restart(tmp_path):
    """Inputs: malformed then repaired configuration. Output: same process publishes fresh metrics and reports the failed cycle."""
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "paths.env"
    config.write_bytes(b"\xff")
    output = tmp_path / "collector" / "paths.prom"
    log = tmp_path / "exporter.log"
    environment = os.environ | {
        "PATH_USAGE_EXPORTER_HOST_ROOT": str(tmp_path),
        "PATH_USAGE_EXPORTER_OUTPUT": str(output),
        "PATH_USAGE_EXPORTER_ENV_FILE": str(config),
        "PATH_USAGE_EXPORTER_INTERVAL_SECONDS": "1",
    }
    with log.open("wb") as stream:
        process = subprocess.Popen(
            [sys.executable, str(SOURCE)],
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for(lambda: b"UnicodeDecodeError" in log.read_bytes(), process)
            assert not output.exists()
            repaired = tmp_path / "repaired.env"
            repaired.write_text("OMERO_DATA_PATH=/data\n", encoding="utf-8")
            repaired.replace(config)
            _wait_for(output.exists, process)
            text = output.read_text()
            assert 'omero_path_bytes_total{kind="omero_data"' in text
            assert (
                len([line for line in text.splitlines() if not line.startswith("#")])
                == 3
            )
            previous = output.stat().st_mtime_ns
            _wait_for(lambda: output.stat().st_mtime_ns > previous, process)
            assert process.poll() is None
        finally:
            process.terminate()
            process.wait(timeout=5)
