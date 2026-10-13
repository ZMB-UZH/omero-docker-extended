"""Exercise actual process shutdown/reload and TLS upgrade checks on Linux."""

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

from tools import env_safety_guard as guard


REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "monitoring/tls/watch-trust.sh"


def until(predicate, timeout=10):
    """Inputs: predicate and timeout. Output: completion or bounded test failure."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail("Expected process event did not occur")


@contextmanager
def running(trust, arguments, *, environment=None):
    """Inputs: command and trust file. Output: managed process with guaranteed cleanup."""
    env = os.environ | {"SSL_CERT_FILE": str(trust)} | (environment or {})
    process = subprocess.Popen(
        ["/bin/sh", str(WRAPPER), *arguments],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # An already-exited process group needs no cleanup.
            process.poll()
        process.wait(timeout=3)


def test_shutdown_before_trust_exists_never_starts_child(tmp_path):
    """Inputs: stop before trust exists. Output: prompt exit without child startup."""
    with running(tmp_path / "missing.pem", ["/bin/sh", "-c", "exit 91"]) as process:
        time.sleep(0.1)
        process.terminate()
        assert process.wait(timeout=3) == 0


@pytest.mark.parametrize("status", [0, 42])
def test_child_exit_without_renewal_preserves_status(tmp_path, status):
    """Inputs: child exit code. Output: unchanged wrapper exit code."""
    trust = tmp_path / "ca.pem"
    trust.write_text("public fixture certificate")
    with running(trust, ["/bin/sh", "-c", f"exit {status}"]) as process:
        assert process.wait(timeout=3) == status


def test_changed_trust_restarts_once_and_operator_stop_does_not_restart(tmp_path):
    """Inputs: trust renewal and stop. Output: one restart, then no active children."""
    trust = tmp_path / "ca.pem"
    trust.write_text("first public certificate")
    starts = tmp_path / "starts"
    child = tmp_path / "service.sh"
    child.write_text(
        'printf "%s\\n" "$$" >> "$STARTS"\n'
        'trap "exit 0" TERM INT\n'
        "while :; do sleep 0.1; done\n"
    )
    with running(
        trust, ["/bin/sh", str(child)], environment={"STARTS": str(starts)}
    ) as process:
        until(lambda: starts.exists())
        replacement = tmp_path / "new.pem"
        replacement.write_text("renewed public certificate")
        replacement.replace(trust)
        until(lambda: len(starts.read_text().splitlines()) == 2)
        process.terminate()
        process.wait(timeout=3)
        assert len(starts.read_text().splitlines()) == 2
        for pid in starts.read_text().splitlines():
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid), 0)


@pytest.mark.parametrize("key", guard.MONITORING_TLS_URL_KEYS)
@pytest.mark.parametrize(
    "value",
    [
        "http://service:3000",  # DevSkim: ignore DS137138 -- rejected plaintext fixture
        "https://user:private-value@service",
        "https://service:wrong",
        "https://service:0",
        "https://service/path?secret=private-value",
        "https://service/#fragment",
        "https://service name",
        "https://[broken",
        "",
    ],
)
def test_transport_preflight_rejects_unsafe_settings_without_value_leak(key, value):
    """Inputs: invalid URLs. Output: setting-specific errors without value disclosure."""
    errors = guard.validate_assignment_value(key, value, value)
    assert errors and key in errors[0]
    assert "private-value" not in str(errors)
    if value:
        assert value not in str(errors)


@pytest.mark.parametrize(
    "url",
    [
        "https://grafana:3000",
        "https://metrics.example.test/custom/base",
        "https://localhost:9443",
        "https://127.0.0.1:9443",
        "https://[::1]:9443",
    ],
)
def test_transport_preflight_accepts_installation_independent_tls_urls(url):
    """Inputs: varied HTTPS URLs. Output: acceptance independent of installation."""
    for key in guard.MONITORING_TLS_URL_KEYS:
        assert guard.validate_assignment_value(key, url, url) == []


def test_compose_transport_preflight_does_not_modify_deployment_files(tmp_path):
    """Inputs: legacy settings. Output: validation error and unchanged operator files."""
    folder = tmp_path / "env"
    folder.mkdir()
    for name in guard.EXPECTED_COMPOSE_ENV_FILES:
        (tmp_path / name).write_text("# fixture\n")
    source = folder / "omeroweb.env"
    original = "ADMIN_TOOLS_GRAFANA_URL=http://private-operator.example.test:3000\n"  # DevSkim: ignore DS137138 -- rejected legacy-setting fixture; never connected
    source.write_text(original)
    errors = guard.validate_monitoring_tls_urls(tmp_path)
    assert errors and "ADMIN_TOOLS_GRAFANA_URL" in errors[0]
    assert "private-operator" not in str(errors)
    assert source.read_text() == original
