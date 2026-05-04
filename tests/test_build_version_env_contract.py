"""Regression tests for build-time version env contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class BuildVersionEnvContractTests(unittest.TestCase):
    """Test cases for build version env contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set Up Class.

        Inputs: none. Output: None.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        """Return read text.

        Inputs: `relative_path`. Output: `str`.
        """
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def test_installation_paths_example_excludes_build_version_pins(self) -> None:
        """Verify installation paths example excludes build version pins.

        Inputs: none. Output: None.
        """
        env_text = self.read_text("installation_paths_example.env")
        self.assertNotIn("OMERO_CLI_ZARR_VERSION=", env_text)
        self.assertNotIn("OME_ZARR_PY_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS2RAW_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS_VERSION=", env_text)

    def test_omeroserver_example_defines_native_zarr_build_versions(self) -> None:
        """Verify omeroserver example defines native Zarr build versions.

        Inputs: none. Output: None.
        """
        env_text = self.read_text("env/omeroserver_example.env")
        self.assertIn("OMERO_DROPBOX_VERSION=5.7.0", env_text)
        self.assertIn("OMERO_CLI_HOST=localhost", env_text)
        self.assertIn("OMERO_CLI_PORT=4064", env_text)
        self.assertIn("OMERO_SERVER_HOST_PORT=4064", env_text)
        self.assertIn("OMERO_JOB_SERVICE_HOST=localhost", env_text)
        self.assertIn("OMERO_JOB_SERVICE_PORT=4064", env_text)
        self.assertIn("OMERO_CLI_ZARR_VERSION=0.8.0", env_text)
        self.assertIn("OME_ZARR_PY_VERSION=0.15.0", env_text)
        self.assertIn("BIOFORMATS2RAW_VERSION=0.11.0", env_text)
        self.assertIn("BIOFORMATS_VERSION=8.5.0", env_text)

    def test_compose_requires_build_versions_from_omeroserver_env(self) -> None:
        """Verify compose requires build versions from omeroserver environment.

        Inputs: none. Output: None.
        """
        compose_text = self.read_text("docker-compose.yml")
        self.assertIn(
            'OMERO_DROPBOX_VERSION: "${OMERO_DROPBOX_VERSION:?Set OMERO_DROPBOX_VERSION in env/omeroserver.env}"',
            compose_text,
        )
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
        self.assertIn(
            'BIOFORMATS_VERSION: "${BIOFORMATS_VERSION:?Set BIOFORMATS_VERSION in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            "${OMERO_SERVER_HOST_PORT:?Set OMERO_SERVER_HOST_PORT in env/omeroserver.env}:${OMERO_CLI_PORT:?Set OMERO_CLI_PORT in env/omeroserver.env}",
            compose_text,
        )

    def test_compose_pins_monitoring_and_management_image_versions(self) -> None:
        """Verify compose pins monitoring and management image versions.

        Inputs: none. Output: None.
        """
        compose_text = self.read_text("docker-compose.yml")
        self.assertIn('image: "portainer/portainer-ce:2.40.0-alpine"', compose_text)
        self.assertIn('image: "grafana/alloy:v1.15.1"', compose_text)
        self.assertIn('image: "prom/prometheus:v3.11.2"', compose_text)
        self.assertIn('image: "prom/node-exporter:v1.11.1"', compose_text)
        self.assertIn('image: "oliver006/redis_exporter:v1.82.0-alpine"', compose_text)
        self.assertIn('image: "redis:8.6.2-alpine"', compose_text)
        self.assertIn('image: "ghcr.io/google/cadvisor:0.56.2"', compose_text)
        self.assertIn('image: "grafana/loki:3.7.1"', compose_text)
        self.assertIn('image: "grafana/grafana:13.0.1"', compose_text)
        self.assertIn('image: "ollama/ollama:0.21.0"', compose_text)
        self.assertNotIn("portainer/portainer-ce:2.39.0-alpine", compose_text)
        self.assertNotIn("grafana/alloy:v1.13.2", compose_text)
        self.assertNotIn("prom/prometheus:v3.10.0", compose_text)
        self.assertNotIn("prom/node-exporter:v1.10.2", compose_text)
        self.assertNotIn("oliver006/redis_exporter:v1.81.0-alpine", compose_text)
        self.assertNotIn("redis:8.6.1-alpine", compose_text)
        self.assertNotIn("gcr.io/cadvisor/cadvisor:v0.55.1", compose_text)
        self.assertNotIn("grafana/loki:3.6.7", compose_text)
        self.assertNotIn("grafana/grafana:12.4.1", compose_text)
        self.assertNotIn("ollama/ollama:latest", compose_text)

    def test_alloy_persists_runtime_positions(self) -> None:
        """Verify alloy persists runtime positions.

        Inputs: none. Output: None.
        """
        compose_text = self.read_text("docker-compose.yml")
        alloy_service = compose_text.split("\n  alloy:\n", 1)[1].split(
            "\n  prometheus:\n", 1
        )[0]
        self.assertIn("--storage.path=/data-alloy", compose_text)
        self.assertIn(
            "${ALLOY_DATA_PATH:?Set ALLOY_DATA_PATH (run installation/installation_script.sh)}:/data-alloy:rw",
            alloy_service,
        )
        self.assertIn(
            "${OMERO_SERVER_LOGS_PATH:?Set OMERO_SERVER_LOGS_PATH (run installation/installation_script.sh)}:/logs/omeroserver:ro",
            alloy_service,
        )
        self.assertIn(
            "${OMERO_WEB_LOGS_PATH:?Set OMERO_WEB_LOGS_PATH (run installation/installation_script.sh)}:/logs/omeroweb:ro",
            alloy_service,
        )
        self.assertIn(
            "${OMERO_WEB_SUPERVISOR_LOGS_PATH:?Set OMERO_WEB_SUPERVISOR_LOGS_PATH (run installation/installation_script.sh)}:/logs/omeroweb-supervisor:ro",
            alloy_service,
        )
        self.assertNotIn(
            "${OMERO_SERVER_LOGS_PATH:?Set OMERO_SERVER_LOGS_PATH (run installation/installation_script.sh)}:/opt/omero/server/OMERO.server/var/log:ro",
            alloy_service,
        )

    def test_installation_script_manages_alloy_data_path_contract(self) -> None:
        """Verify installation script manages alloy data path contract.

        Inputs: none. Output: None.
        """
        script_text = self.read_text("installation/installation_script.sh")
        self.assertIn('ALLOY_DATA_PATH="${OMERO_DATA_PATH%/}/alloy_data"', script_text)
        self.assertIn(
            'ALLOY_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "alloy")',
            script_text,
        )
        self.assertIn(
            'ALLOY_UID="$(discover_container_default_id_or_die "${ALLOY_IMAGE}" "-u")',
            script_text,
        )
        self.assertIn(
            'chown_tree_or_die "${ALLOY_DATA_PATH}" "Alloy data directory" "${ALLOY_UID}" "${ALLOY_GID}"',
            script_text,
        )

    def test_compose_images_are_explicitly_tagged_and_never_latest(self) -> None:
        """Verify compose images are explicitly tagged and never latest.

        Inputs: none. Output: None.
        """
        compose_text = self.read_text("docker-compose.yml")
        image_refs = re.findall(r"^\s*image:\s*[\"']?([^\"'\n#]+)", compose_text, re.M)

        self.assertTrue(image_refs)
        for image_ref in image_refs:
            image_ref = image_ref.strip()
            image_without_digest = image_ref.split("@", 1)[0]
            tag = image_without_digest.rsplit(":", 1)[-1]
            self.assertIn(":", image_without_digest, image_ref)
            self.assertNotEqual("latest", tag, image_ref)

    def test_alpine_323_base_images_use_current_verified_digest(self) -> None:
        """Verify alpine 323 base images use current verified digest.

        Inputs: none. Output: None.
        """
        expected_from = (
            "FROM alpine:3.23@"
            "sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11"
        )
        for relative_path in (
            "docker/firewall-bouncer.Dockerfile",
            "docker/path-usage-exporter.Dockerfile",
            "docker/redis-sysctl-init.Dockerfile",
        ):
            with self.subTest(relative_path=relative_path):
                dockerfile_text = self.read_text(relative_path)
                self.assertIn(expected_from, dockerfile_text)
                self.assertNotIn(
                    "sha256:25109184c71bdad752c8312a8623239686a9a2071e8825f20acb8f2198c3f659",
                    dockerfile_text,
                )

    def test_omeroserver_dockerfile_fails_closed_without_dropbox_version(self) -> None:
        """Verify omeroserver dockerfile fails closed without dropbox version.

        Inputs: none. Output: None.
        """
        dockerfile_text = self.read_text("docker/omero-server.Dockerfile")
        self.assertIn("ARG OMERO_DROPBOX_VERSION\n", dockerfile_text)
        self.assertNotIn("ARG OMERO_DROPBOX_VERSION=", dockerfile_text)
        self.assertIn(
            "OMERO_DROPBOX_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn('"omero-dropbox==${OMERO_DROPBOX_VERSION}"', dockerfile_text)
        self.assertIn(
            '"${VENV_DIR}/bin/python" -c "import fsDropBox, fsMonitorServer"',
            dockerfile_text,
        )

    def test_omeroweb_dockerfile_fails_closed_without_version_args(self) -> None:
        """Verify omeroweb dockerfile fails closed without version args.

        Inputs: none. Output: None.
        """
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
        """Verify installation script generated dot environment includes server environment file.

        Inputs: none. Output: None.
        """
        script_text = self.read_text("installation/installation_script.sh")
        self.assertIn(
            "COMPOSE_ENV_FILES=installation_paths.env,env/omero_secrets.env,env/omeroserver.env,env/omeroweb.env,env/omero-celery.env,env/grafana.env",
            script_text,
        )
        self.assertIn("COMPOSE_PROJECT_NAME=${OMERO_COMPOSE_PROJECT_NAME}", script_text)
        self.assertIn("OMERO_DROPBOX_VERSION=${OMERO_DROPBOX_VERSION}", script_text)
        self.assertIn("OMERO_CLI_ZARR_VERSION=${OMERO_CLI_ZARR_VERSION}", script_text)
        self.assertIn("OME_ZARR_PY_VERSION=${OME_ZARR_PY_VERSION}", script_text)
        self.assertIn("BIOFORMATS2RAW_VERSION=${BIOFORMATS2RAW_VERSION}", script_text)
        self.assertIn("BIOFORMATS_VERSION=${BIOFORMATS_VERSION}", script_text)
        self.assertIn("OMERO_SERVER_HOST_PORT=${OMERO_SERVER_HOST_PORT}", script_text)
        self.assertIn("OMERO_CLI_HOST=${OMERO_CLI_HOST}", script_text)
        self.assertIn("OMERO_CLI_PORT=${OMERO_CLI_PORT}", script_text)
        self.assertIn('OMERO_WEB_HOST_PORT="${OMERO_WEB_HOST_PORT:-}"', script_text)
        self.assertIn(
            'CONFIG_omero_web_application__server_port="${CONFIG_omero_web_application__server_port:-}"',
            script_text,
        )
        self.assertIn("OMERO_WEB_HOST_PORT=${OMERO_WEB_HOST_PORT}", script_text)
        self.assertIn(
            "CONFIG_omero_web_application__server_port=${CONFIG_omero_web_application__server_port}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable OMERO_CLI_ZARR_VERSION in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable OMERO_DROPBOX_VERSION in ${server_env_source}",
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
        self.assertIn(
            "Missing required configuration variable BIOFORMATS_VERSION in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            'validate_tcp_port_config "OMERO_WEB_HOST_PORT"',
            script_text,
        )
        self.assertIn(
            'validate_tcp_port_config "CONFIG_omero_web_application__server_port"',
            script_text,
        )
        self.assertIn(
            'validate_tcp_port_config "OMERO_SERVER_HOST_PORT"',
            script_text,
        )
        self.assertIn(
            'validate_tcp_port_config "OMERO_CLI_PORT"',
            script_text,
        )
        self.assertIn('case "${variable_value}" in', script_text)
        self.assertNotIn('[[ "${variable_value}" =~ ^[0-9]+$ ]]', script_text)


if __name__ == "__main__":
    unittest.main()
