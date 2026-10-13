"""Local-only certificate service: reconcile, retry and expose honest readiness."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import signal
import ssl
import threading

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm

from monitoring.tls.certificates import (
    Identity,
    directory,
    load_private_key,
    read_file,
    reconcile,
    subject_name,
)


LOGGER = logging.getLogger("internal-tls")
INTERVAL_SECONDS = 300
CERTIFICATE_ERRORS = (
    OSError,
    ValueError,
    InvalidSignature,
    UnsupportedAlgorithm,
    x509.ExtensionNotFound,
)


def load_identities(path: Path) -> tuple[Identity, ...]:
    """Inputs: configuration path. Output: bounded, validated service identities."""
    with path.open("rb") as handle:
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise ValueError("Certificate identity configuration exceeds limit")
    data = json.loads(raw)
    if not isinstance(data, list) or not 1 <= len(data) <= 32:
        raise ValueError("Expected a nonempty certificate identity list")
    identities = []
    for row in data:
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "names", "uid", "gid"}
            or not isinstance(row["names"], list)
            or any(not isinstance(value, str) for value in row["names"])
        ):
            raise ValueError("Invalid certificate identity configuration")
        identities.append(
            Identity(row["name"], tuple(row["names"]), row["uid"], row["gid"])
        )
    if len({identity.name for identity in identities}) != len(identities):
        raise ValueError("Duplicate certificate identity")
    return tuple(identities)


def validate_volumes(root: Path, identities: tuple[Identity, ...]) -> None:
    """Inputs: PKI root and identities. Output: rejection of missing persistent mounts."""
    paths = [
        root / "private",
        root / "trust",
        *(root / "servers" / identity.name for identity in identities),
    ]
    for path in paths:
        with directory(path):
            if not os.path.ismount(path):
                raise ValueError(
                    "Every authority, trust and server directory must be a persistent mount"
                )


def healthy(
    root: Path, identities: tuple[Identity, ...], *, now: datetime | None = None
) -> bool:
    """Inputs: PKI root and clock. Output: readiness from real keys and certificates."""
    now = now or datetime.now(UTC)
    with directory(root / "trust") as descriptor:
        raw_status = read_file(descriptor, "status.json")
        raw_ca = read_file(descriptor, "ca.pem")
    if raw_status is None or raw_ca is None:
        return False
    status = json.loads(raw_status)
    age = now.timestamp() - status["checked_at"]
    if age < -300 or age > 3 * INTERVAL_SECONDS:
        return False
    ca = x509.load_pem_x509_certificate(raw_ca)
    ca.verify_directly_issued_by(ca)
    with directory(root / "private") as descriptor:
        key = read_file(descriptor, "key.pem")
    if key is None or load_private_key(key).public_key() != ca.public_key():
        return False
    certificates = {"authority": ca}
    with directory(root / "servers") as parent:
        for identity in identities:
            with directory(identity.name, parent_fd=parent) as descriptor:
                raw = read_file(descriptor, "cert.pem")
                key = read_file(descriptor, "key.pem")
            if raw is None or key is None:
                return False
            leaf = x509.load_pem_x509_certificate(raw)
            leaf.verify_directly_issued_by(ca)
            if load_private_key(key).public_key() != leaf.public_key():
                return False
            if leaf.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value != x509.SubjectAlternativeName(
                [subject_name(name) for name in identity.names]
            ):
                return False
            certificates[identity.name] = leaf
    expected = {
        name: int(cert.not_valid_after_utc.timestamp())
        for name, cert in certificates.items()
    }
    return status["expires_at"] == expected and all(
        cert.not_valid_before_utc
        <= now
        < cert.not_valid_after_utc - timedelta(seconds=INTERVAL_SECONDS)
        for cert in certificates.values()
    )


def serve(root: Path, identities: tuple[Identity, ...], stop: threading.Event) -> None:
    """Inputs: PKI root and stop event. Output: reconciled state with bounded retries."""
    while not stop.is_set():
        try:
            reconcile(
                root / "private",
                root / "trust",
                root / "servers",
                identities,
                system_trust=system_trust_bundle(),
            )
        except CERTIFICATE_ERRORS as exc:
            LOGGER.error(
                "Certificate reconciliation failed (%s); existing material retained",
                type(exc).__name__,
            )
        if stop.wait(INTERVAL_SECONDS):
            return


def system_trust_bundle() -> bytes:
    """Inputs: platform CA location. Output: bounded public trust bytes."""
    path = ssl.get_default_verify_paths().cafile
    if path is None:
        raise ValueError("System CA bundle is unavailable")
    with open(path, "rb") as handle:
        return handle.read(1024 * 1024 + 1)


def main(argv: list[str] | None = None) -> int:
    """Inputs: CLI arguments. Output: issuer/check status; errors omit private details."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("serve", "once", "check"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--identities", required=True, type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    try:
        identities = load_identities(args.identities)
        validate_volumes(args.root, identities)
        if args.operation == "check":
            return 0 if healthy(args.root, identities) else 1
        if args.operation == "once":
            reconcile(
                args.root / "private",
                args.root / "trust",
                args.root / "servers",
                identities,
                system_trust=system_trust_bundle(),
            )
            return 0
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda _signum, _frame: stop.set())
        serve(args.root, identities, stop)
        return 0
    except (*CERTIFICATE_ERRORS, KeyError, TypeError) as exc:
        LOGGER.error("Certificate service unavailable (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
