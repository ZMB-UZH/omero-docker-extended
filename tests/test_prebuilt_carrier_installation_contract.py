"""Contract tests for the strict prebuilt carrier installation workflow."""

from __future__ import annotations

from iter_test_helpers import next_or_fail

import ast
import gzip
import io
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tools import prebuilt_release_metadata
from tools import prune_non_required_docker_images
from tools import write_prebuilt_runtime_archive


VALID_RELEASE_VERSION = "1.0.0-main.1"
VALID_CARRIER_DIGEST = "sha256:" + ("a" * 64)


def valid_changelog(version: str = VALID_RELEASE_VERSION) -> str:
    """Return canonical notes. Inputs: release version. Output: Markdown text."""
    return f"""# Changelog

## [{version}] - 2026-07-18

This release provides a clear summary for operators and users before upgrade.

### Added

- Improves the primary workflow with a documented compatible implementation.

### Changed

- Aligns the supported runtime behavior with its documented public contract.

### Verification

- Exercises unit, integration, deployment, and release artifact contracts.

### Upgrade Notes

- Preserves configured data paths and documents the required upgrade action.

[{version}]: https://github.com/example/project/compare/0.9.0-main.1...{version}
"""


class PrebuiltCarrierInstallationContractTests(unittest.TestCase):
    """Verify easy installation and release carrier wiring."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared repository paths for prebuilt carrier checks.

        Inputs: unittest supplies the class. Output: class-level repo root.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        bash_path = shutil.which("bash")
        if bash_path is None:
            raise RuntimeError("bash is required for easy-installer contract tests")
        cls.bash_path = bash_path

    def read_text(self, relative_path: str) -> str:
        """Read a repository text fixture.

        Inputs: `relative_path`. Output: decoded fixture text.
        """
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def bash_path_arg(self, path: Path) -> str:
        """Return a path argument that Git Bash can open on Windows.

        Inputs: platform path. Output: POSIX path for Windows bash, else native path.
        """
        path_text = str(path)
        if os.name != "nt":
            return path_text
        drive, rest = os.path.splitdrive(path_text)
        if not drive:
            return path_text.replace("\\", "/")
        posix_rest = rest.replace("\\", "/")
        if str(self.bash_path).lower().endswith("\\system32\\bash.exe"):
            return f"/mnt/{drive[0].lower()}{posix_rest}"
        return f"/{drive[0].lower()}{posix_rest}"

    def run_bash_script(
        self,
        script_path: Path,
        *,
        env_vars: dict[str, str] | None = None,
        stdin: object | None = None,
        no_controlling_tty: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a bash script with env assignment visible to WSL bash.

        Inputs: script path and optional variables. Output: completed process.
        """
        assignments = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in (env_vars or {}).items()
        )
        script_arg = shlex.quote(self.bash_path_arg(script_path))
        command = f"{assignments} {script_arg}" if assignments else script_arg
        if no_controlling_tty:
            command = f"setsid --wait bash -lc {shlex.quote(command)}"
        return subprocess.run(
            [self.bash_path, "-lc", command],
            cwd=self.repo_root,
            stdin=stdin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def write_synthetic_easy_root(
        self,
        root: Path,
        *,
        installer_text: str | None = None,
        loader: bool = True,
        metadata_text: str | None = None,
        env_guard: bool = True,
        compose: bool = True,
    ) -> Path:
        """Create a minimal synthetic easy-installer root.

        Inputs: root path and toggles. Output: easy-installer path.
        """
        installation = root / "installation"
        tools = root / "tools"
        installation.mkdir()
        tools.mkdir()
        easy_script = installation / "easy_installation_script.sh"
        easy_script.write_text(
            self.read_text("installation/easy_installation_script.sh"),
            encoding="utf-8",
            newline="\n",
        )
        (installation / "installation_script.sh").write_text(
            installer_text
            if installer_text is not None
            else (
                "#!/usr/bin/env bash\n"
                "# PREBUILT_IMAGE_MODE\n"
                "run_prebuilt_image_load() { :; }\n"
                "printf 'mode=%s\\n' \"${PREBUILT_IMAGE_MODE}\"\n"
                "printf 'release=%s\\n' \"${PREBUILT_IMAGE_RELEASE}\"\n"
                "printf 'digest=%s\\n' \"${PREBUILT_IMAGE_DIGEST}\"\n"
            ),
            encoding="utf-8",
            newline="\n",
        )
        if loader:
            (installation / "load_prebuilt_carrier.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
                newline="\n",
            )
        (tools / "prebuilt_release_metadata.py").write_text(
            metadata_text
            if metadata_text is not None
            else (
                "#!/usr/bin/env python3\n"
                "import re\n"
                "import sys\n"
                "ok = len(sys.argv) == 3 and sys.argv[1] == '--validate-release-version' and re.fullmatch(r'1\\.0\\.0-main\\.1', sys.argv[2])\n"
                "raise SystemExit(0 if ok else 1)\n"
            ),
            encoding="utf-8",
            newline="\n",
        )
        if env_guard:
            (tools / "env_safety_guard.py").write_text(
                "# synthetic\n", encoding="utf-8", newline="\n"
            )
        if compose:
            (root / "docker-compose.yml").write_text(
                "services: {}\n", encoding="utf-8", newline="\n"
            )
        for path in installation.iterdir():
            path.chmod(0o755)
        for path in tools.iterdir():
            path.chmod(0o755)
        return easy_script

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
        self.assertIn("prompt_carrier_digest()", script)
        self.assertIn("Which prebuilt docker image tag should be installed?", script)
        self.assertIn(
            "What is the sha256 digest for that prebuilt carrier image?", script
        )
        self.assertIn("PREBUILT_IMAGE_RELEASE is required", script)
        self.assertIn("PREBUILT_IMAGE_DIGEST is required", script)
        self.assertIn("RELEASE_METADATA_TOOL", script)
        self.assertIn("require_easy_installation_support()", script)
        self.assertIn("load_prebuilt_carrier.sh", script)
        self.assertIn("prebuilt_release_metadata.py", script)
        self.assertIn("--validate-release-version", script)
        self.assertIn("Run ./installation/github_pull_project_bash", script)
        self.assertIn('export PREBUILT_IMAGE_MODE="require"', script)
        self.assertIn('exec "${SCRIPT_DIR}/installation_script.sh" "$@"', script)
        self.assertNotIn("docker compose build", script)
        self.assertNotIn("docker build", script)

    def test_easy_install_script_rejects_stale_installation_root_before_prompt(
        self,
    ) -> None:
        """Verify a stale live root fails before mislabeling valid releases.

        Inputs: synthetic installation root. Output: asserts precise stale-root error.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            easy_script = self.write_synthetic_easy_root(
                root,
                installer_text="#!/usr/bin/env bash\necho old installer\n",
            )

            result = self.run_bash_script(
                easy_script,
                env_vars={
                    "PREBUILT_IMAGE_RELEASE": VALID_RELEASE_VERSION,
                    "PREBUILT_IMAGE_DIGEST": VALID_CARRIER_DIGEST,
                    "INSTALLATION_AUTOMATION_MODE": "1",
                },
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("too old for easy installation", result.stderr)
        self.assertIn("github_pull_project_bash", result.stderr)
        self.assertNotIn("Invalid release version", result.stderr)

    def test_easy_install_release_validation_uses_canonical_metadata_tool(self) -> None:
        """Verify valid releases use the canonical metadata validator.

        Inputs: synthetic installation root. Output: asserts exec receives strict mode.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            easy_script = self.write_synthetic_easy_root(root)

            valid_result = self.run_bash_script(
                easy_script,
                env_vars={
                    "PREBUILT_IMAGE_RELEASE": VALID_RELEASE_VERSION,
                    "PREBUILT_IMAGE_DIGEST": VALID_CARRIER_DIGEST,
                    "INSTALLATION_AUTOMATION_MODE": "1",
                },
            )
            invalid_result = self.run_bash_script(
                easy_script,
                env_vars={
                    "PREBUILT_IMAGE_RELEASE": f"v{VALID_RELEASE_VERSION}",
                    "PREBUILT_IMAGE_DIGEST": VALID_CARRIER_DIGEST,
                    "INSTALLATION_AUTOMATION_MODE": "1",
                },
            )

        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)
        self.assertIn("mode=require", valid_result.stdout)
        self.assertIn(f"release={VALID_RELEASE_VERSION}", valid_result.stdout)
        self.assertIn(f"digest={VALID_CARRIER_DIGEST}", valid_result.stdout)
        self.assertEqual(invalid_result.returncode, 1)
        self.assertIn("PREBUILT_IMAGE_RELEASE must be", invalid_result.stderr)

    def test_easy_install_support_checks_fail_before_prompt(self) -> None:
        """Verify missing support files fail before release prompting.

        Inputs: synthetic roots with one missing support file. Output: precise errors.
        """
        cases = [
            ("loader", {"loader": False}, "prebuilt carrier loader"),
            ("env_guard", {"env_guard": False}, "deployment env validator"),
            ("compose", {"compose": False}, "docker-compose.yml"),
            (
                "metadata",
                {"metadata_text": "if\n"},
                "Release metadata validator is not executable Python",
            ),
        ]
        for case_name, kwargs, expected_error in cases:
            with self.subTest(case_name=case_name):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    root = Path(tmp_dir)
                    easy_script = self.write_synthetic_easy_root(root, **kwargs)
                    result = self.run_bash_script(
                        easy_script,
                        env_vars={
                            "PREBUILT_IMAGE_RELEASE": VALID_RELEASE_VERSION,
                            "PREBUILT_IMAGE_DIGEST": VALID_CARRIER_DIGEST,
                            "INSTALLATION_AUTOMATION_MODE": "1",
                        },
                    )
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected_error, result.stderr)
                self.assertNotIn("Which prebuilt", result.stderr)

    def test_easy_install_automation_requires_release(self) -> None:
        """Verify unattended easy installs fail closed without a release tag.

        Inputs: synthetic root with automation mode. Output: release-required error.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            easy_script = self.write_synthetic_easy_root(root)
            result = self.run_bash_script(
                easy_script,
                env_vars={"INSTALLATION_AUTOMATION_MODE": "1"},
            )
            no_tty_result = self.run_bash_script(
                easy_script,
                stdin=subprocess.DEVNULL,
                no_controlling_tty=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("PREBUILT_IMAGE_RELEASE is required", result.stderr)
        self.assertNotIn("mode=require", result.stdout)
        self.assertEqual(no_tty_result.returncode, 1)
        self.assertIn("PREBUILT_IMAGE_RELEASE is required", no_tty_result.stderr)
        self.assertNotIn("No such device or address", no_tty_result.stderr)
        self.assertNotIn(
            "Could not read prebuilt docker image tag", no_tty_result.stderr
        )
        self.assertNotIn("mode=require", no_tty_result.stdout)

    def test_easy_install_automation_requires_carrier_digest(self) -> None:
        """Verify unattended easy installs fail closed without a carrier digest.

        Inputs: synthetic root with automation mode. Output: digest-required error.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            easy_script = self.write_synthetic_easy_root(root)
            result = self.run_bash_script(
                easy_script,
                env_vars={
                    "PREBUILT_IMAGE_RELEASE": VALID_RELEASE_VERSION,
                    "INSTALLATION_AUTOMATION_MODE": "1",
                },
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("PREBUILT_IMAGE_DIGEST is required", result.stderr)
        self.assertNotIn("mode=require", result.stdout)

    def test_installer_strict_prebuilt_mode_skips_only_build_prompts(self) -> None:
        """Verify strict prebuilt mode skips only build-image prompts.

        Inputs: canonical installer fixture. Output: asserts prompt and build wiring.
        """
        script = self.read_text("installation/installation_script.sh")

        self.assertIn('PREBUILT_IMAGE_MODE="${PREBUILT_IMAGE_MODE:-disabled}"', script)
        self.assertIn('PREBUILT_IMAGE_DIGEST="${PREBUILT_IMAGE_DIGEST:-}"', script)
        self.assertIn('case "${PREBUILT_IMAGE_MODE}" in', script)
        self.assertIn('PREBUILT_IMAGE_MODE}" = "require"', script)
        self.assertIn("run_prebuilt_image_load()", script)
        self.assertIn('PREBUILT_IMAGE_DIGEST="${PREBUILT_IMAGE_DIGEST}"', script)
        self.assertIn("run_prebuilt_image_load\n        return $?", script)
        self.assertIn("USE_BUILDX_COMPRESSED_BUILD=0", script)
        self.assertIn("USE_CACHE_BUILD=1", script)
        self.assertIn("DOCKER_BUILD_FLATTEN_FINAL_IMAGE=1", script)
        self.assertIn("APPLY_SECURITY_HARDENING=1", script)
        self.assertIn("compose_up_args+=(--no-build)", script)

        host_env_load = script.index(
            'if ! load_installation_paths_env "${SCRIPT_ENV_FILE}"; then'
        )
        runtime_env_load = script.index("for required_runtime_env_file in")
        prebuilt_mode_validation = script.index(
            "if ! validate_prebuilt_image_mode; then"
        )
        self.assertLess(host_env_load, prebuilt_mode_validation)
        self.assertLess(runtime_env_load, prebuilt_mode_validation)

        prompt_start = script.index("if ! validate_prebuilt_image_mode; then")
        self.assertIn('if [ "${PREBUILT_IMAGE_MODE}" != "require" ]; then', script)
        self.assertLess(
            script.index(
                "PREBUILT_IMAGE_MODE=require: using release-built images", prompt_start
            ),
            script.index(
                'if [ "${PREBUILT_IMAGE_MODE}" != "require" ]; then', prompt_start
            ),
        )
        self.assertLess(
            script.index(
                'if [ "${PREBUILT_IMAGE_MODE}" != "require" ]; then', prompt_start
            ),
            script.index("resolve_flatten_final_image_choice", prompt_start),
        )

    def test_easy_installation_prompt_count_matches_prebuilt_contract(self) -> None:
        """Verify easy installation keeps exactly eleven interactive prompts.

        Inputs: installer fixtures. Output: confirms the prebuilt prompt list size.
        """
        standard_prompts = [
            "Delete all container images?",
            "Enable Buildx compressed build workflow?",
            "Use build cache?",
            "Flatten final images into single-layer outputs?",
            "Enable docker image security hardening?",
            "Enable docker scout vulnerability scanning?",
            "Start containers after build?",
            "OMERO installation path",
            "OMERO database path",
            "OMERO plugin database path",
            "OMERO data path",
            "OMERO tmp path",
            "Enable ext4 project quotas for OMERO user data?",
        ]
        skipped_for_prebuilt = {
            "Enable Buildx compressed build workflow?",
            "Use build cache?",
            "Flatten final images into single-layer outputs?",
            "Enable docker image security hardening?",
        }
        easy_prompts = [
            "Which prebuilt docker image tag should be installed?",
            "What is the sha256 digest for that prebuilt carrier image?",
        ] + [
            prompt for prompt in standard_prompts if prompt not in skipped_for_prebuilt
        ]

        script = self.read_text("installation/installation_script.sh")
        easy_script = self.read_text("installation/easy_installation_script.sh")

        for prompt in standard_prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, script)
        self.assertIn(easy_prompts[0], easy_script)
        self.assertIn(easy_prompts[1], easy_script)
        self.assertEqual(13, len(standard_prompts))
        self.assertEqual(11, len(easy_prompts))
        self.assertNotIn("Use build cache?", easy_prompts)

    def test_prebuilt_and_standard_installers_share_runtime_flow_after_image_step(
        self,
    ) -> None:
        """Verify prebuilt mode remains interchangeable with standard installs.

        Inputs: installer fixture. Output: asserts shared env, path, and startup flow.
        """
        script = self.read_text("installation/installation_script.sh")

        required_order = [
            'if ! load_installation_paths_env "${SCRIPT_ENV_FILE}"; then',
            "for required_runtime_env_file in",
            "if ! validate_prebuilt_image_mode; then",
            'if [ "${PREBUILT_IMAGE_MODE}" = "require" ]; then',
            'OMERO_INSTALLATION_PATH="$(prompt_for_preparable_path',
            'write_installation_paths_env "${SCRIPT_ENV_FILE}"',
            "if ! run_image_build; then",
            'compose_up_with_retries "${COMPOSE_FILE}"',
        ]
        previous = -1
        for marker in required_order:
            with self.subTest(marker=marker):
                current = script.index(marker, previous + 1)
                self.assertGreater(current, previous)
                previous = current

        prebuilt_branch_start = script.index(
            'if [ "${PREBUILT_IMAGE_MODE}" = "require" ]; then'
        )
        prebuilt_branch_end = script.index(
            'echo "PREBUILT_IMAGE_MODE=require: using release-built images',
            prebuilt_branch_start,
        )
        prebuilt_prompt_window = script[prebuilt_branch_start:prebuilt_branch_end]
        self.assertNotIn("write_installation_paths_env", prebuilt_prompt_window)
        self.assertNotIn("load_installation_paths_env", prebuilt_prompt_window)
        self.assertNotIn("docker compose", prebuilt_prompt_window)

        self.assertIn("return $?", script[script.index("run_prebuilt_image_load") :])
        self.assertIn(
            'if [ "${PREBUILT_IMAGE_MODE:-disabled}" = "require" ]; then\n'
            "        compose_up_args+=(--no-build)\n"
            "    fi",
            script,
        )
        self.assertNotIn("PREBUILT_IMAGE_MODE=disabled", script)
        self.assertNotIn("unset PREBUILT_IMAGE_MODE", script)

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
        self.assertIn("stream_carrier_bundle()", loader)
        self.assertIn(
            'docker cp "${container_name}:${BUNDLE_CONTAINER_PATH}" -', loader
        )
        self.assertIn("tar -xO", loader)
        self.assertIn("runtime_images_archive", loader)
        self.assertIn("image_archive_sha256", loader)
        self.assertIn("runtime_images_uncompressed_bytes", loader)
        self.assertIn('PREBUILT_IMAGE_DIGEST="${PREBUILT_IMAGE_DIGEST:-}"', loader)
        self.assertIn('normalize_sha256_digest "PREBUILT_IMAGE_DIGEST"', loader)
        self.assertIn("printf '%s:%s@%s'", loader)
        self.assertIn('grep -F "@${expected_carrier_digest}"', loader)
        self.assertIn("docker info -f '{{.DockerRootDir}}'", loader)
        self.assertIn("hashlib.sha256()", loader)
        self.assertIn("stream_carrier_bundle | docker load", loader)
        self.assertNotIn('docker load -i "${bundle_path}"', loader)
        self.assertIn('docker image inspect "${image_ref}"', loader)
        self.assertRegex(loader, r"latest\|\*:latest\|\*:latest@\*")
        self.assertNotIn("docker compose build", loader)
        self.assertNotIn("docker build", loader)

    def test_prebuilt_loader_rejects_mutable_release_without_digest(self) -> None:
        """Verify carrier loading fails before docker pull without a digest.

        Inputs: loader script with a temporary work directory. Output: digest error.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self.run_bash_script(
                self.repo_root / "installation/load_prebuilt_carrier.sh",
                env_vars={
                    "OMERO_TMP_PATH": tmp_dir,
                    "PREBUILT_IMAGE_RELEASE": VALID_RELEASE_VERSION,
                },
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("PREBUILT_IMAGE_DIGEST cannot be empty", result.stderr)
        self.assertNotIn("Pulling prebuilt carrier image", result.stdout)

    def test_release_workflow_is_manual_semver_and_single_carrier_image(self) -> None:
        """Verify release workflow dispatch and version contracts.

        Inputs: release workflow fixture. Output: asserts manual release metadata.
        """
        workflow_text = self.read_text(".github/workflows/release-prebuilt-carrier.yml")
        environment_helper_text = self.read_text(
            "tools/prepare_ci_compose_environment.py"
        )
        workflow = yaml.safe_load(workflow_text)
        triggers = workflow[True]

        self.assertEqual(["workflow_dispatch"], list(triggers))
        release_job = workflow["jobs"]["release"]
        self.assertEqual(
            "github.ref_name == github.event.repository.default_branch",
            release_job["if"],
        )
        self.assertNotIn("environment", release_job)
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("write", release_job["permissions"]["contents"])
        self.assertEqual("ubuntu-latest", release_job["runs-on"])
        self.assertNotIn("runner_label", triggers["workflow_dispatch"]["inputs"])
        steps = release_job["steps"]
        hosted_storage_step = next_or_fail(
            step
            for step in steps
            if step["name"] == "Move docker data root to hosted-runner large disk"
        )
        self.assertEqual(
            "runner.os == 'Linux' && runner.environment == 'github-hosted'",
            hosted_storage_step["if"],
        )
        self.assertIn('target_root="/mnt/docker-data"', hosted_storage_step["run"])
        self.assertIn("sudo systemctl stop docker", hosted_storage_step["run"])
        self.assertIn("sudo systemctl start docker", hosted_storage_step["run"])
        self.assertIn("DOCKER_DATA_ROOT", hosted_storage_step["run"])
        self.assertIn("DockerRootDir", hosted_storage_step["run"])
        replace_input = triggers["workflow_dispatch"]["inputs"]["replace_existing"]
        self.assertFalse(replace_input["default"])
        self.assertEqual("boolean", replace_input["type"])
        release_input = triggers["workflow_dispatch"]["inputs"]["release_version"]
        self.assertTrue(release_input["required"])
        self.assertNotIn("default", release_input)
        public_notes_input = triggers["workflow_dispatch"]["inputs"][
            "confirm_public_release_notes"
        ]
        self.assertFalse(public_notes_input["default"])
        self.assertEqual("boolean", public_notes_input["type"])
        for input_name in (
            "authorize_delete_github_release",
            "authorize_delete_git_tag",
            "authorize_delete_docker_tag",
        ):
            with self.subTest(input_name=input_name):
                deletion_input = triggers["workflow_dispatch"]["inputs"][input_name]
                self.assertFalse(deletion_input["default"])
                self.assertEqual("boolean", deletion_input["type"])

        checkout_step = next_or_fail(
            step for step in steps if step["name"] == "Checkout"
        )
        self.assertEqual(
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
            checkout_step["uses"],
        )
        self.assertEqual(0, checkout_step["with"]["fetch-depth"])
        self.assertFalse(checkout_step["with"]["persist-credentials"])

        self.assertIn("tools/prebuilt_release_metadata.py", workflow_text)
        self.assertNotIn("existing-release-tags.txt", workflow_text)
        self.assertNotIn("--existing-tags-file", workflow_text)
        self.assertIn("--requested-version", workflow_text)
        self.assertIn("--requested-docker-repository", workflow_text)
        self.assertIn("--changelog CHANGELOG.md", workflow_text)
        self.assertIn("--release-notes-output dist/release-notes.md", workflow_text)
        self.assertIn(
            "--validate-public-release-notes dist/release-notes.md", workflow_text
        )
        self.assertIn("REQUESTED_PUBLIC_NOTES_CONFIRMATION", workflow_text)
        self.assertIn(
            "Release notes require explicit human public-disclosure review",
            workflow_text,
        )
        self.assertIn("REQUESTED_REPLACE_EXISTING", workflow_text)
        self.assertIn(
            "Deletion confirmations require replace_existing=true", workflow_text
        )
        for lookup_label in ("GitHub tag", "GitHub release", "Docker Hub tag"):
            with self.subTest(lookup_label=lookup_label):
                self.assertIn(f'"{lookup_label}",', workflow_text)
        self.assertIn('f"{label} lookup returned HTTP {status}', workflow_text)
        self.assertIn("lookup transport failed", workflow_text)
        self.assertIn("except (TimeoutError, urllib.error.URLError)", workflow_text)
        self.assertIn("status not in {200, 404}", workflow_text)
        self.assertIn("--latest=false", workflow_text)
        self.assertIn("python3 -m tools.prepare_ci_compose_environment", workflow_text)
        self.assertIn('(".env_example", ".env")', environment_helper_text)
        self.assertIn("ENV_TEMPLATE_PAIRS", environment_helper_text)
        self.assertIn("_copy_contract_exclusively", environment_helper_text)
        self.assertIn("os.O_EXCL", environment_helper_text)
        self.assertIn("os.O_NOFOLLOW", environment_helper_text)
        self.assertIn("os.O_CLOEXEC", environment_helper_text)
        self.assertIn(
            '["docker", "compose", "-f", "docker-compose.yml", "config", "--profiles"]',
            environment_helper_text,
        )
        self.assertIn(
            'values[COMPOSE_PROFILES_KEY] = ",".join', environment_helper_text
        )
        self.assertIn(
            "No Compose profiles discovered for CI validation", environment_helper_text
        )
        self.assertIn("DOCKERHUB_TOKEN", workflow_text)
        self.assertIn("--password-stdin", workflow_text)
        self.assertNotIn("DOCKERHUB_ACCESS_TOKEN", workflow_text)
        self.assertIn("# zizmor: ignore[secrets-outside-env]", workflow_text)
        self.assertIn(
            "GitHub Actions environments create deployment records", workflow_text
        )
        scout_install_step = next_or_fail(
            step for step in steps if step["name"] == "Install Docker Scout CLI"
        )
        self.assertEqual(
            "1.23.1", scout_install_step["env"]["DOCKER_SCOUT_CLI_VERSION"]
        )
        expected_scout_sha256 = "".join(
            (
                "0f778f9d833f28bc",
                "6cccff95e3303984",
                "9c0afcecafa38d9f",
                "46fe74bfd0915714",
            )
        )
        self.assertEqual(
            expected_scout_sha256,
            scout_install_step["env"]["DOCKER_SCOUT_CLI_SHA256"],
        )
        self.assertIn(
            "github.com/docker/scout-cli/releases/download",
            scout_install_step["run"],
        )
        self.assertIn("sha256sum -c -", scout_install_step["run"])
        self.assertIn(
            "${HOME}/.docker/cli-plugins/docker-scout", scout_install_step["run"]
        )
        self.assertIn("docker scout version", scout_install_step["run"])
        scout_action_lines = [
            line.strip()
            for line in workflow_text.splitlines()
            if "uses: docker/scout-action@" in line
        ]
        self.assertGreaterEqual(len(scout_action_lines), 1)
        expected_action_suffix = (
            f"# v{scout_install_step['env']['DOCKER_SCOUT_CLI_VERSION']}"
        )
        self.assertTrue(
            all(line.endswith(expected_action_suffix) for line in scout_action_lines)
        )
        scout_enable_step = next_or_fail(
            step
            for step in steps
            if step["name"] == "Ensure Docker Scout repository analysis is enabled"
        )
        self.assertEqual("strmt7", scout_enable_step["env"]["DOCKER_SCOUT_ORG"])
        self.assertIn("docker scout version", scout_enable_step["run"])
        self.assertIn("list_enabled_repositories()", scout_enable_step["run"])
        self.assertIn(
            "Docker Scout repository analysis is already enabled",
            scout_enable_step["run"],
        )
        self.assertIn(
            'docker scout repo enable "${DOCKER_REPOSITORY}" --org "${DOCKER_SCOUT_ORG}"',
            scout_enable_step["run"],
        )
        self.assertIn("docker scout repo list", scout_enable_step["run"])
        self.assertIn("--only-enabled", scout_enable_step["run"])
        self.assertIn('grep -F "${DOCKER_REPOSITORY}"', scout_enable_step["run"])
        self.assertLess(
            scout_enable_step["run"].index("list_enabled_repositories"),
            scout_enable_step["run"].index("docker scout repo enable"),
        )
        self.assertIn(
            "reached the repository limit for your plan", scout_enable_step["run"]
        )
        self.assertIn("upgrade the Docker Hub plan", scout_enable_step["run"])
        self.assertIn('exit "${enable_status}"', scout_enable_step["run"])
        self.assertLess(
            workflow_text.index("Install Docker Scout CLI"),
            workflow_text.index("Ensure Docker Scout repository analysis is enabled"),
        )
        self.assertLess(
            workflow_text.index("Ensure Docker Scout repository analysis is enabled"),
            workflow_text.index("Build hardened flattened runtime images"),
        )
        scout_upload_step = next_or_fail(
            step
            for step in steps
            if step["name"] == "Upload carrier analysis to Docker Scout"
        )
        self.assertEqual("strmt7", scout_upload_step["env"]["DOCKER_SCOUT_ORG"])
        self.assertIn("docker scout push \\", scout_upload_step["run"])
        self.assertIn('--org "${DOCKER_SCOUT_ORG}"', scout_upload_step["run"])
        self.assertIn("--sbom", scout_upload_step["run"])
        self.assertIn('"${CARRIER_IMAGE}"', scout_upload_step["run"])
        self.assertLess(
            workflow_text.index("Upload carrier analysis to Docker Scout"),
            workflow_text.index("Analyze Docker Hub carrier image with Docker Scout"),
        )
        self.assertIn(
            "from tools.env_safety_guard import (",
            environment_helper_text,
        )
        self.assertIn("resolve_env_references,", environment_helper_text)
        self.assertIn(
            "resolve_env_references(value, resolved_values)", environment_helper_text
        )
        self.assertIn(
            "Unresolved synthetic environment reference", environment_helper_text
        )
        self.assertNotIn('values["REDIS_SAVE_POLICY"] =', environment_helper_text)
        self.assertNotIn('values["REDIS_APPENDONLY"] =', environment_helper_text)
        self.assertNotIn('values["REDIS_MAXMEMORY"] =', environment_helper_text)
        self.assertNotIn('values["REDIS_MAXMEMORY_POLICY"] =', environment_helper_text)
        self.assertNotIn('values["REDIS_DATA_TMPFS_SIZE"] =', environment_helper_text)
        self.assertNotIn('COMPOSE_PROFILES="sysctl-init,crowdsec"', workflow_text)

    def test_workflows_do_not_use_github_actions_environments(self) -> None:
        """Verify workflows do not use GitHub Actions environments.

        Inputs: workflow fixtures. Output: empty offender list.
        """
        offenders: list[str] = []
        workflows_dir = self.repo_root / ".github" / "workflows"
        for workflow_path in sorted(workflows_dir.glob("*.yml")):
            workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
            for job_name, job in workflow.get("jobs", {}).items():
                if "environment" in job:
                    offenders.append(
                        f"{workflow_path.relative_to(self.repo_root)}:{job_name}: "
                        "remove the job environment because GitHub Actions "
                        "environments create deployment records"
                    )
        self.assertEqual([], offenders)
        workflow_instructions = self.read_text(
            ".github/instructions/workflows.instructions.md"
        )
        runtime_playbook = self.read_text("docs/reference/ai-agent-runtime-playbook.md")
        for instruction_text in (workflow_instructions, runtime_playbook):
            self.assertIn(
                "No workflow in this repository may create GitHub deployment records",
                instruction_text,
            )
            self.assertIn("Do not", instruction_text)
            self.assertIn("job-level", instruction_text)
            self.assertIn("`environment` blocks", instruction_text)

    def test_release_workflow_embedded_python_blocks_parse(self) -> None:
        """Verify workflow heredoc Python is syntactically valid.

        Inputs: release workflow fixture. Output: parses each Python heredoc block.
        """
        workflow_text = self.read_text(".github/workflows/release-prebuilt-carrier.yml")
        workflow = yaml.safe_load(workflow_text)
        release_steps = workflow["jobs"]["release"]["steps"]
        parsed_blocks = 0

        for step in release_steps:
            run_script = step.get("run", "")
            lines = run_script.splitlines()
            for index, line in enumerate(lines):
                if "python3 - <<'PY'" not in line:
                    continue
                block: list[str] = []
                for candidate in lines[index + 1 :]:
                    if candidate == "PY":
                        break
                    block.append(candidate)
                else:
                    self.fail(f"Unterminated Python heredoc in step {step['name']}")
                parsed_blocks += 1
                with self.subTest(step=step["name"], block=parsed_blocks):
                    ast.parse("\n".join(block) + "\n")

        self.assertGreater(parsed_blocks, 0)

    def test_release_workflow_bash_steps_parse(self) -> None:
        """Verify every release workflow Bash step is syntactically valid.

        Inputs: release workflow fixture. Output: successful `bash -n` checks.
        """
        workflow = yaml.safe_load(
            self.read_text(".github/workflows/release-prebuilt-carrier.yml")
        )
        release_steps = workflow["jobs"]["release"]["steps"]
        parsed_steps = 0

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, step in enumerate(release_steps):
                run_script = step.get("run")
                if run_script is None:
                    continue
                parsed_steps += 1
                script_path = Path(tmp_dir) / f"release-step-{index}.sh"
                script_path.write_text(
                    f"#!/usr/bin/env bash\n{run_script}\n",
                    encoding="utf-8",
                    newline="\n",
                )
                completed = subprocess.run(
                    [self.bash_path, "-n", self.bash_path_arg(script_path)],
                    cwd=self.repo_root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                with self.subTest(step=step["name"]):
                    self.assertEqual(0, completed.returncode, completed.stderr)

        self.assertGreater(parsed_steps, 0)

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
        self.assertIn('DOCKER_BUILD_LOCAL_CACHE_ENABLED="0"', workflow_text)
        self.assertIn('DOCKER_BUILD_BAKE_SERIAL_MODE="always"', workflow_text)
        self.assertIn('DOCKER_BUILD_FLATTEN_FINAL_IMAGE="1"', workflow_text)
        self.assertIn('APPLY_SECURITY_HARDENING="1"', workflow_text)
        self.assertNotIn("DOCKER_BUILD_TARGETS=", workflow_text)
        self.assertIn(
            "docker compose -f docker-compose.yml config --images", workflow_text
        )
        self.assertIn('COMPOSE_PROFILES="${COMPOSE_PROFILES:?}"', workflow_text)
        self.assertIn("tools/prune_non_required_docker_images.py", workflow_text)
        self.assertIn(
            "--required-images-file dist/prebuilt-required-images.txt", workflow_text
        )
        self.assertNotIn("docker system df || true", workflow_text)
        self.assertIn('docker save "${compose_images[@]}"', workflow_text)
        self.assertIn("write_runtime_archive()", workflow_text)
        self.assertIn(
            "docker save failed on attempt ${attempt}; collecting storage diagnostics.",
            workflow_text,
        )
        self.assertIn("docker save failed after 3 attempts.", workflow_text)
        self.assertIn("tools/write_prebuilt_runtime_archive.py", workflow_text)
        self.assertIn("image_archive_sha256", workflow_text)
        self.assertIn("runtime_images_uncompressed_bytes", workflow_text)
        self.assertIn("df -h /", workflow_text)
        self.assertIn("/mnt/docker-data", workflow_text)
        self.assertIn("runner.environment == 'github-hosted'", workflow_text)
        self.assertIn("docker system df", workflow_text)
        self.assertIn("Set up carrier Buildx builder", workflow_text)
        self.assertIn("--driver docker-container", workflow_text)
        self.assertIn("BUILDX_BUILDER=", workflow_text)
        self.assertIn("docker buildx build", workflow_text)
        self.assertIn('--builder "${BUILDX_BUILDER:?}"', workflow_text)
        self.assertIn("-f docker/prebuilt-carrier.Dockerfile", workflow_text)
        self.assertIn('-t "${CARRIER_IMAGE}"', workflow_text)
        self.assertIn("dist/prebuilt-carrier-digest.txt", workflow_text)
        self.assertIn("PREBUILT_IMAGE_DIGEST=${carrier_digest}", workflow_text)
        self.assertIn(
            "PREBUILT_IMAGE_REF=${CARRIER_IMAGE}@${carrier_digest}", workflow_text
        )
        self.assertIn("Upload carrier digest release asset", workflow_text)
        self.assertIn('docker create "${CARRIER_IMAGE}"', workflow_text)
        self.assertIn(
            'docker cp "${cid}:/omero-prebuilt/prebuilt-manifest.json"',
            workflow_text,
        )
        self.assertIn(
            'docker cp "${cid}:/omero-prebuilt/prebuilt-required-images.txt"',
            workflow_text,
        )
        self.assertIn(
            "cmp dist/prebuilt-required-images.txt "
            "dist/verified-prebuilt-required-images.txt",
            workflow_text,
        )
        self.assertIn(
            'docker cp "${cid}:/omero-prebuilt/release-notes.md"', workflow_text
        )
        self.assertIn(
            "cmp dist/release-notes.md dist/verified-release-notes.md",
            workflow_text,
        )
        self.assertIn('"release_notes": "release-notes.md"', workflow_text)
        self.assertIn('"release_notes_sha256":', workflow_text)
        self.assertIn("org.opencontainers.image.title", workflow_text)
        self.assertIn("org.opencontainers.image.description", workflow_text)
        self.assertIn("org.opencontainers.image.version", workflow_text)
        self.assertIn("org.opencontainers.image.revision", workflow_text)
        self.assertIn("org.opencontainers.image.source", workflow_text)
        self.assertIn("org.opencontainers.image.documentation", workflow_text)
        self.assertNotIn("docker run --rm", workflow_text)
        self.assertIn("gh release create", workflow_text)
        self.assertIn("prebuilt-carrier-digest.txt", workflow_text)
        self.assertIn("release-notes.md", workflow_text)
        self.assertIn("RELEASE_REPLACE_EXISTING", workflow_text)
        self.assertIn(
            "Replacement requested but no existing release artifact was found",
            workflow_text,
        )
        self.assertIn(
            'gh release delete "${RELEASE_VERSION}"',
            workflow_text,
        )
        self.assertIn("AUTHORIZE_DELETE_GITHUB_RELEASE", workflow_text)
        self.assertIn("AUTHORIZE_DELETE_GIT_TAG", workflow_text)
        self.assertIn("AUTHORIZE_DELETE_DOCKER_TAG", workflow_text)
        self.assertIn(
            "Missing fresh approval for GitHub release deletion", workflow_text
        )
        self.assertIn("Missing fresh approval for Git tag deletion", workflow_text)
        self.assertIn(
            "Missing fresh approval for Docker Hub tag deletion", workflow_text
        )
        self.assertIn(
            '"repos/${GITHUB_REPOSITORY}/git/refs/tags/${RELEASE_VERSION}"',
            workflow_text,
        )
        self.assertIn(
            '"https://hub.docker.com/v2/auth/token"',
            workflow_text,
        )
        self.assertNotIn('"https://hub.docker.com/v2/users/login"', workflow_text)
        self.assertIn('method="DELETE"', workflow_text)
        self.assertIn("Docker Hub tag remained visible after deletion", workflow_text)
        self.assertIn(
            "Existing GitHub and Docker Hub release artifacts are absent.",
            workflow_text,
        )
        self.assertIn("Create GitHub draft release", workflow_text)
        self.assertIn("Publish GitHub release", workflow_text)
        self.assertIn(
            "Report retained draft after failed carrier publish",
            workflow_text,
        )
        self.assertIn("RELEASE_TARGET_REF: ${{ github.ref_name }}", workflow_text)
        self.assertIn(
            '"repos/${GITHUB_REPOSITORY}/git/ref/heads/${RELEASE_TARGET_REF}"',
            workflow_text,
        )
        self.assertIn(
            '"repos/${GITHUB_REPOSITORY}/git/ref/tags/${RELEASE_VERSION}"',
            workflow_text,
        )
        self.assertIn(
            '--method POST "repos/${GITHUB_REPOSITORY}/git/refs"',
            workflow_text,
        )
        self.assertIn(
            '--method PATCH "repos/${GITHUB_REPOSITORY}/git/refs/tags/${RELEASE_VERSION}"',
            workflow_text,
        )
        self.assertIn('-F "force=true"', workflow_text)
        self.assertIn('gh release upload "${RELEASE_VERSION}"', workflow_text)
        self.assertIn("--clobber", workflow_text)
        self.assertLess(
            workflow_text.index('--method POST "repos/${GITHUB_REPOSITORY}/git/refs"'),
            workflow_text.index('gh release create "${RELEASE_VERSION}"'),
        )
        self.assertIn('-f "ref=refs/tags/${RELEASE_VERSION}"', workflow_text)
        self.assertIn('-f "sha=${GITHUB_SHA}"', workflow_text)
        self.assertIn("--verify-tag", workflow_text)
        self.assertIn(
            '"repos/${GITHUB_REPOSITORY}/git/tags/${created_tag_sha}"',
            workflow_text,
        )
        self.assertIn('--target "${RELEASE_TARGET_REF}"', workflow_text)
        self.assertIn("--draft", workflow_text)
        self.assertIn("--draft=false", workflow_text)
        self.assertNotIn("--prerelease", workflow_text)
        self.assertIn("if: failure()", workflow_text)
        self.assertNotIn("RELEASE_DRAFT_CREATED_BY_RUN", workflow_text)
        self.assertNotIn("RELEASE_TAG_CREATED_BY_RUN", workflow_text)
        self.assertNotIn("--json isDraft", workflow_text)
        self.assertNotIn("--cleanup-tag", workflow_text)
        self.assertIn(
            "Any draft release or Git tag created by this failed run was retained",
            workflow_text,
        )
        self.assertIn("Remove carrier Buildx builder", workflow_text)
        self.assertIn('docker buildx rm -f "${BUILDX_BUILDER}"', workflow_text)
        self.assertIn(
            "--json tagName,targetCommitish,isDraft,isPrerelease,assets,url",
            workflow_text,
        )
        self.assertIn('release.get("tagName")', workflow_text)
        self.assertIn('release.get("targetCommitish")', workflow_text)
        self.assertIn('release.get("isDraft")', workflow_text)
        self.assertIn('release.get("isPrerelease")', workflow_text)
        self.assertNotIn('--target "${GITHUB_SHA}"', workflow_text)
        self.assertNotIn("git ls-remote", workflow_text)

    def test_release_metadata_helper_requires_explicit_aligned_tags(self) -> None:
        """Verify release helper keeps explicit GitHub and Docker tags aligned.

        Inputs: synthetic release values. Output: aligned metadata or rejection.
        """
        parsed = prebuilt_release_metadata.parse_release_version(VALID_RELEASE_VERSION)
        self.assertEqual((1, 0, 0, "main.1"), tuple(vars(parsed).values()))
        self.assertTrue(
            prebuilt_release_metadata.is_valid_release_version(VALID_RELEASE_VERSION)
        )
        stable = prebuilt_release_metadata.parse_release_version("2.3.4")
        self.assertEqual((2, 3, 4, None), tuple(vars(stable).values()))
        self.assertEqual(
            (
                VALID_RELEASE_VERSION,
                "strmt7/omero-docker-extended",
                f"strmt7/omero-docker-extended:{VALID_RELEASE_VERSION}",
            ),
            prebuilt_release_metadata.resolve_release_metadata(
                requested_version=VALID_RELEASE_VERSION,
                requested_docker_repository="",
                default_docker_repository="strmt7/omero-docker-extended",
            ),
        )
        self.assertEqual(
            "example/project:2.0.0",
            prebuilt_release_metadata.resolve_release_metadata(
                requested_version=" 2.0.0 ",
                requested_docker_repository=" example/project ",
                default_docker_repository="unused/default",
            )[2],
        )
        with self.assertRaisesRegex(ValueError, "explicit release version"):
            prebuilt_release_metadata.resolve_release_metadata(
                requested_version=" ",
                requested_docker_repository="",
                default_docker_repository="example/project",
            )
        with self.assertRaisesRegex(ValueError, "lower-case"):
            prebuilt_release_metadata.validate_docker_repository("Invalid/Repo")
        for bad_value in (
            "latest",
            "example/project:latest",
            f"v{VALID_RELEASE_VERSION}",
            "1.0.0+build.1",
            "1.0",
        ):
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
                ["--validate-release-version", VALID_RELEASE_VERSION]
            ),
        )
        with (
            mock.patch.object(
                sys,
                "argv",
                ["prebuilt_release_metadata.py", "--validate-release-version", "2.0.0"],
            ),
            self.assertRaises(SystemExit) as exit_context,
        ):
            runpy.run_path(
                str(self.repo_root / "tools" / "prebuilt_release_metadata.py"),
                run_name="__main__",
            )
        self.assertEqual(0, exit_context.exception.code)

    def test_release_metadata_changelog_contract_is_professional(self) -> None:
        """Verify canonical categories, comparison, and release rendering.

        Inputs: synthetic changelogs. Output: parsed notes or fail-closed errors.
        """
        changelog = valid_changelog()
        release = prebuilt_release_metadata.extract_release_changelog(
            changelog, VALID_RELEASE_VERSION
        )
        self.assertEqual(VALID_RELEASE_VERSION, release.version)
        self.assertEqual("2026-07-18", release.release_date.isoformat())
        self.assertIn("### Upgrade Notes", release.body)
        self.assertTrue(release.comparison_url.endswith(VALID_RELEASE_VERSION))
        rendered = prebuilt_release_metadata.render_release_notes(
            changelog, VALID_RELEASE_VERSION
        )
        self.assertIn(f"# OMERO Docker Extended {VALID_RELEASE_VERSION}", rendered)
        self.assertIn("**Full comparison:**", rendered)
        self.assertNotIn(f"[{VALID_RELEASE_VERSION}]:", rendered)

        missing_standard_sections = f"""# Changelog

