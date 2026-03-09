"""Tests for installation/docker_buildx_compressed_push.sh."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class DockerBuildxCompressedPushScriptTests(unittest.TestCase):
    """Validation and command generation coverage for compressed build helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_path = (
            cls.repo_root / "installation" / "docker_buildx_compressed_push.sh"
        )

    def _create_fake_docker(self, bin_dir: Path, log_path: Path) -> None:
        fake_docker_path = bin_dir / "docker"
        fake_docker_path.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
log_path="${FAKE_DOCKER_LOG_PATH:?}"
printf '%s\n' "$*" >> "${log_path}"
inspect_json="${FAKE_DOCKER_IMAGE_INSPECT_JSON:-}"
compose_config_output="${FAKE_DOCKER_COMPOSE_CONFIG_OUTPUT:-}"
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "version" ]; then
  exit 0
fi
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "inspect" ]; then
  printf 'Name:   %s\nDriver: docker-container\n' "${3:-default}"
  exit 0
fi
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "create" ]; then
  exit 0
fi
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "use" ]; then
  exit 0
fi
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "bake" ]; then
  exit 0
fi
if [ "${1:-}" = "compose" ] && [ "${4:-}" = "config" ]; then
  if [ -n "${compose_config_output}" ]; then
    printf '%s\n' "${compose_config_output}"
  fi
  exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "inspect" ]; then
  if [ -n "${inspect_json}" ]; then
    printf '%s\n' "${inspect_json}"
  fi
  exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "tag" ]; then
  exit 0
fi
if [ "${1:-}" = "build" ]; then
  exit 0
fi
if [ "${1:-}" = "container" ] && [ "${2:-}" = "create" ]; then
  printf 'fake-container-id\n'
  exit 0
fi
if [ "${1:-}" = "container" ] && [ "${2:-}" = "rm" ]; then
  exit 0
fi
if [ "${1:-}" = "export" ]; then
  printf 'fake-tar-stream'
  exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "import" ]; then
  cat >/dev/null
  exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "rm" ]; then
  exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "push" ]; then
  exit 0
