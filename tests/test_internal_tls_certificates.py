"""Real PKI/filesystem/TLS tests, with no external service or installed host data."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
import socket
import ssl
import stat
import subprocess
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
import pytest

from monitoring.tls import certificates as tls


@pytest.fixture
def installation(tmp_path):
    """Inputs: temporary root. Output: disposable PKI layout and caller-owned IDs."""
    state, trust, targets = (
        tmp_path / name for name in ("private", "public", "servers")
    )
    for path in (state, trust, targets, targets / "monitoring", targets / "database"):
        path.mkdir(mode=0o700)
    identities = (
        tls.Identity(
            "monitoring",
            ("metrics", "metrics.example.test", "localhost", "127.0.0.1", "::1"),
            os.getuid(),
            os.getgid(),
        ),
        tls.Identity("database", ("database",), os.getuid(), os.getgid()),
    )
    return state, trust, targets, identities


def snapshot(root):
    """Inputs: root. Output: content, inode, mode and ownership of managed files."""
    return {
        str(path.relative_to(root)): (
            path.read_bytes(),
            path.stat().st_ino,
            stat.S_IMODE(path.stat().st_mode),
            path.stat().st_uid,
            path.stat().st_gid,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def certificate(path):
    """Inputs: PEM path. Output: real published X.509 certificate."""
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_fresh_setup_idempotence_and_secret_boundaries(installation):
    """Inputs: fresh PKI. Output: private-key separation and idempotent publication."""
    state, trust, targets, identities = installation
    now = datetime.now(UTC).replace(microsecond=0)
    tls.reconcile(*installation, now=now)
    before = snapshot(state.parent)
    tls.reconcile(*installation, now=now)
    assert snapshot(state.parent) == before
    ca = certificate(trust / "ca.pem")
    assert ca.extensions.get_extension_for_class(
        x509.BasicConstraints
    ).value == x509.BasicConstraints(True, 0)
    for identity in identities:
        leaf = certificate(targets / identity.name / "cert.pem")
        leaf.verify_directly_issued_by(ca)
        assert leaf.not_valid_after_utc == now + timedelta(days=30)
        assert leaf.extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        ).value == x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])
        assert leaf.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).critical
        assert (
            stat.S_IMODE((targets / identity.name / "key.pem").stat().st_mode) == 0o600
        )
        assert b"PRIVATE KEY" not in (targets / identity.name / "cert.pem").read_bytes()
    assert stat.S_IMODE((state / "key.pem").stat().st_mode) == 0o600
    assert all(b"PRIVATE KEY" not in path.read_bytes() for path in trust.iterdir())
    assert (
        len(
            {
                (state / "key.pem").read_bytes(),
                *(path.read_bytes() for path in targets.glob("*/key.pem")),
            }
        )
        == 3
    )


@pytest.mark.parametrize("signer", ["ed25519", "rsa"])
def test_certificate_rejects_non_ec_issuer_without_replacing_material(
    installation, signer
):
    """Inputs: real foreign-signed certificate. Output: explicit rejection, unchanged keys/files."""
    state, trust, targets, identities = installation
    tls.reconcile(*installation)
    key = tls.load_private_key((state / "key.pem").read_bytes())
    foreign = (
        ed25519.Ed25519PrivateKey.generate()
        if signer == "ed25519"
        else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    now = datetime.now(UTC)
    forged = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([]))
        .issuer_name(x509.Name([]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(foreign, None if signer == "ed25519" else hashes.SHA256())
    )
    (state / "cert.pem").write_bytes(forged.public_bytes(serialization.Encoding.PEM))
    before = snapshot(state.parent)
    with pytest.raises(ValueError, match="signature algorithm"):
        tls.reconcile(state, trust, targets, identities)
    assert snapshot(state.parent) == before


@pytest.mark.parametrize("elapsed", [20, 31, 3651])
def test_early_renewal_and_long_offline_recovery(installation, elapsed):
    """Inputs: expired PKI. Output: restored validity with original key identities."""
    state, trust, targets, _ = installation
    first = datetime.now(UTC).replace(microsecond=0)
    tls.reconcile(*installation, now=first)
    original_ca = certificate(trust / "ca.pem")
    original_leaf = certificate(targets / "monitoring/cert.pem")
    keys = {path: path.read_bytes() for path in state.parent.rglob("key.pem")}
    later = first + timedelta(days=elapsed)
    tls.reconcile(*installation, now=later)
    ca = certificate(trust / "ca.pem")
    leaf = certificate(targets / "monitoring/cert.pem")
    leaf.verify_directly_issued_by(ca)
    assert leaf.serial_number != original_leaf.serial_number
    assert leaf.not_valid_after_utc == later + timedelta(days=30)
    assert ca.not_valid_after_utc > leaf.not_valid_after_utc
    assert ca.public_key() == original_ca.public_key()
    assert {path: path.read_bytes() for path in keys} == keys


def test_ca_renews_before_expiry_without_replacing_service_keys(installation):
    """Inputs: expiring authority. Output: renewed CA compatible with original keys."""
    _, trust, targets, _ = installation
    first = datetime.now(UTC).replace(microsecond=0)
    tls.reconcile(*installation, now=first)
    ca = certificate(trust / "ca.pem")
    later = first + timedelta(days=3650 - 365)
    tls.reconcile(*installation, now=later)
    renewed = certificate(trust / "ca.pem")
    assert renewed.serial_number != ca.serial_number
    assert renewed.public_key() == ca.public_key()
    certificate(targets / "monitoring/cert.pem").verify_directly_issued_by(renewed)


def test_certificate_name_change_is_applied_without_changing_other_identity(
    installation,
):
    """Inputs: changed service SAN. Output: only that service certificate changes."""
    state, trust, targets, identities = installation
    now = datetime.now(UTC).replace(microsecond=0)
    tls.reconcile(*installation, now=now)
    previous = snapshot(targets)
    changed = (
        tls.Identity("monitoring", ("new.example.test",), os.getuid(), os.getgid()),
        identities[1],
    )
    tls.reconcile(state, trust, targets, changed, now=now)
    after = snapshot(targets)
    assert {name for name in after if after[name] != previous[name]} == {
        "monitoring/cert.pem"
    }


@pytest.mark.parametrize(
    "destination", ["private/key.pem", "servers/monitoring/key.pem"]
)
def test_missing_established_keys_never_reset_installation_trust(
    installation, destination
):
    """Inputs: missing established keys. Output: failure without resetting trust."""
    state, _, _, _ = installation
    tls.reconcile(*installation)
    (state.parent / destination).unlink()
    before = snapshot(state.parent)
    with pytest.raises(ValueError, match="key is missing"):
        tls.reconcile(*installation)
    assert snapshot(state.parent) == before


@pytest.mark.parametrize(
    "destination", ["private/key.pem", "public/ca.pem", "servers/monitoring/cert.pem"]
)
def test_linked_files_never_touch_unrelated_content(installation, destination):
    """Inputs: linked managed files. Output: rejection and untouched unrelated data."""
    state, _, _, _ = installation
    victim = state.parent / "keep"
    victim.write_bytes(b"unrelated original data")
    (state.parent / destination).symlink_to(victim)
    with pytest.raises(OSError):
        tls.reconcile(*installation)
    assert victim.read_bytes() == b"unrelated original data"


def test_hardlinked_and_special_files_are_rejected(installation):
    """Inputs: hardlinks and FIFOs. Output: rejection without reading unrelated data."""
    state, _, _, _ = installation
    victim = state.parent / "keep"
    victim.write_bytes(b"unchanged")
    key = state / "key.pem"
    os.link(victim, key)
    with pytest.raises(ValueError, match="managed certificate file"):
        tls.reconcile(*installation)
    key.unlink()
    os.mkfifo(key)
    with pytest.raises(ValueError, match="managed certificate file"):
        tls.reconcile(*installation)
    assert victim.read_bytes() == b"unchanged"


@pytest.mark.parametrize(
    "field", ["leaf", "leaf_renew_before", "ca_renew_before", "ca", "backdate"]
)
def test_invalid_renewal_windows_are_rejected(field):
    """Inputs: invalid validity windows. Output: rejection before any certificate work."""
    value = timedelta(days=-1) if field == "backdate" else timedelta(0)
    with pytest.raises(ValueError, match="renewal windows"):
        tls.Lifetime(**{field: value})


def test_unsafe_directory_and_growing_file_are_rejected(installation, monkeypatch):
    """Inputs: writable PKI directory and growing file. Output: bounded fail-closed reads."""
    state, _, _, _ = installation
    state.chmod(0o722)
    with pytest.raises(ValueError, match="unsafe ownership or permissions"):
        with tls.directory(state):
            pytest.fail("Unsafe directory was accepted")
    state.chmod(0o700)
    content = state / "oversize.pem"
    content.write_bytes(b"x" * (tls.MAX_MANAGED_BYTES + 1))
    with tls.directory(state) as descriptor:
        with pytest.raises(ValueError, match="Invalid managed certificate file"):
            tls.read_file(descriptor, content.name)
        stat_original = tls.os.fstat

        def before_growth(fd):
            """Inputs: descriptor. Output: pre-growth size while retaining real file metadata."""
            metadata = list(stat_original(fd))
            metadata[6] = 0
            return os.stat_result(metadata)

        monkeypatch.setattr(tls.os, "fstat", before_growth)
        with pytest.raises(ValueError, match="exceeds limit"):
            tls.read_file(descriptor, content.name)


def test_foreign_private_key_profile_is_rejected():
    """Inputs: valid PEM with a different curve. Output: explicit managed-profile rejection."""
    raw = ec.generate_private_key(ec.SECP384R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="key type"):
        tls.load_private_key(raw)


def test_invalid_clock_identity_set_and_oversize_trust_do_not_write(installation):
    """Inputs: invalid reconciliation inputs. Output: validation without PKI side effects."""
    state, trust, targets, identities = installation
    for invalid in ((), identities + identities):
        with pytest.raises(ValueError, match="aware time and unique"):
            tls.reconcile(state, trust, targets, invalid)
    with pytest.raises(ValueError, match="aware time and unique"):
        tls.reconcile(*installation, now=datetime.now())
    with pytest.raises(ValueError, match="bundle exceeds limit"):
        tls.reconcile(*installation, system_trust=b"x" * tls.MAX_MANAGED_BYTES)
    assert snapshot(state.parent) == {}


def test_lock_hardlink_cannot_modify_unrelated_state(installation):
    """Inputs: hardlinked issuer lock. Output: rejection without modifying either link."""
    state, _, _, _ = installation
    original = state.parent / "unrelated"
    original.write_bytes(b"preserve")
    os.link(original, state / "issuer.lock")
    with pytest.raises(ValueError, match="issuer lock"):
        tls.reconcile(*installation)
    assert original.read_bytes() == b"preserve"
    assert set(path.name for path in state.iterdir()) == {"issuer.lock"}


def test_missing_authority_cannot_reset_existing_leaf_state(installation):
    """Inputs: orphaned service material. Output: rejection without replacing service keys."""
    state, trust, targets, _ = installation
    tls.reconcile(*installation)
    for path in (state / "cert.pem", state / "key.pem", trust / "ca.pem"):
        path.unlink()
    before = snapshot(targets)
    with pytest.raises(ValueError, match="authority or service key is missing"):
        tls.reconcile(*installation)
    assert snapshot(targets) == before
    assert not (state / "key.pem").exists()


def test_certificate_key_mismatch_preserves_evidence(installation):
    """Inputs: swapped leaf certificates. Output: rejection with original evidence intact."""
    _, _, targets, _ = installation
    tls.reconcile(*installation)
    with tls.directory(targets / "monitoring") as descriptor:
        tls.publish(
            descriptor,
            "cert.pem",
            (targets / "database/cert.pem").read_bytes(),
            mode=0o444,
            uid=os.getuid(),
            gid=os.getgid(),
        )
    before = snapshot(targets)
    with pytest.raises(ValueError, match="do not match"):
        tls.reconcile(*installation)
    assert snapshot(targets) == before


def test_authority_constraints_cannot_be_weakened(installation):
    """Inputs: self-signed non-CA certificate. Output: failure without republishing trust."""
    state, trust, _, _ = installation
    tls.reconcile(*installation)
    before = snapshot(trust)
    now = datetime.now(UTC)
    with tls.directory(state) as descriptor:
        key = tls.load_private_key(tls.read_file(descriptor, "key.pem"))
        subject = certificate(state / "cert.pem").subject
        invalid = tls.issue(
            key,
            key,
            subject=subject,
            issuer=subject,
            names=("metrics",),
            start=now - timedelta(minutes=1),
            end=now + timedelta(days=1),
            authority=False,
        )
        tls.publish(
            descriptor,
            "cert.pem",
            invalid.public_bytes(serialization.Encoding.PEM),
            mode=0o600,
            uid=os.getuid(),
            gid=os.getgid(),
        )
    with pytest.raises(ValueError, match="authority constraints"):
        tls.reconcile(*installation)
    assert snapshot(trust) == before


def test_concurrent_reconcilers_publish_a_single_consistent_authority(installation):
    """Inputs: concurrent reconciliations. Output: one consistent CA and no residue."""
    now = datetime.now(UTC).replace(microsecond=0)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(lambda _: tls.reconcile(*installation, now=now), range(8))
        )
    assert all(result == results[0] for result in results)
    _, trust, targets, _ = installation
    certificate(targets / "monitoring/cert.pem").verify_directly_issued_by(
        certificate(trust / "ca.pem")
    )
    assert not list(installation[0].parent.rglob(".certificate-*"))


def test_failed_atomic_publication_preserves_previous_trust(installation, monkeypatch):
    """Inputs: interrupted publication. Output: preserved trust and successful retry."""
    _, trust, _, _ = installation
    first = datetime.now(UTC).replace(microsecond=0)
    tls.reconcile(*installation, now=first)
    before = (trust / "ca.pem").read_bytes()
    replace = tls.os.replace

    def disk_failure(source, target, **kwargs):
        """Inputs: rename target. Output: injected trust-write error or real rename."""
        if target == "ca.pem":
            raise OSError("simulated disk failure")
        return replace(source, target, **kwargs)

    monkeypatch.setattr(tls.os, "replace", disk_failure)
    with pytest.raises(OSError, match="simulated disk failure"):
        tls.reconcile(*installation, now=first + timedelta(days=3651))
    assert (trust / "ca.pem").read_bytes() == before
    assert not list(trust.glob(".certificate-*"))
    monkeypatch.setattr(tls.os, "replace", replace)
    tls.reconcile(*installation, now=first + timedelta(days=3651))
    assert (trust / "ca.pem").read_bytes() != before


@pytest.mark.parametrize(
    "names",
    [
        ("../escape",),
        ("https://metrics",),
        ("*.example.test",),
        ("a..example",),
        ("a" * 64,),
        ("metrics", "metrics"),
        (),
    ],
)
def test_invalid_names_fail_before_filesystem_access(names):
    """Inputs: invalid SANs. Output: rejection before filesystem access."""
    with pytest.raises(ValueError):
        tls.Identity("service", names, os.getuid(), os.getgid())


@pytest.mark.parametrize("name", ["..", "../escape", "/outside", "x/y", "", "x" * 64])
def test_invalid_identity_path(name):
    """Inputs: unsafe identity paths. Output: validation failure without traversal."""
    with pytest.raises(ValueError):
        tls.Identity(name, ("metrics",), os.getuid(), os.getgid())


@pytest.mark.parametrize("uid", [-1, True, 2**32 - 1, "1"])
def test_invalid_runtime_ownership(uid):
    """Inputs: invalid ownership IDs. Output: rejection before file creation."""
    with pytest.raises(ValueError):
        tls.Identity("service", ("metrics",), uid, os.getgid())


def tls_handshake(leaf_dir, ca_file, hostname):
    """Inputs: leaf, CA and hostname. Output: verified loopback TLS or SSL error."""
    server = ssl.SSLContext(
        ssl.PROTOCOL_TLS_SERVER,  # DevSkim: ignore DS440072 -- negotiating server context
    )
    server.minimum_version = (
        ssl.TLSVersion.TLSv1_2  # DevSkim: ignore DS440001 -- minimum, not fixed protocol
    )
    server.load_cert_chain(leaf_dir / "cert.pem", leaf_dir / "key.pem")
    client = ssl.create_default_context(cafile=str(ca_file))
    client.minimum_version = (
        ssl.TLSVersion.TLSv1_2  # DevSkim: ignore DS440001 -- minimum, not maximum
    )
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            """Inputs: local TLS peer. Output: authenticated response or retained SSL error."""
            try:
                connection, _ = listener.accept()
                with (
                    connection,
                    server.wrap_socket(connection, server_side=True) as secured,
                ):
                    secured.sendall(b"verified")
            except ssl.SSLError as exc:
                errors.append(type(exc).__name__)

        worker = threading.Thread(target=serve)
        worker.start()
        try:
            with socket.create_connection(
                listener.getsockname(), timeout=5
            ) as connection:
                with client.wrap_socket(
                    connection, server_hostname=hostname
                ) as secured:
                    assert secured.recv(8) == b"verified"
        finally:
            worker.join(timeout=6)
            assert not worker.is_alive()
    return errors


@pytest.mark.parametrize(
    "hostname", ["metrics", "metrics.example.test", "localhost", "127.0.0.1", "::1"]
)
def test_real_tls_accepts_declared_domain_localhost_and_ip_sans(installation, hostname):
    """Inputs: DNS/IP SANs. Output: successful real TLS hostname verification."""
    _, trust, targets, _ = installation
    tls.reconcile(*installation)
    assert tls_handshake(targets / "monitoring", trust / "ca.pem", hostname) == []


def test_real_tls_rejects_wrong_name_untrusted_ca_and_expired_certificate(
    installation, tmp_path
):
    """Inputs: wrong name, CA and expiry. Output: TLS failures, then valid recovery."""
    _, trust, targets, _ = installation
    tls.reconcile(*installation)
    with pytest.raises(ssl.SSLCertVerificationError, match="Hostname mismatch"):
        tls_handshake(targets / "monitoring", trust / "ca.pem", "another.example.test")
    other_key = ec.generate_private_key(ec.SECP256R1())
    original = certificate(trust / "ca.pem")
    now = datetime.now(UTC)
    untrusted = tls.issue(
        other_key,
        other_key,
        subject=original.subject,
        issuer=original.subject,
        names=(),
        start=now - timedelta(minutes=1),
        end=now + timedelta(days=10),
        authority=True,
    )
    other = tmp_path / "different-ca.pem"
    other.write_bytes(untrusted.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(ssl.SSLCertVerificationError):
        tls_handshake(targets / "monitoring", other, "metrics")
    leaf_dir = targets / "monitoring"
    with tls.directory(leaf_dir) as descriptor:
        key = tls.private_key(
            descriptor, uid=os.getuid(), gid=os.getgid(), may_create=False
        )
    with tls.directory(installation[0]) as descriptor:
        ca_key = tls.private_key(
            descriptor, uid=os.getuid(), gid=os.getgid(), may_create=False
        )
    expired = tls.issue(
        key,
        ca_key,
        subject=x509.Name([]),
        issuer=original.subject,
        names=("metrics",),
        start=now - timedelta(days=2),
        end=now - timedelta(days=1),
        authority=False,
    )
    with tls.directory(leaf_dir) as descriptor:
        tls.publish(
            descriptor,
            "cert.pem",
            expired.public_bytes(serialization.Encoding.PEM),
            mode=0o444,
            uid=os.getuid(),
            gid=os.getgid(),
        )
    with pytest.raises(ssl.SSLCertVerificationError, match="expired"):
        tls_handshake(leaf_dir, trust / "ca.pem", "metrics")
    tls.reconcile(*installation)
    assert tls_handshake(leaf_dir, trust / "ca.pem", "metrics") == []


def test_openssl_strict_server_certificate_verification(installation):
    """Inputs: issued certificate. Output: successful strict OpenSSL verification."""
    import shutil

    executable = shutil.which("openssl")
    assert executable is not None
    _, trust, targets, _ = installation
    tls.reconcile(*installation)
    result = subprocess.run(
        [
            executable,
            "verify",
            "-x509_strict",
            "-purpose",
            "sslserver",
            "-verify_hostname",
            "metrics",
            "-CAfile",
            str(trust / "ca.pem"),
            str(targets / "monitoring/cert.pem"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_authority_cannot_validate_names_outside_installation_contract(installation):
    """Inputs: out-of-scope signed leaf. Output: TLS name-constraint rejection."""
    state, trust, targets, _ = installation
    tls.reconcile(*installation)
    ca = certificate(trust / "ca.pem")
    with tls.directory(state) as descriptor:
        ca_key = tls.load_private_key(tls.read_file(descriptor, "key.pem"))
    with tls.directory(targets / "monitoring") as descriptor:
        key = tls.load_private_key(tls.read_file(descriptor, "key.pem"))
        now = datetime.now(UTC)
        outside = tls.issue(
            key,
            ca_key,
            subject=x509.Name([]),
            issuer=ca.subject,
            names=("outside.example.invalid",),
            start=now - timedelta(minutes=1),
            end=now + timedelta(days=1),
            authority=False,
        )
        tls.publish(
            descriptor,
            "cert.pem",
            outside.public_bytes(serialization.Encoding.PEM),
            mode=0o444,
            uid=os.getuid(),
            gid=os.getgid(),
        )
    with pytest.raises(ssl.SSLCertVerificationError, match="subtree violation"):
        tls_handshake(
            targets / "monitoring", trust / "ca.pem", "outside.example.invalid"
        )