## [{VALID_RELEASE_VERSION}] - 2026-07-18

This long operator summary intentionally contains enough explanatory material
to pass the minimum content threshold while omitting all standard categories.

### Upgrade Notes

- Preserve the current deployment configuration and storage assignments.

### Verification

- Run the complete documented release verification matrix before publication.

[{VALID_RELEASE_VERSION}]: https://github.com/example/project/compare/0.9.0...{VALID_RELEASE_VERSION}
"""
        invalid_changelogs = {
            "missing heading": changelog.replace(
                f"## [{VALID_RELEASE_VERSION}]", "## [9.9.9]"
            ),
            "duplicate heading": changelog
            + changelog[changelog.index(f"## [{VALID_RELEASE_VERSION}]") :],
            "invalid date": changelog.replace("2026-07-18", "2026-02-31", 1),
            "short body": (
                f"## [{VALID_RELEASE_VERSION}] - 2026-07-18\n\n"
                "### Added\n\n- A.\n\n### Upgrade Notes\n\n- B.\n\n"
                "### Verification\n\n- C.\n\n"
                f"[{VALID_RELEASE_VERSION}]: https://github.com/example/project/"
                f"compare/old...{VALID_RELEASE_VERSION}\n"
            ),
            "placeholder": changelog.replace("clear summary", "TODO summary"),
            "invalid heading": changelog.replace("### Added", "### Added:"),
            "unsupported heading": changelog.replace("### Added", "### Highlights"),
            "duplicate section": changelog.replace("### Changed", "### Added"),
            "empty section": changelog.replace(
                "- Improves the primary workflow with a documented compatible "
                "implementation.",
                "The primary workflow remains compatible.",
            ),
            "missing verification": changelog.replace(
                "### Verification\n\n"
                "- Exercises unit, integration, deployment, and release artifact "
                "contracts.\n\n",
                "",
            ),
            "no standard category": missing_standard_sections,
            "missing comparison": changelog.rsplit("\n[", 1)[0] + "\n",
            "duplicate comparison": changelog
            + f"[{VALID_RELEASE_VERSION}]: https://github.com/example/project/"
            f"compare/older...{VALID_RELEASE_VERSION}\n",
            "wrong comparison": changelog.replace(
                f"compare/0.9.0-main.1...{VALID_RELEASE_VERSION}",
                f"releases/tag/{VALID_RELEASE_VERSION}",
            ),
        }
        for name, invalid_changelog in invalid_changelogs.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                prebuilt_release_metadata.extract_release_changelog(
                    invalid_changelog, VALID_RELEASE_VERSION
                )

        safe_security = changelog.replace(
            "### Changed\n\n"
            "- Aligns the supported runtime behavior with its documented public "
            "contract.",
            "### Security\n\n"
            "- Strengthens defense-in-depth safeguards without publishing "
            "technical details.",
        )
        prebuilt_release_metadata.extract_release_changelog(
            safe_security, VALID_RELEASE_VERSION
        )
        for security_note in (
            "- Describes a private endpoint.",
            "- Applies `internal` implementation controls.",
        ):
            with (
                self.subTest(security_note=security_note),
                self.assertRaises(ValueError),
            ):
                prebuilt_release_metadata.extract_release_changelog(
                    safe_security.replace(
                        "- Strengthens defense-in-depth safeguards without publishing "
                        "technical details.",
                        security_note,
                    ),
                    VALID_RELEASE_VERSION,
                )

    def test_release_metadata_blocks_sensitive_public_content(self) -> None:
        """Verify release notes reject private and exploit-enabling material.

        Inputs: representative sensitive strings. Output: every value is blocked.
        """
        sensitive_values = (
            "credential " + "gh" + "p_" + ("x" * 36),
            "-----BEGIN " + "PRIVATE KEY-----",
            "pass" + "word=not-for-publication",
            "https://name:value@public.example/path",
            "operator@host.example",
            r"C:\Users\operator\release.txt",
            r"\\private-host\share\release.txt",
            "/home/operator/release.txt",
            "service.internal",
            "address 192.0.2.1",
            "address 2001:db8::1",
            "Includes a proof of concept.",
            "https://1@public.example/path",
            "https://?query",
            "https://[invalid]/path",
        )
        for sensitive_value in sensitive_values:
            with self.subTest(value_type=sensitive_values.index(sensitive_value)):
                with self.assertRaises(ValueError):
                    prebuilt_release_metadata.validate_public_release_text(
                        f"Public summary {sensitive_value}", "synthetic notes"
                    )

        prebuilt_release_metadata.validate_public_release_text(
            "Public summary at https://public.example/path with invalid numeric "
            "forms 999.999.999.999 and a:b:c.",
            "synthetic notes",
        )

    def test_release_metadata_cli_writes_validated_notes_and_environment(self) -> None:
        """Verify release CLI validates inputs and writes deterministic outputs.

        Inputs: temporary changelog and output paths. Output: notes and env values.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            changelog_path = temp_path / "CHANGELOG.md"
            changelog_path.write_text(valid_changelog(), encoding="utf-8")
            notes_path = temp_path / "nested" / "release-notes.md"
            env_path = temp_path / "github.env"
            args = [
                "--requested-version",
                VALID_RELEASE_VERSION,
                "--requested-docker-repository",
                "",
                "--default-docker-repository",
                "strmt7/omero-docker-extended",
                "--changelog",
                str(changelog_path),
                "--release-notes-output",
                str(notes_path),
                "--github-env",
                str(env_path),
            ]
            self.assertEqual(0, prebuilt_release_metadata.main(args))
            self.assertIn("### Added", notes_path.read_text(encoding="utf-8"))
            env_text = env_path.read_text(encoding="utf-8")
            self.assertIn(f"RELEASE_VERSION={VALID_RELEASE_VERSION}\n", env_text)
            self.assertIn(
                f"CARRIER_IMAGE=strmt7/omero-docker-extended:{VALID_RELEASE_VERSION}\n",
                env_text,
            )
            self.assertEqual(
                0,
                prebuilt_release_metadata.main(
                    ["--validate-public-release-notes", str(notes_path)]
                ),
            )
            with mock.patch.dict(
                os.environ, {"GITHUB_ENV": str(temp_path / "implicit.env")}
            ):
                self.assertEqual(0, prebuilt_release_metadata.main(args[:-2]))
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(0, prebuilt_release_metadata.main(args[:-2]))

            invalid_arg_sets = (
                [],
                ["--default-docker-repository", "example/project"],
                [
                    "--requested-version",
                    VALID_RELEASE_VERSION,
                    "--default-docker-repository",
                    "example/project",
                ],
                ["--validate-public-release-notes", str(temp_path / "missing.md")],
            )
            for invalid_args in invalid_arg_sets:
                with self.subTest(invalid_args=invalid_args):
                    self.assertEqual(1, prebuilt_release_metadata.main(invalid_args))

            invalid_changelog_path = temp_path / "invalid-changelog.md"
            invalid_changelog_path.write_text("# Changelog\n", encoding="utf-8")
            self.assertEqual(
                1,
                prebuilt_release_metadata.main(
                    [
                        "--requested-version",
                        VALID_RELEASE_VERSION,
                        "--default-docker-repository",
                        "example/project",
                        "--changelog",
                        str(invalid_changelog_path),
                        "--release-notes-output",
                        str(temp_path / "invalid-notes.md"),
                    ]
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

    def test_release_prune_helper_keeps_only_compose_required_images(self) -> None:
        """Verify release pruning is derived from required image references.

        Inputs: synthetic docker image listing. Output: asserts removable refs.
        """
        required_images = [
            "example.local/required-one:1.0.0",
            "example.local/required-two:2.0.0",
        ]
        local_images = [
            prune_non_required_docker_images.LocalImage(
                reference="example.local/required-one:1.0.0",
                image_id="sha256:required-one",
            ),
            prune_non_required_docker_images.LocalImage(
                reference="example.local/required-two:2.0.0",
                image_id="sha256:required-two",
            ),
            prune_non_required_docker_images.LocalImage(
                reference="example.local/base-only:3.0.0",
                image_id="sha256:base",
            ),
            prune_non_required_docker_images.LocalImage(
                reference="example.local/non-required:latest",
                image_id="sha256:local-latest",
            ),
            prune_non_required_docker_images.LocalImage(
                reference="example.local/required-one-alias:4.0.0",
                image_id="sha256:required-one",
            ),
        ]

        removable = prune_non_required_docker_images.removable_image_references(
            required_images=required_images,
            local_images=local_images,
            required_image_ids={"sha256:required-one", "sha256:required-two"},
        )

        self.assertEqual(
            ["example.local/base-only:3.0.0", "example.local/non-required:latest"],
            removable,
        )

    def test_release_prune_helper_rejects_unsafe_image_references(self) -> None:
        """Verify pruning helper rejects floating or malformed refs.

        Inputs: malformed synthetic image refs. Output: asserts validation fails.
        """
        for image_ref in ("latest", "repo/image:latest", "-bad:tag", "bad tag"):
            with self.subTest(image_ref=image_ref):
                with self.assertRaises(ValueError):
                    prune_non_required_docker_images.validate_image_reference(image_ref)

    def test_release_prune_helper_allows_local_latest_as_prune_candidate(self) -> None:
        """Verify local daemon latest tags do not invalidate required images.

        Inputs: synthetic docker image listing. Output: asserts latest is removable.
        """
        reference = prune_non_required_docker_images.image_reference_from_listing(
            {"Repository": "example.local/local-only", "Tag": "latest"}
        )

        self.assertEqual("example.local/local-only:latest", reference)

    def test_prebuilt_carrier_image_is_scratch_data_only(self) -> None:
        """Verify carrier image is data-only and has no OS package surface.

        Inputs: carrier dockerfile fixture. Output: asserts scratch payload image.
        """
        dockerfile = self.read_text("docker/prebuilt-carrier.Dockerfile")
        readme = self.read_text("README.md")
        normalized_readme = " ".join(readme.split())
        quickstart = self.read_text("docs/deployment/quickstart.md")
        normalized_quickstart = " ".join(quickstart.split())

        self.assertIn("FROM scratch", dockerfile)
        self.assertIn("Scratch has no passwd database", dockerfile)
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertIn("HEALTHCHECK NONE", dockerfile)
        self.assertIn('CMD ["/omero-prebuilt/carrier-data-only"]', dockerfile)
        self.assertNotIn("ENTRYPOINT", dockerfile)
        self.assertNotIn("alpine", dockerfile.lower())
        self.assertNotIn("busybox", dockerfile.lower())
        self.assertNotIn("RUN ", dockerfile)
        self.assertNotIn("HEALTHCHECK CMD", dockerfile)
        self.assertNotIn(" sh", dockerfile.lower())
        self.assertNotIn("--chown", dockerfile)
        self.assertIn(
            "COPY --chmod=0444",
            dockerfile,
        )
        self.assertIn("prebuilt-manifest.json", dockerfile)
        self.assertIn("prebuilt-required-images.txt", dockerfile)
        self.assertIn("release-notes.md", dockerfile)
        self.assertIn("runtime-images.tar.gz", dockerfile)
        self.assertIn("/omero-prebuilt/", dockerfile)
        self.assertNotIn("chown -R", dockerfile)
        self.assertNotIn("chmod 0444 /omero-prebuilt/runtime-images.tar.gz", dockerfile)
        self.assertNotIn("test -r /omero-prebuilt/prebuilt-manifest.json", dockerfile)
        self.assertNotIn("test -r /omero-prebuilt/runtime-images.tar.gz", dockerfile)
        self.assertIn(
            "The release workflow flattens the bundled runtime service images", readme
        )
        self.assertIn(
            "does not include Alpine, BusyBox, a package manager, or a shell",
            normalized_readme,
        )
        self.assertIn("HEALTHCHECK NONE", readme)
        self.assertNotIn("normal image wrapper", readme)
        self.assertIn("one payload layer", normalized_quickstart)
        self.assertIn("HEALTHCHECK NONE", quickstart)

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
