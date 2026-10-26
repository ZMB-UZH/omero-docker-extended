"""Build and exercise the TLS issuer without host data or deployment volumes."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


class TlsImageTests(unittest.TestCase):
    """Detect stale distribution pins and real certificate-runtime failures."""

    def test_build_issuance_readiness_and_idempotence(self) -> None:
        """Inputs: public recipe and private fixture mounts. Output: native lifecycle parity."""
        docker = shutil.which("docker")
        self.assertIsNotNone(docker, "A native Linux Docker engine is required")
        token = uuid.uuid4().hex
        tag = "omero-tls-test:" + token
        container = "omero-tls-test-" + token
        label = "org.openmicroscopy.test.fixture"

        def command(*args: str, timeout: int = 90) -> str:
            """Inputs: native Docker arguments. Output: checked, bounded stdout."""
            result = subprocess.run(
                [str(docker), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        def remove_owned(kind: str, reference: str) -> None:
            """Inputs: fixture identity. Output: cleanup only after ownership validation."""
            result = subprocess.run(
                [str(docker), kind, "inspect", reference],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode:
                self.assertIn("No such", result.stderr)
                return
            metadata = json.loads(result.stdout)[0]
            self.assertEqual(metadata["Config"]["Labels"].get(label), token)
            if kind == "container":
                command(kind, "rm", "--force", reference)
            else:
                command(kind, "rm", reference)

        for kind, reference in (("image", tag), ("container", container)):
            result = subprocess.run(
                [str(docker), kind, "inspect", reference],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0, "Fixture identity already exists")
            self.assertIn("No such", result.stderr)

        self.addCleanup(remove_owned, "image", tag)
        command(
            "build",
            "--provenance=false",
            "--label",
            f"{label}={token}",
            "--file",
            str(ROOT / "docker/internal-tls.Dockerfile"),
            "--tag",
            tag,
            str(ROOT),
            timeout=600,
        )
        self.addCleanup(remove_owned, "container", container)
        identities = json.loads(
            (ROOT / "monitoring/tls/identities.json").read_text(encoding="utf-8")
        )
        mounts = ["/pki/private", "/pki/trust"] + [
            "/pki/servers/" + identity["name"] for identity in identities
        ]
        arguments = [
            "run",
            "--rm",
            "--name",
            container,
            "--label",
            f"{label}={token}",
            "--network=none",
            "--read-only",
            "--user=0:0",
            "--cap-drop=ALL",
            "--cap-add=CHOWN",
            "--cap-add=DAC_OVERRIDE",
            "--cap-add=FOWNER",
        ]
        for mount in mounts:
            mode = "0700" if mount.endswith("/private") else "0755"
            arguments.extend(["--tmpfs", f"{mount}:rw,nosuid,nodev,noexec,mode={mode}"])
        probe = """
import hashlib
from pathlib import Path
from monitoring.tls.manager import load_identities, main

arguments = ["--root", "/pki", "--identities", "/etc/omero-tls/identities.json"]
assert main(["check", *arguments]) == 1, "An empty PKI must not report readiness"
assert main(["once", *arguments]) == 0
assert main(["check", *arguments]) == 0
def fingerprints():
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path("/pki").rglob("*.pem") if path.is_file()}
before = fingerprints()
identities = load_identities(Path("/etc/omero-tls/identities.json"))
assert len(before) >= 2 * len(identities) + 2, "Expected issuer and service key/certificate material"
assert main(["once", *arguments]) == 0
assert main(["check", *arguments]) == 0
assert fingerprints() == before, "Healthy keys and certificates must not be replaced"
print("Certificate issuance, readiness and idempotence passed.")
"""
        output = command(
            *arguments,
            "--entrypoint=/opt/tls/bin/python",
            tag,
            "-c",
            probe,
        )
        self.assertIn("Certificate issuance, readiness and idempotence passed.", output)


if __name__ == "__main__":
    unittest.main()