fi
exit 0
""",
            encoding="utf-8",
        )
        fake_docker_path.chmod(fake_docker_path.stat().st_mode | stat.S_IXUSR)

    def test_script_fails_when_registry_prefix_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin_dir = temp_path / "bin"
            fake_bin_dir.mkdir(parents=True, exist_ok=True)
            fake_log_path = temp_path / "docker.log"
            fake_log_path.write_text("", encoding="utf-8")
            self._create_fake_docker(fake_bin_dir, fake_log_path)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin_dir}:{env.get('PATH', '')}",
                    "FAKE_DOCKER_LOG_PATH": str(fake_log_path),
                    "DOCKER_IMAGE_TAG": "local",
                    "DOCKER_BUILD_TARGETS": "omeroserver",
                    "DOCKER_BUILD_PUSH_IMAGES": "1",
                }
            )
            env.pop("DOCKER_REGISTRY_PREFIX", None)

            result = subprocess.run(
                [str(self.script_path)],
                cwd=self.repo_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing required variable: DOCKER_REGISTRY_PREFIX", result.stderr)

    def test_script_allows_local_build_without_registry_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin_dir = temp_path / "bin"
            fake_bin_dir.mkdir(parents=True, exist_ok=True)
            fake_log_path = temp_path / "docker.log"
            fake_log_path.write_text("", encoding="utf-8")
            self._create_fake_docker(fake_bin_dir, fake_log_path)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin_dir}:{env.get('PATH', '')}",
                    "FAKE_DOCKER_LOG_PATH": str(fake_log_path),
                    "DOCKER_IMAGE_TAG": "dev",
                    "DOCKER_BUILD_TARGETS": "omeroserver",
                    "DOCKER_BUILD_PUSH_IMAGES": "0",
                    "DOCKER_REGISTRY_PREFIX_DEFAULT": "sandbox/omero",
                    "BUILDX_DATA_PATH": str(temp_path / "buildx_cache"),
                }
            )
            env.pop("DOCKER_REGISTRY_PREFIX", None)

            result = subprocess.run(
                [str(self.script_path)],
                cwd=self.repo_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Registry prefix      : (not set; building local images only)", result.stdout)

    def test_script_builds_expected_bake_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin_dir = temp_path / "bin"
            fake_bin_dir.mkdir(parents=True, exist_ok=True)
            fake_log_path = temp_path / "docker.log"
            fake_log_path.write_text("", encoding="utf-8")
            self._create_fake_docker(fake_bin_dir, fake_log_path)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin_dir}:{env.get('PATH', '')}",
                    "FAKE_DOCKER_LOG_PATH": str(fake_log_path),
                    "DOCKER_REGISTRY_PREFIX": "registry.example.com/omero",
                    "DOCKER_IMAGE_TAG": "2026.02.1",
                    "DOCKER_BUILD_TARGETS": "omeroserver omeroweb",
                    "DOCKER_BUILD_COMPRESSION_TYPE": "estargz",
                    "BUILDX_DATA_PATH": str(temp_path / "buildx_cache"),
                    "DOCKER_BUILD_COMPRESSION_LEVEL": "9",
                    "DOCKER_BUILD_PUSH_IMAGES": "1",
                    "DOCKER_BUILD_USE_OCI_MEDIATYPES": "1",
                    "DOCKER_BUILD_INLINE_CACHE": "1",
                    "DOCKER_BUILD_FLATTEN_FINAL_IMAGE": "0",
                }
            )

            result = subprocess.run(
                [str(self.script_path)],
                cwd=self.repo_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Running Buildx bake for compressed images", result.stdout)

            log_lines = fake_log_path.read_text(encoding="utf-8").splitlines()
            bake_lines = [line for line in log_lines if line.startswith("buildx bake")]
            self.assertEqual(
                len(bake_lines),
                2,
                msg=(
                    "Expected serial multi-target Buildx execution to emit one "
                    "bake command per target"
                ),
            )

            joined_bake_lines = "\n".join(bake_lines)
            self.assertIn("omeroserver", joined_bake_lines)
            self.assertIn("omeroweb", joined_bake_lines)
            self.assertIn(
                "omeroserver.output=type=image,name=registry.example.com/omero/omeroserver:2026.02.1,push=true,compression=estargz,compression-level=9,force-compression=true,oci-mediatypes=true",
                joined_bake_lines,
            )

    def test_script_runs_flatten_flow_with_metadata_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin_dir = temp_path / "bin"
            fake_bin_dir.mkdir(parents=True, exist_ok=True)
            fake_log_path = temp_path / "docker.log"
            fake_log_path.write_text("", encoding="utf-8")
            self._create_fake_docker(fake_bin_dir, fake_log_path)

            inspect_json = (
                '{"Config":{"Env":["PATH=/usr/local/bin","FOO=bar baz"],'
                '"Labels":{"test.label":"value with space"},'
                '"ExposedPorts":{"8080/tcp":{}},'
                '"Volumes":{"/data":{}},'
                '"WorkingDir":"/work",'
                '"User":"123:456",'
                '"StopSignal":"SIGTERM",'
                '"Entrypoint":["/hello.txt"],'
                '"Cmd":["--serve"],'
                '"OnBuild":[],'
                '"Shell":["/bin/sh","-c"],'
                '"Healthcheck":{"Test":["CMD","/hello.txt"],'
                '"Interval":5000000000,'
                '"Timeout":3000000000,'
                '"Retries":2}}}'
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin_dir}:{env.get('PATH', '')}",
                    "FAKE_DOCKER_LOG_PATH": str(fake_log_path),
                    "FAKE_DOCKER_IMAGE_INSPECT_JSON": inspect_json,
                    "DOCKER_IMAGE_TAG": "flattencheck",
                    "DOCKER_BUILD_TARGETS": "omeroserver",
                    "DOCKER_BUILD_PUSH_IMAGES": "0",
                    "DOCKER_BUILD_FLATTEN_FINAL_IMAGE": "1",
                    "DOCKER_BUILD_SQUASH": "1",
                    "DOCKER_BUILD_NO_CACHE": "1",
                    "DOCKER_BUILD_LOCAL_CACHE_ENABLED": "0",
                    "BUILDX_DATA_PATH": str(temp_path / "buildx_cache"),
                }
            )

            result = subprocess.run(
                [str(self.script_path)],
                cwd=self.repo_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Flatten final image  : 1", result.stdout)

            log_lines = fake_log_path.read_text(encoding="utf-8").splitlines()
            joined_log = "\n".join(log_lines)

            self.assertIn(
                "buildx bake --file",
                joined_log,
            )
            self.assertIn(
                "omeroserver.output=type=docker",
                joined_log,
            )
            self.assertNotIn(
                "omeroserver.squash=true",
                joined_log,
            )
            self.assertIn(
                "build --file",
                joined_log,
            )
            self.assertIn(
                "container create --name flatten-omeroserver-",
                joined_log,
            )
            self.assertIn(
                "--change ENV FOO=\"bar baz\"",
                joined_log,
            )
            self.assertIn(
                "--change ENTRYPOINT [\"/hello.txt\"]",
                joined_log,
            )
            self.assertIn(
                "--change HEALTHCHECK --interval=5000000000ns --timeout=3000000000ns --retries=2 CMD [\"/hello.txt\"]",
                joined_log,
            )
            self.assertIn(
                "image rm -f omeroserver:flattencheck__flatten_source_",
                joined_log,
            )
            self.assertIn(
                "image rm -f omeroserver:flattencheck__flatten_fs_",
                joined_log,
            )
            self.assertIn(
                "container rm -f flatten-omeroserver-",
                joined_log,
            )

    def test_script_runs_flatten_only_flow_for_compose_built_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin_dir = temp_path / "bin"
            fake_bin_dir.mkdir(parents=True, exist_ok=True)
            fake_log_path = temp_path / "docker.log"
            fake_log_path.write_text("", encoding="utf-8")
            self._create_fake_docker(fake_bin_dir, fake_log_path)

            inspect_json = (
                '{"Config":{"Env":["PATH=/usr/local/bin","FOO=bar"],'
                '"Labels":{"test.label":"value"},'
                '"ExposedPorts":{"8080/tcp":{}},'
                '"Volumes":{"/data":{}},'
                '"WorkingDir":"/work",'
                '"User":"123:456",'
                '"StopSignal":"SIGTERM",'
                '"Entrypoint":["/hello.txt"],'
                '"Cmd":["--serve"],'
                '"OnBuild":[],' 
                '"Shell":["/bin/sh","-c"],'
                '"Healthcheck":{"Test":["CMD","/hello.txt"],'
                '"Interval":5000000000,'
                '"Timeout":3000000000,'
                '"Retries":2}}}'
            )
            compose_config_output = (
                "services:\n"
                "  omeroserver:\n"
                "    image: omeroserver:custom\n"
                "  omeroweb:\n"
                "    image: omeroweb:custom\n"
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin_dir}:{env.get('PATH', '')}",
                    "FAKE_DOCKER_LOG_PATH": str(fake_log_path),
                    "FAKE_DOCKER_IMAGE_INSPECT_JSON": inspect_json,
                    "FAKE_DOCKER_COMPOSE_CONFIG_OUTPUT": compose_config_output,
                    "DOCKER_IMAGE_TAG": "flattencheck",
                    "DOCKER_BUILD_TARGETS": "omeroserver",
                    "DOCKER_BUILD_PUSH_IMAGES": "0",
                    "DOCKER_BUILD_FLATTEN_FINAL_IMAGE": "1",
                    "DOCKER_BUILD_FLATTEN_ONLY": "1",
                    "DOCKER_BUILD_SQUASH": "0",
                    "DOCKER_BUILD_NO_CACHE": "1",
                    "DOCKER_BUILD_LOCAL_CACHE_ENABLED": "0",
                    "COMPOSE_FILE": str(self.repo_root / "docker-compose.yml"),
                }
            )

            result = subprocess.run(
                [str(self.script_path)],
                cwd=self.repo_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Running image flatten-only workflow with settings:", result.stdout)

            joined_log = fake_log_path.read_text(encoding="utf-8")
            self.assertNotIn("buildx bake", joined_log)
            self.assertIn("compose -f", joined_log)
            self.assertIn("config", joined_log)
            self.assertIn("image inspect omeroserver:custom", joined_log)
            self.assertIn("image tag omeroserver:custom omeroserver:custom__flatten_source_", joined_log)
            self.assertIn("build --file", joined_log)
            self.assertIn("image import", joined_log)


if __name__ == "__main__":
    unittest.main()
