"""Real Docker metadata round trips; no live services, registries or data mounts."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


class ImageFlatteningTests(unittest.TestCase):
    """Exercise the public flatten-only entry point using fixture-owned images."""

    def test_metadata_and_files_survive_flattening(self) -> None:
        """Inputs: adversarial metadata. Output: exact values and unexecuted triggers."""
        docker = shutil.which("docker")
        bash = shutil.which("bash")
        self.assertIsNotNone(docker, "A native Linux Docker engine is required")
        self.assertIsNotNone(bash, "Bash is required")
        tag = "omero-flatten-test:" + uuid.uuid4().hex
        images: set[str] = {tag}
        containers: list[str] = []

        def command(*args: str, binary: bool = False) -> str | bytes:
            """Inputs: Docker argv. Output: checked stdout with bounded execution."""
            result = subprocess.run(
                [str(docker), *args],
                capture_output=True,
                text=not binary,
                check=False,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        def remove_image(reference: str) -> None:
            """Inputs: fixture reference. Output: removal or a reported cleanup error."""
            result = subprocess.run(
                [str(docker), "image", "inspect", reference],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode:
                self.assertIn("No such image:", result.stderr)
                return
            command("image", "rm", reference)

        values = {
            "PLAIN": "ordinary value",
            "SPECIAL": "line one\nline two\t\"quoted\" \\ $PLAIN ${MISSING} 'single'\r\n",
            "EMPTY": "",
            "_OMERO_FLATTEN_0": "must not shadow generated arguments",
        }
        labels = {"example.multiline": values["SPECIAL"], "example.empty": ""}
        try:
            with tempfile.TemporaryDirectory(prefix="omero-flatten-test-") as name:
                context = Path(name)
                payload = b"original filesystem bytes\n"
                (context / "payload").write_bytes(payload)
                lines = ["FROM scratch", "COPY payload /payload"]
                arguments = []
                for number, (key, value) in enumerate(values.items()):
                    argument = f"FIXTURE_VALUE_{number}"
                    lines.extend([f"ARG {argument}", f'ENV {key}="${{{argument}}}"'])
                    arguments.extend(["--build-arg", f"{argument}={value}"])
                lines.extend(
                    [
                        "ARG FIXTURE_WORKDIR",
                        "WORKDIR ${FIXTURE_WORKDIR}",
                        "USER 123:456",
                        "EXPOSE 8080/tcp 8081/udp",
                        "ARG FIXTURE_VOLUME",
                        'VOLUME ["${FIXTURE_VOLUME}"]',
                        "STOPSIGNAL SIGTERM",
                        'SHELL ["/bin/sh","-c"]',
                        'ENTRYPOINT ["/entrypoint","$PLAIN"]',
                        'CMD ["argument with space"]',
                        "HEALTHCHECK --interval=5s --timeout=3s --retries=2 CMD test -f /payload",
                        "ONBUILD LABEL example.trigger=must-not-execute",
                    ]
                )
                (context / "Dockerfile").write_text("\n".join(lines) + "\n")
                arguments.extend(
                    [
                        "--build-arg",
                        "FIXTURE_WORKDIR=/work $PLAIN with space",
                        "--build-arg",
                        "FIXTURE_VOLUME=/data $PLAIN with space",
                    ]
                )
                for key, value in labels.items():
                    arguments.extend(["--label", f"{key}={value}"])
                command("build", "--provenance=false", "--tag", tag, *arguments, name)
                before = json.loads(command("image", "inspect", tag))[0]
                images.update((tag, before["Id"]))
                self.assertEqual(before["Config"]["Labels"], labels)
                for key, value in values.items():
                    self.assertIn(f"{key}={value}", before["Config"]["Env"])
                compose = context / "compose.json"
                compose.write_text(json.dumps({"services": {"app": {"image": tag}}}))
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith(
                        ("COMPOSE_", "DOCKER_BUILD", "DOCKER_REGISTRY_")
                    )
                }
                environment.update(
                    COMPOSE_FILE=str(compose),
                    DOCKER_BUILD_TARGETS="app",
                    DOCKER_BUILD_FLATTEN_ONLY="1",
                    DOCKER_BUILD_FLATTEN_FINAL_IMAGE="1",
                    DOCKER_BUILD_PUSH_IMAGES="0",
                    DOCKER_BUILD_PROVENANCE="0",
                )
                result = subprocess.run(
                    [
                        str(bash),
                        str(ROOT / "installation/docker_buildx_compressed_push.sh"),
                    ],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                after = json.loads(command("image", "inspect", tag))[0]
                images.add(after["Id"])
                expected = before["Config"].copy()
                expected["Healthcheck"] = dict(
                    expected["Healthcheck"],
                    Test=["CMD", "/bin/sh", "-c", "test -f /payload"],
                )
                for key in (
                    "Env",
                    "Labels",
                    "WorkingDir",
                    "User",
                    "ExposedPorts",
                    "Volumes",
                    "StopSignal",
                    "Shell",
                    "Entrypoint",
                    "Cmd",
                    "Healthcheck",
                    "OnBuild",
                ):
                    self.assertEqual(after["Config"].get(key), expected.get(key), key)
                identifier = command("create", "--network=none", tag).strip()
                containers.append(identifier)
                with tarfile.open(
                    fileobj=io.BytesIO(command("export", identifier, binary=True))
                ) as archive:
                    with archive.extractfile("payload") as member:
                        self.assertEqual(member.read(), payload)
        finally:
            # unittest runs every cleanup even if another fails, preserving the
            # original assertion. LIFO removes containers, then tags, then IDs.
            for reference in sorted(images):
                if reference != tag:
                    self.addCleanup(remove_image, reference)
            self.addCleanup(remove_image, tag)
            for identifier in containers:
                self.addCleanup(command, "rm", "--volumes", identifier)


if __name__ == "__main__":
    unittest.main()
