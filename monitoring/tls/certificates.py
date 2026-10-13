"""Offline certificate reconciliation for a single Compose installation.

Only the issuer mounts the private authority directory. Consumers mount the
public trust directory and, for servers, their own leaf directory read-only.
Normal renewal preserves keys so concurrent native certificate reloads cannot
observe a new certificate paired with an old private key.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

MAX_MANAGED_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Lifetime:
    """Validity and early-renewal windows, independent of the host clock source."""

    ca: timedelta = timedelta(days=3650)
    ca_renew_before: timedelta = timedelta(days=365)
    leaf: timedelta = timedelta(days=30)
    leaf_renew_before: timedelta = timedelta(days=10)
    backdate: timedelta = timedelta(minutes=5)

    def __post_init__(self):
        """Inputs: renewal windows. Output: ValueError for an unsafe lifetime policy."""
        if not (
            timedelta(0)
            < self.leaf_renew_before
            < self.leaf
            < self.ca_renew_before
            < self.ca
            and timedelta(0) <= self.backdate < self.leaf_renew_before
        ):
            raise ValueError("Invalid certificate renewal windows")


@dataclass(frozen=True)
class Identity:
    """Service identity and image-runtime ownership, never host account IDs."""

    name: str
    names: tuple[str, ...]
    uid: int
    gid: int

    def __post_init__(self):
        """Inputs: service names and IDs. Output: validation before filesystem writes."""
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", self.name):
            raise ValueError("Invalid certificate identity")
        if any(
            type(value) is not int or not 0 <= value < 2**32 - 1
            for value in (self.uid, self.gid)
        ):
            raise ValueError("Invalid certificate file ownership")
        if (
            not self.names
            or len(self.names) > 32
            or len(set(self.names)) != len(self.names)
        ):
            raise ValueError("Certificate names must be unique and nonempty")
        for name in self.names:
            subject_name(name)


def subject_name(value: str) -> x509.GeneralName:
    """Inputs: explicit DNS/IP identity. Output: SAN, rejecting URLs and wildcards."""
    try:
        return x509.IPAddress(ipaddress.ip_address(value))
    except ValueError:
        if len(value) > 253 or not re.fullmatch(
            r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*",
            value,
        ):
            raise ValueError("Invalid DNS certificate name") from None
        return x509.DNSName(value)


@contextmanager
def directory(path: Path | str, *, parent_fd: int | None = None) -> Iterator[int]:
    """Inputs: directory path. Output: verified descriptor, closed on exit."""
    descriptor = os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
    )
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
            raise ValueError(
                "Certificate directory has unsafe ownership or permissions"
            )
        yield descriptor
    finally:
        os.close(descriptor)


def read_file(directory_fd: int, name: str) -> bytes | None:
    """Inputs: directory FD and name. Output: bounded bytes or None; links rejected."""
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
        )
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > MAX_MANAGED_BYTES
        ):
            raise ValueError("Invalid managed certificate file")
        data = handle.read(MAX_MANAGED_BYTES + 1)
        if len(data) > MAX_MANAGED_BYTES:
            raise ValueError("Managed certificate file exceeds limit")
        return data


def publish(
    directory_fd: int, name: str, data: bytes, *, mode: int, uid: int, gid: int
) -> None:
    """Inputs: bytes and ownership. Output: durable atomic file, unchanged bytes kept."""
    existing = read_file(directory_fd, name)
    if existing == data:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (stat.S_IMODE(metadata.st_mode), metadata.st_uid, metadata.st_gid) == (
            mode,
            uid,
            gid,
        ):
            return
    temporary = ".certificate-" + secrets.token_hex(16)
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchown(handle.fileno(), uid, gid)
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            # A successful atomic replace already consumed this temporary file.
            temporary = ""


def private_key(
    directory_fd: int, *, uid: int, gid: int, may_create: bool
) -> ec.EllipticCurvePrivateKey:
    """Inputs: directory and creation policy. Output: preserved or newly created key."""
    raw = read_file(directory_fd, "key.pem")
    if raw is None:
        if not may_create:
            raise ValueError("Existing certificate authority or service key is missing")
        key = ec.generate_private_key(ec.SECP256R1())
        raw = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    else:
        key = load_private_key(raw)
    publish(directory_fd, "key.pem", raw, mode=0o600, uid=uid, gid=gid)
    return key


def load_private_key(raw: bytes) -> ec.EllipticCurvePrivateKey:
    """Inputs: private PEM bytes. Output: validated key without writes or disclosure."""
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise ValueError("Unexpected internal certificate key type")
    return key


def issue(
    key: ec.EllipticCurvePrivateKey,
    ca_key: ec.EllipticCurvePrivateKey,
    *,
    subject: x509.Name,
    issuer: x509.Name,
    names: tuple[str, ...],
    start: datetime,
    end: datetime,
    authority: bool,
    constraints: x509.NameConstraints | None = None,
) -> x509.Certificate:
    """Inputs: keys, names and validity. Output: signed, constrained X.509 certificate."""
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(end)
        .add_extension(
            x509.BasicConstraints(ca=authority, path_length=0 if authority else None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=not authority,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=authority,
                crl_sign=authority,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
    )
    if constraints is not None:
        builder = builder.add_extension(constraints, critical=True)
    if not authority:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([subject_name(name) for name in names]),
            critical=not subject,
        ).add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    return builder.sign(ca_key, hashes.SHA256())


def existing_certificate(
    directory_fd: int,
    key: ec.EllipticCurvePrivateKey,
    ca_key: ec.EllipticCurvePrivateKey,
) -> x509.Certificate | None:
    """Inputs: directory and keys. Output: authenticated matching certificate or None."""
    raw = read_file(directory_fd, "cert.pem")
    if raw is None:
        return None
    certificate = x509.load_pem_x509_certificate(raw)
    if certificate.public_key() != key.public_key():
        raise ValueError("Certificate and private key do not match")
    parameters = certificate.signature_algorithm_parameters
    if not isinstance(parameters, ec.ECDSA):
        raise ValueError("Unexpected internal certificate signature algorithm")
    ca_key.public_key().verify(
        certificate.signature,
        certificate.tbs_certificate_bytes,
        parameters,
    )
    return certificate


def requires_renewal(
    certificate: x509.Certificate | None, now: datetime, renew_before: timedelta
) -> bool:
    """Inputs: certificate and clock. Output: whether early renewal is required."""
    return (
        certificate is None
        or now < certificate.not_valid_before_utc
        or certificate.not_valid_after_utc <= now + renew_before
    )


def reconcile(
    state: Path,
    trust: Path,
    targets: Path,
    identities: tuple[Identity, ...],
    *,
    now: datetime | None = None,
    policy: Lifetime = Lifetime(),
    system_trust: bytes = b"",
) -> dict[str, int]:
    """Reconcile private state and public material without touching application data.

    The caller supplies existing, dedicated volume directories. A missing CA key
    beside existing material is an error, not permission to reset installation
    trust. Root certificates renew with the same authority key; consumers must
    reload their trust files when the certificate changes.

    Inputs: dedicated directories, identities and clock. Output: per-service expiry
    timestamps after durable publication; invalid state raises without resetting keys.
    """
    now = now or datetime.now(UTC)
    if system_trust:
        if len(system_trust) > MAX_MANAGED_BYTES - 4096:
            raise ValueError("System certificate bundle exceeds limit")
        x509.load_pem_x509_certificates(system_trust)
    if (
        now.tzinfo is None
        or not identities
        or len({x.name for x in identities}) != len(identities)
    ):
        raise ValueError("Require aware time and unique nonempty service identities")
    with (
        directory(state) as state_fd,
        directory(trust) as trust_fd,
        directory(targets) as targets_fd,
    ):
        lock_fd = os.open(
            "issuer.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
            dir_fd=state_fd,
        )
        try:
            if (
                not stat.S_ISREG(os.fstat(lock_fd).st_mode)
                or os.fstat(lock_fd).st_nlink != 1
            ):
                raise ValueError("Invalid certificate issuer lock")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fresh = (
                read_file(state_fd, "cert.pem") is None
                and read_file(trust_fd, "ca.pem") is None
            )
            if fresh:
                for identity in identities:
                    with directory(identity.name, parent_fd=targets_fd) as leaf_fd:
                        if (
                            read_file(leaf_fd, "cert.pem") is not None
                            or read_file(leaf_fd, "key.pem") is not None
                        ):
                            fresh = False
            ca_key = private_key(
                state_fd, uid=os.geteuid(), gid=os.getegid(), may_create=fresh
            )
            ca = existing_certificate(state_fd, ca_key, ca_key)
            allowed = []
            for value in sorted(
                {name for identity in identities for name in identity.names}
            ):
                general_name = subject_name(value)
                if isinstance(general_name, x509.IPAddress):
                    general_name = x509.IPAddress(
                        ipaddress.ip_network(str(general_name.value))
                    )
                allowed.append(general_name)
            constraints = x509.NameConstraints(
                permitted_subtrees=allowed, excluded_subtrees=None
            )
            if ca is not None:
                ca.verify_directly_issued_by(ca)
                if ca.extensions.get_extension_for_class(
                    x509.BasicConstraints
                ).value != x509.BasicConstraints(True, 0):
                    raise ValueError("Invalid internal authority constraints")
            if (
                ca is None
                or requires_renewal(ca, now, policy.ca_renew_before)
                or (
                    ca is not None
                    and ca.extensions.get_extension_for_class(
                        x509.NameConstraints
                    ).value
                    != constraints
                )
            ):
                name = x509.Name(
                    [
                        x509.NameAttribute(
                            NameOID.COMMON_NAME, "OMERO internal authority"
                        )
                    ]
                )
                ca = issue(
                    ca_key,
                    ca_key,
                    subject=name,
                    issuer=name,
                    names=(),
                    start=now - policy.backdate,
                    end=now + policy.ca,
                    authority=True,
                    constraints=constraints,
                )
                publish(
                    state_fd,
                    "cert.pem",
                    ca.public_bytes(serialization.Encoding.PEM),
                    mode=0o600,
                    uid=os.geteuid(),
                    gid=os.getegid(),
                )
            ca_bytes = ca.public_bytes(serialization.Encoding.PEM)
            publish(
                trust_fd,
                "ca.pem",
                ca_bytes,
                mode=0o444,
                uid=os.geteuid(),
                gid=os.getegid(),
            )
            publish(
                trust_fd,
                "ca-bundle.pem",
                system_trust.rstrip() + b"\n" + ca_bytes,
                mode=0o444,
                uid=os.geteuid(),
                gid=os.getegid(),
            )
            expiries = {"authority": int(ca.not_valid_after_utc.timestamp())}
            for identity in identities:
                with directory(identity.name, parent_fd=targets_fd) as leaf_fd:
                    key = private_key(
                        leaf_fd,
                        uid=identity.uid,
                        gid=identity.gid,
                        may_create=read_file(leaf_fd, "cert.pem") is None,
                    )
                    leaf = existing_certificate(leaf_fd, key, ca_key)
                    wanted = x509.SubjectAlternativeName(
                        [subject_name(name) for name in identity.names]
                    )
                    if (
                        leaf is None
                        or requires_renewal(leaf, now, policy.leaf_renew_before)
                        or (
                            leaf is not None
                            and leaf.extensions.get_extension_for_class(
                                x509.SubjectAlternativeName
                            ).value
                            != wanted
                        )
                    ):
                        leaf = issue(
                            key,
                            ca_key,
                            subject=x509.Name([]),
                            issuer=ca.subject,
                            names=identity.names,
                            start=now - policy.backdate,
                            end=now + policy.leaf,
                            authority=False,
                        )
                        publish(
                            leaf_fd,
                            "cert.pem",
                            leaf.public_bytes(serialization.Encoding.PEM),
                            mode=0o444,
                            uid=os.geteuid(),
                            gid=os.getegid(),
                        )
                    expiries[identity.name] = int(leaf.not_valid_after_utc.timestamp())
            publish(
                trust_fd,
                "status.json",
                (
                    json.dumps(
                        {"checked_at": int(now.timestamp()), "expires_at": expiries},
                        sort_keys=True,
                    )
                    + "\n"
                ).encode(),
                mode=0o444,
                uid=os.geteuid(),
                gid=os.getegid(),
            )
            return expiries
        finally:
            os.close(lock_fd)
