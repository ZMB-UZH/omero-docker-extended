"""Regression tests for build-time version env contracts."""

from __future__ import annotations

import unittest
from pathlib import Path


class BuildVersionEnvContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_installation_paths_example_excludes_build_version_pins(self) -> None:
        env_text = self.read_text("installation_paths_example.env")
        self.assertNotIn("OMERO_CLI_ZARR_VERSION=", env_text)
        self.assertNotIn("OME_ZARR_PY_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS2RAW_VERSION=", env_text)

    def test_omeroserver_example_defines_native_zarr_build_versions(self) -> None:
        env_text = self.read_text("env/omeroserver_example.env")
        self.assertIn("OMERO_CLI_ZARR_VERSION=0.8.0", env_text)
        self.assertIn("OME_ZARR_PY_VERSION=0.14.0", env_text)
        self.assertIn("BIOFORMATS2RAW_VERSION=0.11.0", env_text)

    def test_compose_requires_build_versions_from_omeroserver_env(self) -> None:
        compose_text = self.read_text("docker-compose.yml")
        self.assertIn(
            'OMERO_CLI_ZARR_VERSION: "${OMERO_CLI_ZARR_VERSION:?Set OMERO_CLI_ZARR_VERSION in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            'OME_ZARR_PY_VERSION: "${OME_ZARR_PY_VERSION:?Set OME_ZARR_PY_VERSION in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            'BIOFORMATS2RAW_VERSION: "${BIOFORMATS2RAW_VERSION:?Set BIOFORMATS2RAW_VERSION in env/omeroserver.env}"',
            compose_text,
        )

    def test_omeroweb_dockerfile_fails_closed_without_version_args(self) -> None:
        dockerfile_text = self.read_text("docker/omero-web.Dockerfile")
        self.assertIn("ARG OMERO_CLI_ZARR_VERSION\n", dockerfile_text)
        self.assertIn("ARG OME_ZARR_PY_VERSION\n", dockerfile_text)
        self.assertIn("ARG BIOFORMATS2RAW_VERSION\n", dockerfile_text)
        self.assertNotIn("ARG OMERO_CLI_ZARR_VERSION=", dockerfile_text)
        self.assertNotIn("ARG OME_ZARR_PY_VERSION=", dockerfile_text)
        self.assertNotIn("ARG BIOFORMATS2RAW_VERSION=", dockerfile_text)
        self.assertIn(
            "OMERO_CLI_ZARR_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn(
            "OME_ZARR_PY_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn(
            "BIOFORMATS2RAW_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )

    def test_installation_script_generated_dot_env_includes_server_env_file(
        self,
    ) -> None:
        script_text = self.read_text("installation/installation_script.sh")
        self.assertIn(
            "COMPOSE_ENV_FILES=installation_paths.env:env/omero_secrets.env:env/omeroserver.env",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable OMERO_CLI_ZARR_VERSION in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable OME_ZARR_PY_VERSION in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable BIOFORMATS2RAW_VERSION in ${server_env_source}",
            script_text,
        )


if __name__ == "__main__":
    unittest.main()
