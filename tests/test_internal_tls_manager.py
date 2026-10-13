"""Certificate-service lifecycle and persistent-storage safety contracts."""

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from monitoring.tls import certificates as tls
from monitoring.tls import manager


@pytest.fixture
def setup(tmp_path):
    """Inputs: temporary root. Output: dedicated PKI fixture and identity config."""
    for path in (
        tmp_path / "private",
        tmp_path / "trust",
        tmp_path / "servers",
        tmp_path / "servers/service",
    ):
        path.mkdir(mode=0o700)
    identity = tls.Identity("service", ("service",), os.getuid(), os.getgid())
    config = tmp_path / "identities.json"
    config.write_text(
        json.dumps(
            [
                {
                    "name": identity.name,
                    "names": list(identity.names),
                    "uid": identity.uid,
                    "gid": identity.gid,
                }
            ]
        )
    )
    return tmp_path, (identity,), config


def test_read_actual_default_identity_contract():
    """Inputs: shipped identity manifest. Output: validated complete service set."""
    root = Path(__file__).resolve().parents[1]
    identities = manager.load_identities(root / "monitoring/tls/identities.json")
    assert {x.name for x in identities} == {
        "database",
        "database_plugin",
        "grafana",
        "loki",
        "prometheus",
    }


def test_readiness_tracks_real_material_and_heartbeat(setup):
    """Inputs: missing/stale PKI. Output: readiness reflects actual material age."""
    root, identities, _ = setup
    now = datetime.now(UTC).replace(microsecond=0)
    assert not manager.healthy(root, identities, now=now)
    tls.reconcile(
        root / "private", root / "trust", root / "servers", identities, now=now
    )
    assert manager.healthy(root, identities, now=now)
    assert not manager.healthy(root, identities, now=now + timedelta(seconds=901))
    assert not manager.healthy(root, identities, now=now - timedelta(seconds=301))
    status = root / "trust/status.json"
    raw = json.loads(status.read_text())
    raw["expires_at"]["service"] += 1
    with tls.directory(root / "trust") as descriptor:
        tls.publish(
            descriptor,
            status.name,
            json.dumps(raw).encode(),
            mode=0o444,
            uid=os.getuid(),
            gid=os.getgid(),
        )
    assert not manager.healthy(root, identities, now=now)


def test_no_ephemeral_filesystem_fallback(setup):
    """Inputs: unmounted directories. Output: failure without ephemeral PKI writes."""
    root, identities, config = setup
    with pytest.raises(ValueError, match="persistent mount"):
        manager.validate_volumes(root, identities)
    assert manager.main(["once", "--root", str(root), "--identities", str(config)]) == 1
    assert not list((root / "private").iterdir())


@pytest.mark.parametrize("name", ["private/key.pem", "servers/service/key.pem"])
def test_missing_runtime_keys_cannot_pass_readiness(setup, name):
    """Inputs: missing private keys. Output: unhealthy status without regeneration."""
    root, identities, _ = setup
    tls.reconcile(root / "private", root / "trust", root / "servers", identities)
    (root / name).unlink()
    assert not manager.healthy(root, identities)
    assert not (root / name).exists()


def test_changed_identity_requires_reconciliation_before_readiness(setup):
    """Inputs: changed SAN. Output: unhealthy until real reconciliation completes."""
    root, identities, _ = setup
    tls.reconcile(root / "private", root / "trust", root / "servers", identities)
    changed = (
        tls.Identity("service", ("new.example.test",), os.getuid(), os.getgid()),
    )
    assert not manager.healthy(root, changed)
    tls.reconcile(root / "private", root / "trust", root / "servers", changed)
    assert manager.healthy(root, changed)


def test_all_identity_volumes_are_required(setup, monkeypatch):
    """Inputs: mount inventory. Output: validation visits every required volume."""
    root, identities, _ = setup
    expected = {root / "private", root / "trust", root / "servers/service"}
    visited = []

    def is_mount(path):
        """Inputs: mount path. Output: recorded visit and fixture mount status."""
        visited.append(path)
        return path in expected

    monkeypatch.setattr(manager.os.path, "ismount", is_mount)
    manager.validate_volumes(root, identities)
    assert set(visited) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [],
        [{}],
        [{"name": "x", "names": [], "uid": 0, "gid": 0}],
        [{"name": "x", "names": "service", "uid": 0, "gid": 0}],
        [{"name": "x", "names": [123], "uid": 0, "gid": 0}],
    ],
)
def test_invalid_identity_schema_has_no_side_effects(setup, value):
    """Inputs: invalid schema. Output: rejection and unchanged private state."""
    root, _, config = setup
    config.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        manager.load_identities(config)
    assert not list((root / "private").iterdir())


