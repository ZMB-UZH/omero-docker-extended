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
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "version" ]; then
  exit 0
fi
if [ "${1:-}" = "buildx" ] && [ "${2:-}" = "inspect" ]; then
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
                    "DOCKER_BUILD_COMPRESSION_LEVEL": "9",
                    "DOCKER_BUILD_PUSH_IMAGES": "1",
                    "DOCKER_BUILD_USE_OCI_MEDIATYPES": "1",
                    "DOCKER_BUILD_INLINE_CACHE": "1",
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


if __name__ == "__main__":
    unittest.main()
