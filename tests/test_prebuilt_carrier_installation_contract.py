"""Contract tests for the strict prebuilt carrier installation workflow."""

from __future__ import annotations

from iter_test_helpers import next_or_fail

import gzip
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from tools import prebuilt_release_metadata
from tools import write_prebuilt_runtime_archive


class PrebuiltCarrierInstallationContractTests(unittest.TestCase):
    """Verify easy installation and release carrier wiring."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared repository paths for prebuilt carrier checks.

        Inputs: unittest supplies the class. Output: class-level repo root.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        """Read a repository text fixture.

        Inputs: `relative_path`. Output: decoded fixture text.
        """
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_compose_custom_images_are_environment_driven_with_existing_defaults(
        self,
    ) -> None:
        """Verify custom Compose images remain environment-driven.

        Inputs: repository Compose fixture. Output: asserts image references.
        """
        compose = yaml.safe_load(self.read_text("docker-compose.yml"))
        services = compose["services"]
        expected_images = {
            "path-usage-exporter": "${PATH_USAGE_EXPORTER_IMAGE:-path-usage-exporter:custom}",
            "omeroserver": "${OMERO_SERVER_IMAGE:-omeroserver:custom}",
            "redis-sysctl-init": "${REDIS_SYSCTL_INIT_IMAGE:-redis-sysctl-init:custom}",
            "omeroweb": "${OMERO_WEB_IMAGE:-omeroweb:custom}",
            "pg-maintenance": "${PG_MAINTENANCE_IMAGE:-pg-maintenance:custom}",
            "crowdsec": "${CROWDSEC_IMAGE:-crowdsec:custom}",
        }

        for service_name, image_ref in expected_images.items():
            with self.subTest(service_name=service_name):
                self.assertEqual(image_ref, services[service_name]["image"])

    def test_easy_install_script_only_enables_required_prebuilt_mode(self) -> None:
        """Verify the easy installer only selects strict prebuilt mode.

        Inputs: easy install script fixture. Output: asserts no build commands.
        """
        script = self.read_text("installation/easy_installation_script.sh")

        self.assertIn("prompt_release_version()", script)
        self.assertIn("Which prebuilt release version should be installed?", script)
        self.assertIn("PREBUILT_IMAGE_RELEASE is required", script)
        self.assertIn("tools/prebuilt_release_metadata.py", script)
        self.assertIn("--validate-release-version", script)
        self.assertIn('export PREBUILT_IMAGE_MODE="require"', script)
        self.assertIn('exec "${SCRIPT_DIR}/installation_script.sh" "$@"', script)
        self.assertNotIn("docker compose build", script)
        self.assertNotIn("docker build", script)

    def test_installer_strict_prebuilt_mode_skips_only_build_prompts(self) -> None:
        """Verify strict prebuilt mode skips only build-image prompts.

        Inputs: canonical installer fixture. Output: asserts prompt and build wiring.
        """
        script = self.read_text("installation/installation_script.sh")

        self.assertIn('PREBUILT_IMAGE_MODE="${PREBUILT_IMAGE_MODE:-disabled}"', script)
        self.assertIn('case "${PREBUILT_IMAGE_MODE}" in', script)
        self.assertIn('PREBUILT_IMAGE_MODE}" = "require"', script)
        self.assertIn("run_prebuilt_image_load()", script)
        self.assertIn("run_prebuilt_image_load\n        return $?", script)
        self.assertIn("USE_BUILDX_COMPRESSED_BUILD=0", script)
        self.assertIn("DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1", script)
        self.assertIn("APPLY_SECURITY_HARDENING=1", script)
        self.assertIn("compose_up_args+=(--no-build)", script)

        prompt_start = script.index("if ! validate_prebuilt_image_mode; then")
        self.assertIn('if [ "${PREBUILT_IMAGE_MODE}" != "require" ]; then', script)
        self.assertLess(
            script.index(
                "PREBUILT_IMAGE_MODE=require: using release-built images", prompt_start
            ),
            script.index("if ! resolve_cache_build_choice", prompt_start),
        )
        self.assertLess(
            script.index(
                'if [ "${PREBUILT_IMAGE_MODE}" != "require" ]; then', prompt_start
            ),
            script.index("resolve_flatten_final_image_choice", prompt_start),
        )

    def test_prebuilt_loader_validates_manifest_checksum_and_loaded_images(
        self,
    ) -> None:
        """Verify carrier loading validates bundle integrity before use.

        Inputs: carrier loader fixture. Output: asserts pull, checksum, load, inspect.
        """
        loader = self.read_text("installation/load_prebuilt_carrier.sh")

        self.assertIn('docker pull "${carrier_ref}"', loader)
        self.assertIn(
            'docker cp "${container_name}:${MANIFEST_CONTAINER_PATH}"', loader
        )
        self.assertIn('docker cp "${container_name}:${BUNDLE_CONTAINER_PATH}"', loader)
        self.assertIn("runtime_images_archive", loader)
        self.assertIn("image_archive_sha256", loader)
        self.assertIn("runtime_images_uncompressed_bytes", loader)
        self.assertIn("docker info -f '{{.DockerRootDir}}'", loader)
        self.assertIn("hashlib.sha256()", loader)
        self.assertIn('docker load -i "${bundle_path}"', loader)
        self.assertIn('docker image inspect "${image_ref}"', loader)
        self.assertRegex(loader, r"latest\|\*:latest\|\*:latest@\*")
        self.assertNotIn("docker compose build", loader)
        self.assertNotIn("docker build", loader)

    def test_release_workflow_is_manual_semver_and_single_carrier_image(self) -> None:
        """Verify release workflow dispatch and version contracts.

        Inputs: release workflow fixture. Output: asserts manual release metadata.
        """
        workflow_text = self.read_text(".github/workflows/release-prebuilt-carrier.yml")
        workflow = yaml.safe_load(workflow_text)
        triggers = workflow[True]

        self.assertEqual(["workflow_dispatch"], list(triggers))
        release_job = workflow["jobs"]["release"]
        self.assertEqual(
            "github.ref_name == github.event.repository.default_branch",
            release_job["if"],
        )
        self.assertEqual("dockerhub-release", release_job["environment"])
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("write", release_job["permissions"]["contents"])
        self.assertEqual("${{ inputs.runner_label }}", release_job["runs-on"])
        self.assertEqual(
            "ubuntu-latest",
            triggers["workflow_dispatch"]["inputs"]["runner_label"]["default"],
        )

        steps = release_job["steps"]
        checkout_step = next_or_fail(
            step for step in steps if step["name"] == "Checkout"
        )
        self.assertEqual(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            checkout_step["uses"],
        )
        self.assertEqual(0, checkout_step["with"]["fetch-depth"])
        self.assertFalse(checkout_step["with"]["persist-credentials"])

        self.assertIn("tools/prebuilt_release_metadata.py", workflow_text)
        self.assertIn("--requested-version", workflow_text)
        self.assertIn("--requested-docker-repository", workflow_text)
        self.assertIn("--latest=false", workflow_text)

    def test_release_workflow_builds_hardened_flattened_bundle_from_compose(
        self,
    ) -> None:
        """Verify carrier bundle is hardened, flattened, and Compose-derived.

        Inputs: release workflow fixture. Output: asserts bundle build behavior.
        """
        workflow_text = self.read_text(".github/workflows/release-prebuilt-carrier.yml")

        self.assertIn("git archive", workflow_text)
        self.assertIn("installation/docker_buildx_compressed_push.sh", workflow_text)
        self.assertIn('DOCKER_BUILD_INLINE_CACHE="1"', workflow_text)
        self.assertIn('DOCKER_BUILD_FLATTEN_FINAL_IMAGE="1"', workflow_text)
        self.assertIn('APPLY_SECURITY_HARDENING="1"', workflow_text)
        self.assertNotIn("DOCKER_BUILD_TARGETS=", workflow_text)
        self.assertIn(
            "docker compose -f docker-compose.yml config --images", workflow_text
        )
        self.assertIn('docker save "${compose_images[@]}"', workflow_text)
        self.assertIn("tools/write_prebuilt_runtime_archive.py", workflow_text)
        self.assertIn("image_archive_sha256", workflow_text)
        self.assertIn("runtime_images_uncompressed_bytes", workflow_text)
        self.assertIn("df -h /", workflow_text)
        self.assertIn("docker system df", workflow_text)
        self.assertIn("docker buildx build", workflow_text)
        self.assertIn("-f docker/prebuilt-carrier.Dockerfile", workflow_text)
        self.assertIn('-t "${CARRIER_IMAGE}"', workflow_text)
        self.assertIn("docker run --rm", workflow_text)
        self.assertIn("gh release create", workflow_text)

    def test_release_metadata_helper_generates_professional_beta_versions(self) -> None:
        """Verify release helper keeps GitHub and Docker tags aligned.

        Inputs: synthetic tag sets. Output: asserts SemVer beta and rejection logic.
        """
        self.assertEqual(
            "0.1.0-beta.1",
            prebuilt_release_metadata.next_beta_release_version(()),
        )
        self.assertEqual(
            "0.9.0-beta.2",
            prebuilt_release_metadata.next_beta_release_version(
                ("not-a-release", "0.8.0", "0.9.0-beta.1")
            ),
        )
        self.assertEqual(
            "1.2.4-beta.1",
            prebuilt_release_metadata.next_beta_release_version(("1.2.3",)),
        )
        self.assertEqual(
            (
                "0.9.0-beta.1",
                "strmt7/omero-docker-extended",
                "strmt7/omero-docker-extended:0.9.0-beta.1",
            ),
            prebuilt_release_metadata.resolve_release_metadata(
                requested_version="0.9.0-beta.1",
                requested_docker_repository="",
                default_docker_repository="strmt7/omero-docker-extended",
                existing_tags=("0.8.0",),
            ),
        )
        for bad_value in ("latest", "v0.9.0-beta.1", "0.9.0+build.1", "0.9"):
            with self.subTest(bad_value=bad_value):
                self.assertFalse(
                    prebuilt_release_metadata.is_valid_release_version(bad_value)
                )
                self.assertEqual(
                    1,
                    prebuilt_release_metadata.main(
                        ["--validate-release-version", bad_value]
                    ),
                )
        self.assertEqual(
            0,
            prebuilt_release_metadata.main(
                ["--validate-release-version", "0.9.0-beta.1"]
            ),
        )

    def test_archive_writer_creates_deterministic_gzip_and_raw_byte_count(
        self,
    ) -> None:
        """Verify release archive helper compresses streams without temp tars.

        Inputs: synthetic binary stream. Output: asserts archive and byte count.
        """
        payload = b"synthetic docker save stream" * 1024
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "runtime-images.tar.gz"
            bytes_path = temp_path / "runtime-images-uncompressed.bytes"

            raw_bytes = write_prebuilt_runtime_archive.write_archive(
                input_stream=io.BytesIO(payload),
                archive_path=archive_path,
                raw_bytes_path=bytes_path,
            )

            self.assertEqual(len(payload), raw_bytes)
            self.assertEqual(f"{len(payload)}\n", bytes_path.read_text())
            self.assertEqual(payload, gzip.decompress(archive_path.read_bytes()))

    def test_prebuilt_carrier_image_declares_non_root_healthcheck(self) -> None:
        """Verify carrier image security metadata is explicit.

        Inputs: carrier Dockerfile fixture. Output: asserts non-root healthcheck.
        """
        dockerfile = self.read_text("docker/prebuilt-carrier.Dockerfile")

        self.assertIn("USER carrier", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("test -r /omero-prebuilt/prebuilt-manifest.json", dockerfile)
        self.assertIn("test -r /omero-prebuilt/runtime-images.tar.gz", dockerfile)

    def test_new_prebuilt_files_do_not_contain_build_substitution_wording(self) -> None:
        """Verify prebuilt files do not describe local build substitution.

        Inputs: prebuilt workflow fixtures. Output: asserts forbidden wording absent.
        """
        for relative_path in (
            ".github/workflows/release-prebuilt-carrier.yml",
            "installation/easy_installation_script.sh",
            "installation/load_prebuilt_carrier.sh",
            "docker/prebuilt-carrier.Dockerfile",
        ):
            with self.subTest(relative_path=relative_path):
                lowered = self.read_text(relative_path).lower()
                self.assertNotIn("docker compose build", lowered)


if __name__ == "__main__":
    unittest.main()