def test_duplicate_and_oversize_configuration(setup):
    """Inputs: duplicate/oversized config. Output: parser errors before PKI access."""
    _, _, config = setup
    rows = json.loads(config.read_text())
    config.write_text(json.dumps(rows + rows))
    with pytest.raises(ValueError, match="Duplicate"):
        manager.load_identities(config)
    config.write_bytes(b" " * 65537)
    with pytest.raises(ValueError, match="exceeds limit"):
        manager.load_identities(config)


def test_retry_retains_existing_material_then_recovers(setup, monkeypatch, caplog):
    """Inputs: transient disk failure. Output: retry, recovery and sanitized logs."""
    root, identities, _ = setup
    calls = []
    original = manager.reconcile

    def transient(*args, **kwargs):
        """Inputs: reconciliation call. Output: initial error, then real reconciliation."""
        calls.append(1)
        if len(calls) == 1:
            raise OSError("private details must not be logged")
        return original(*args, **kwargs)

    class StopAfterRecovery:
        """Bound the production retry loop without time-based sleeps."""

        def is_set(self):
            """Inputs: loop check. Output: false until the bounded wait stops iteration."""
            return False

        def wait(self, seconds):
            """Inputs: retry interval. Output: stop after the second reconciliation."""
            assert seconds == manager.INTERVAL_SECONDS
            return len(calls) == 2

    monkeypatch.setattr(manager, "reconcile", transient)
    monkeypatch.setattr(manager, "system_trust_bundle", lambda: b"")
    manager.serve(root, identities, StopAfterRecovery())
    assert len(calls) == 2
    assert manager.healthy(root, identities)
    assert "OSError" in caplog.text
    assert "private details" not in caplog.text


def test_stopped_service_does_not_mutate_volumes(setup):
    """Inputs: set stop event. Output: no new reconciliation or PKI files."""
    root, identities, _ = setup
    stop = threading.Event()
    stop.set()
    manager.serve(root, identities, stop)
    assert not list((root / "private").iterdir())


def test_once_and_readonly_health_cli(setup, monkeypatch):
    """Inputs: real PKI and CLI args. Output: one-shot success and read-only health."""
    root, _, config = setup
    monkeypatch.setattr(manager.os.path, "ismount", lambda _path: True)
    tls.reconcile(root / "private", root / "trust", root / "servers", setup[1])
    public_anchor = root / "fixture-platform-ca.pem"
    public_anchor.write_bytes((root / "trust/ca.pem").read_bytes())
    monkeypatch.setattr(
        manager.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile=str(public_anchor)),
    )
    args = ["--root", str(root), "--identities", str(config)]
    assert manager.main(["once", *args]) == 0
    before = {
        str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert manager.main(["check", *args]) == 0
    assert {
        str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == before


def test_absent_platform_ca_is_reported(monkeypatch):
    """Inputs: absent platform CA. Output: explicit trust-store failure."""
    monkeypatch.setattr(
        manager.ssl, "get_default_verify_paths", lambda: SimpleNamespace(cafile=None)
    )
    with pytest.raises(ValueError, match="System CA bundle is unavailable"):
        manager.system_trust_bundle()


def test_readiness_rejects_mismatched_leaf_key(setup):
    """Inputs: replaced leaf key. Output: unhealthy status without rewriting PKI."""
    root, identities, _ = setup
    tls.reconcile(root / "private", root / "trust", root / "servers", identities)
    raw = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with tls.directory(root / "servers/service") as descriptor:
        tls.publish(
            descriptor, "key.pem", raw, mode=0o600, uid=os.getuid(), gid=os.getgid()
        )
    assert not manager.healthy(root, identities)
    assert (root / "servers/service/key.pem").read_bytes() == raw


def test_service_signals_stop_before_new_reconciliation(setup, monkeypatch):
    """Inputs: stop during signal registration. Output: clean exit without creating PKI."""
    root, _, config = setup
    registered = []

    def register(signum, handler):
        """Inputs: signal and handler. Output: recorded handler and simulated SIGINT."""
        registered.append(signum)
        if signum == signal.SIGINT:
            handler(signum, None)

    monkeypatch.setattr(manager.os.path, "ismount", lambda _path: True)
    monkeypatch.setattr(manager.signal, "signal", register)
    assert (
        manager.main(["serve", "--root", str(root), "--identities", str(config)]) == 0
    )
    assert registered == [signal.SIGTERM, signal.SIGINT]
    assert not list((root / "private").iterdir())


def test_cli_rejects_ephemeral_pki_and_never_prints_configuration(setup):
    """Inputs: real CLI and unmounted PKI. Output: failure without private paths or writes."""
    root, _, config = setup
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "monitoring.tls.manager",
            "once",
            "--root",
            str(root),
            "--identities",
            str(config),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1
    assert "Certificate service unavailable (ValueError)" in result.stderr
    assert str(root) not in result.stderr
    assert not list((root / "private").iterdir())
