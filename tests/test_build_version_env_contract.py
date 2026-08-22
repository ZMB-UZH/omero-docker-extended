"""Regression tests for build-time version env contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class BuildVersionEnvContractTests(unittest.TestCase):
    """Test cases for build version env contract tests."""

    FORBIDDEN_FLOATING_IMAGE_TAGS = frozenset(
        {"latest", "stable", "edge", "main", "master", "nightly", "rolling", "current"}
    )

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `BuildVersionEnvContractTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]

    def read_text(self, relative_path: str) -> str:
        """Return `BuildVersionEnvContractTests`'s configured text fixture.

        Inputs: `relative_path`. Output: `str`.
        """
        return (self.repo_root / relative_path).read_text(encoding="utf-8")

    def assert_explicit_nonfloating_image_ref(self, image_ref: str) -> None:
        """Verify an image reference is explicit and not a floating alias.

        Inputs: `image_ref` Docker image reference. Output: fails on unpinned or floating tags.
        """
        normalized = image_ref.strip().strip("\"'")
        if normalized == "scratch":
            return
        image_without_digest = normalized.split("@", 1)[0]
        self.assertIn(":", image_without_digest, normalized)
        tag = image_without_digest.rsplit(":", 1)[-1].lower()
        self.assertNotIn(tag, self.FORBIDDEN_FLOATING_IMAGE_TAGS, normalized)

    def test_installation_paths_example_excludes_build_version_pins(self) -> None:
        """Verify installation paths example excludes build version pins.

        Inputs: repository fixtures. Output: fails on regressions in installation paths example excludes build version pins.
        """
        env_text = self.read_text("installation_paths_example.env")
        self.assertNotIn("OMERO_CLI_ZARR_VERSION=", env_text)
        self.assertNotIn("OME_ZARR_PY_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS2RAW_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS2RAW_SHA256=", env_text)
        self.assertNotIn("TIFFFILE_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS_VERSION=", env_text)
        self.assertNotIn("BIOFORMATS_SHA256=", env_text)

    def test_omeroserver_example_defines_native_zarr_build_versions(self) -> None:
        """Verify omeroserver example defines native Zarr build versions.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver example defines native Zarr build versions.
        """
        env_text = self.read_text("env/omeroserver_example.env")
        self.assertIn("OMERO_DROPBOX_VERSION=5.7.0", env_text)
        self.assertIn("OMERO_CLI_HOST=localhost", env_text)
        self.assertIn("OMERO_CLI_PORT=4064", env_text)
        self.assertIn("OMERO_SERVER_HOST_PORT=4064", env_text)
        self.assertIn("OMERO_JOB_SERVICE_HOST=localhost", env_text)
        self.assertIn("OMERO_JOB_SERVICE_PORT=4064", env_text)
        self.assertIn("OMERO_CLI_ZARR_VERSION=0.8.0", env_text)
        self.assertIn("OME_ZARR_PY_VERSION=0.16.0", env_text)
        self.assertIn("BIOFORMATS2RAW_VERSION=0.12.1", env_text)
        self.assertIn(
            "BIOFORMATS2RAW_SHA256=51fbbf04a83c2042b707fce016ad0c8260d37194ff8fe7d986d53f4ebee116a6",
            env_text,
        )
        self.assertIn(
            "2026.3.3 is the newest compatible release",
            env_text,
        )
        self.assertIn("TIFFFILE_VERSION=2026.3.3", env_text)
        self.assertIn("BIOFORMATS_VERSION=8.5.0", env_text)
        self.assertIn(
            "BIOFORMATS_SHA256=978093f2a4d0034f9581b19a5acd5a53c56d7b04b703865cd533aa953c92b1c2",
            env_text,
        )

    def test_compose_requires_build_versions_from_omeroserver_env(self) -> None:
        """Verify compose requires build versions from omeroserver env.

        Inputs: repository fixtures. Output: fails on regressions in compose requires build versions from omeroserver env.
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
            'BIOFORMATS2RAW_SHA256: "${BIOFORMATS2RAW_SHA256:?Set BIOFORMATS2RAW_SHA256 in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            'TIFFFILE_VERSION: "${TIFFFILE_VERSION:?Set TIFFFILE_VERSION in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            'BIOFORMATS_VERSION: "${BIOFORMATS_VERSION:?Set BIOFORMATS_VERSION in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            'BIOFORMATS_SHA256: "${BIOFORMATS_SHA256:?Set BIOFORMATS_SHA256 in env/omeroserver.env}"',
            compose_text,
        )
        self.assertIn(
            "${OMERO_SERVER_HOST_PORT:?Set OMERO_SERVER_HOST_PORT in env/omeroserver.env}:${OMERO_CLI_PORT:?Set OMERO_CLI_PORT in env/omeroserver.env}",
            compose_text,
        )

    def test_compose_pins_monitoring_and_management_image_versions(self) -> None:
        """Verify compose pins monitoring and management image versions.

        Inputs: repository fixtures. Output: fails on regressions in compose pins monitoring and management image versions.
        """
        compose_text = self.read_text("docker-compose.yml")
        self.assertIn('image: "portainer/portainer-ce:2.44.0-alpine"', compose_text)
        self.assertIn('image: "grafana/alloy:v1.18.1"', compose_text)
        self.assertIn('image: "prom/prometheus:v3.14.0"', compose_text)
        self.assertIn('image: "prom/node-exporter:v1.12.1"', compose_text)
        self.assertIn(
            'image: "prometheuscommunity/postgres-exporter:v0.20.1"',
            compose_text,
        )
        self.assertIn('image: "oliver006/redis_exporter:v1.89.0-alpine"', compose_text)
        self.assertIn('image: "redis:8.10.1-alpine"', compose_text)
        self.assertIn('image: "ghcr.io/google/cadvisor:0.60.5"', compose_text)
        self.assertIn('image: "grafana/loki:3.7.6"', compose_text)
        self.assertIn('image: "grafana/grafana:13.2.0"', compose_text)
        self.assertIn('image: "ollama/ollama:0.32.15"', compose_text)
        self.assertNotIn("portainer/portainer-ce:2.39.0-alpine", compose_text)
        self.assertNotIn("grafana/alloy:v1.17.1", compose_text)
        self.assertNotIn("prom/prometheus:v3.12.0", compose_text)
        self.assertNotIn("prom/node-exporter:v1.11.1", compose_text)
        self.assertNotIn("prometheuscommunity/postgres-exporter:v0.19.1", compose_text)
        self.assertNotIn("oliver006/redis_exporter:v1.86.0-alpine", compose_text)
        self.assertNotIn("redis:8.6.4-alpine", compose_text)
        self.assertNotIn("ghcr.io/google/cadvisor:0.60.3", compose_text)
        self.assertNotIn("grafana/loki:3.6.7", compose_text)
        self.assertNotIn("grafana/grafana:13.1.0", compose_text)
        self.assertNotIn("ollama/ollama:0.32.2", compose_text)

    def test_portainer_management_surface_is_https_only_and_hardened(self) -> None:
        """Verify Portainer is default-on, HTTPS-only, and container-hardened.

        Inputs: repository fixtures. Output: fails on regressions in Portainer
        exposure, Docker socket access, or hardened runtime options.
        """

        compose_text = self.read_text("docker-compose.yml")
        portainer_service = compose_text.split("\n  portainer:\n", 1)[1].split(
            "\n  loki:\n", 1
        )[0]
        prometheus_text = self.read_text("monitoring/prometheus/prometheus.yml")
        dot_env_text = self.read_text(".env_example")

        self.assertNotIn("profiles:", portainer_service)
        self.assertIn(
            '- "${PORTAINER_HOST_BIND:-0.0.0.0}:9443:9443"',
            portainer_service,
        )
        self.assertNotIn(":9000", portainer_service)
        self.assertIn("--http-disabled", portainer_service)
        self.assertIn("--bind-https=:9443", portainer_service)
        self.assertIn("--tunnel-addr=127.0.0.1", portainer_service)
        self.assertIn("--csp", portainer_service)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock:ro", portainer_service)
        self.assertIn("read_only: true", portainer_service)
        self.assertIn("init: true", portainer_service)
        self.assertIn("- /tmp:size=64m,mode=1777", portainer_service)
        self.assertIn("cap_drop:", portainer_service)
        self.assertIn("- ALL", portainer_service)
        self.assertIn("no-new-privileges:true", portainer_service)
        self.assertIn(
            '["CMD", "/bin/busybox", "nc", "-z", "-w", "2", "127.0.0.1", "9443"]',
            portainer_service,
        )
        self.assertNotIn("https://localhost:9443", portainer_service)
        self.assertIn("PORTAINER_HOST_BIND=0.0.0.0", dot_env_text)
        self.assertIn(
            "https://portainer:9443/api/system/status",
            prometheus_text,
        )
        self.assertNotIn("portainer:9000/api/system/status", prometheus_text)

    def test_alloy_persists_runtime_positions(self) -> None:
        """Verify alloy persists runtime positions.

        Inputs: repository fixtures. Output: fails on regressions in alloy persists runtime positions.
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
        """Verify the installation script manages alloy data path contract execution contract.

        Inputs: repository fixtures. Output: fails on regressions when installation script manages alloy data path contract accepts unsafe input.
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

    def test_installation_script_manages_portainer_data_path_contract(self) -> None:
        """Verify installer prepares Portainer data with image runtime ownership.

        Inputs: repository fixtures. Output: fails on regressions in Portainer
        UID/GID discovery or data-directory ownership preparation.
        """

        script_text = self.read_text("installation/installation_script.sh")
        self.assertIn('PORTAINER_UID="${PORTAINER_UID:-}"', script_text)
        self.assertIn('PORTAINER_GID="${PORTAINER_GID:-}"', script_text)
        self.assertIn('PORTAINER_IMAGE="${PORTAINER_IMAGE:-}"', script_text)
        self.assertIn(
            'PORTAINER_IMAGE="$(resolve_service_image_from_compose_or_die "${COMPOSE_FILE}" "portainer")',
            script_text,
        )
        self.assertIn(
            'PORTAINER_UID="$(discover_container_default_id_or_die "${PORTAINER_IMAGE}" "-u")',
            script_text,
        )
        self.assertIn(
            'PORTAINER_GID="$(discover_container_default_id_or_die "${PORTAINER_IMAGE}" "-g")',
            script_text,
        )
        self.assertIn(
            'chown_tree_or_die "${PORTAINER_DATA_PATH}" "Portainer data directory" "${PORTAINER_UID}" "${PORTAINER_GID}"',
            script_text,
        )

    def test_compose_images_are_explicitly_tagged_and_never_floating(self) -> None:
        """Verify compose images are explicitly tagged and never floating.

        Inputs: repository fixtures. Output: fails on regressions in compose images are explicitly tagged and never floating.
        """
        compose_text = self.read_text("docker-compose.yml")
        image_refs = re.findall(r"^\s*image:\s*[\"']?([^\"'\n#]+)", compose_text, re.M)

        self.assertTrue(image_refs)
        for image_ref in image_refs:
            self.assert_explicit_nonfloating_image_ref(image_ref)

    def test_dockerfile_bases_are_explicitly_tagged_and_never_floating(self) -> None:
        """Verify Dockerfile bases are explicitly tagged and never floating.

        Inputs: repository fixtures. Output: fails on regressions in Dockerfile base image pinning.
        """
        for dockerfile_path in sorted((self.repo_root / "docker").glob("*.Dockerfile")):
            dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
            from_refs = re.findall(r"^\s*FROM\s+([^\s#]+)", dockerfile_text, re.M)
            self.assertTrue(from_refs, str(dockerfile_path))
            for image_ref in from_refs:
                with self.subTest(dockerfile=dockerfile_path.name, image_ref=image_ref):
                    self.assert_explicit_nonfloating_image_ref(image_ref)

    def test_workflow_container_images_are_explicitly_tagged_and_never_floating(
        self,
    ) -> None:
        """Verify workflow container images are explicitly tagged and never floating.

        Inputs: repository fixtures. Output: fails on regressions in workflow container pinning.
        """
        for workflow_path in sorted(
            (self.repo_root / ".github" / "workflows").glob("*")
        ):
            if workflow_path.suffix not in {".yml", ".yaml"}:
                continue
            workflow_text = workflow_path.read_text(encoding="utf-8")
            image_refs = re.findall(r"^\s*image:\s*([^\s#]+)", workflow_text, re.M)
            for image_ref in image_refs:
                with self.subTest(workflow=workflow_path.name, image_ref=image_ref):
                    self.assert_explicit_nonfloating_image_ref(image_ref)

    def test_alpine_324_base_images_use_current_verified_digest(self) -> None:
        """Verify alpine 324 base images use current verified digest.

        Inputs: repository fixtures. Output: fails on regressions in alpine 323 base images use current verified digest.
        """
        expected_from = (
            "FROM alpine:3.24.1@"
            "sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b"
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
                    "sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11",
                    dockerfile_text,
                )

    def test_ubuntu_2604_base_images_use_current_verified_digest(self) -> None:
        """Verify Ubuntu 26.04 base images use current verified digest.

        Inputs: repository fixtures. Output: fails on regressions in Ubuntu base image pins.
        """
        dockerfile_text = self.read_text("docker/omero-celery-worker.Dockerfile")
        self.assertIn(
            "FROM ubuntu:26.04@"
            "sha256:2260313b31c8c011cd2eebe728008efac1b3982be73eb71348ea2648d2c0e09b",
            dockerfile_text,
        )
        self.assertNotIn(
            "sha256:53958ec7b67c2c9355df922dd08dbf0360611f8c3cdb656875e81873db9ffdba",
            dockerfile_text,
        )

    def test_postgres_1615_base_image_uses_current_verified_digest(self) -> None:
        """Verify the PostgreSQL 16.15 maintenance base uses its current digest.

        Inputs: repository fixtures. Output: fails on stale PostgreSQL digests.
        """

        dockerfile_text = self.read_text("docker/pg-maintenance.Dockerfile")
        self.assertIn(
            "FROM postgres:16.15@"
            "sha256:e17e86066e5ef83e0952a9347f5c792b7ece00972e2aa787a6986f471b3dd3d5",
            dockerfile_text,
        )
        self.assertNotIn(
            "sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b",
            dockerfile_text,
        )

    def test_postgres_runtime_images_match_maintenance_version(self) -> None:
        """Verify both database services match the maintenance client version.

        Inputs: repository fixtures. Output: fails on PostgreSQL version drift.
        """

        compose_text = self.read_text("docker-compose.yml")
        self.assertEqual(compose_text.count('image: "postgres:16.15"'), 2)

    def test_omero_base_images_use_current_verified_digests(self) -> None:
        """Verify OMERO base images use current verified digests.

        Inputs: repository fixtures. Output: fails on regressions in OMERO base image pins.
        """
        expected_from_by_path = {
            "docker/omero-server.Dockerfile": (
                "FROM openmicroscopy/omero-server:5.6.18@"
                "sha256:895317a8dba185da6a08fe412d337e62fb6bbb9f6579d33e485439020a43217f"
            ),
            "docker/omero-web.Dockerfile": (
                "FROM openmicroscopy/omero-web-standalone:5.33.0-1@"
                "sha256:fac13ff1f14ee29c610091b1e0a8c717583a43c4256efadedae5685c4f4eedb4"
            ),
        }
        for relative_path, expected_from in expected_from_by_path.items():
            with self.subTest(relative_path=relative_path):
                dockerfile_text = self.read_text(relative_path)
                self.assertIn(expected_from, dockerfile_text)

    def test_omero_python_api_pin_matches_updated_server_stack(self) -> None:
        """Verify OMERO Python API pins match the updated OMERO server stack.

        Inputs: repository fixtures. Output: fails on stale omero-py pins.
        """
        expected_pin = '"omero-py==5.23.0"'
        web_dockerfile_text = self.read_text("docker/omero-web.Dockerfile")
        worker_dockerfile_text = self.read_text("docker/omero-celery-worker.Dockerfile")
        server_dockerfile_text = self.read_text("docker/omero-server.Dockerfile")

        self.assertIn(expected_pin, web_dockerfile_text)
        self.assertIn(
            expected_pin,
            worker_dockerfile_text,
        )
        for package_pin in (
            "django==5.2.17",
            "matplotlib==3.11.1",
            "pytest==9.1.1",
            "portalocker==4.2.0",
            "psycopg2-binary==2.9.12",
            "celery==5.6.3",
            "redis==8.1.0",
            "django-redis==7.0.0",
            "omero-fpbioimage==0.4.1",
            "omero-gallery==3.4.3",
            "omero-parade==0.2.4",
            "omero-web-zarr==0.1.1",
        ):
            with self.subTest(package_pin=package_pin):
                self.assertIn(package_pin, web_dockerfile_text)
        self.assertIn('"redis==8.1.0"', worker_dockerfile_text)
        self.assertIn("pytest==9.1.1", server_dockerfile_text)
        self.assertNotIn("redis==5.0.8", web_dockerfile_text)
        self.assertNotIn("redis==5.0.8", worker_dockerfile_text)
        self.assertNotIn("pytest==7.4.4", server_dockerfile_text)
        self.assertNotIn("django-redis>=", web_dockerfile_text)

    def test_omero_image_direct_python_dependencies_are_exactly_pinned(self) -> None:
        """Verify direct image dependencies cannot resolve to changing versions.

        Inputs: repository fixtures. Output: verifies exact package and temporary
        directory defaults in every OMERO application image.
        """
        server_text = self.read_text("docker/omero-server.Dockerfile")
        web_text = self.read_text("docker/omero-web.Dockerfile")
        worker_text = self.read_text("docker/omero-celery-worker.Dockerfile")

        common_version_args = (
            "ARG PIP_VERSION=26.2.1",
            "ARG SETUPTOOLS_VERSION=80.10.2",
            "ARG WHEEL_VERSION=0.48.0",
            "ARG CRYPTOGRAPHY_VERSION=50.0.0",
            "ARG URLLIB3_VERSION=2.7.0",
            "ARG CERTIFI_VERSION=2026.7.22",
            "ARG IDNA_VERSION=3.19",
            "ARG REQUESTS_VERSION=2.34.2",
            "ARG JINJA2_VERSION=3.1.6",
        )
        for dockerfile_text in (server_text, web_text, worker_text):
            for version_arg in common_version_args:
                with self.subTest(version_arg=version_arg):
                    self.assertIn(version_arg, dockerfile_text)
            self.assertIn("TMPDIR=/tmp", dockerfile_text)
            self.assertIn("OMERO_TMPDIR=/tmp", dockerfile_text)

        combined_text = "\n".join((server_text, web_text, worker_text))
        self.assertIn("pkg_resources", combined_text)
        self.assertNotRegex(
            combined_text,
            r"ARG SETUPTOOLS_VERSION=(?:8[1-9]|9[0-9])(?:\.|$)",
        )

        for version_arg in (
            "ARG PYOPENSSL_VERSION=26.4.0",
            "ARG REPORTLAB_VERSION=5.0.1",
            "ARG MARKDOWN_VERSION=3.10.3",
            "ARG OMERO_CLI_RENDER_VERSION=0.8.1",
            "ARG OMERO_METADATA_VERSION=0.14.0",
            "ARG OMERO_CLI_DUPLICATE_VERSION=0.4.0",
            "ARG OMERO_RDF_VERSION=0.7.2",
        ):
            with self.subTest(version_arg=version_arg):
                self.assertIn(version_arg, server_text)

        self.assertIn("ARG PYOPENSSL_VERSION=26.4.0", web_text)
        self.assertNotRegex(
            "\n".join((server_text, web_text, worker_text)),
            r"(?m)^\s+(pip|setuptools|wheel|cryptography|urllib3|certifi|idna|requests|jinja2)(?:\s+\\)?$",
        )
        self.assertNotRegex(
            server_text,
            r"(?m)^\s+(reportlab|markdown|omero-cli-render|omero-metadata|omero-cli-duplicate|omero-rdf)(?:\s+\\|;)?$",
        )

    def test_omeroserver_dockerfile_fails_closed_without_dropbox_version(self) -> None:
        """Confirm omeroserver dockerfile fails closed without dropbox version exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver dockerfile fails closed without dropbox version.
        """
        dockerfile_text = self.read_text("docker/omero-server.Dockerfile")
        self.assertIn("ARG OMERO_DROPBOX_VERSION\n", dockerfile_text)
        self.assertIn("ARG TIFFFILE_VERSION\n", dockerfile_text)
        self.assertIn("ARG BIOFORMATS_SHA256\n", dockerfile_text)
        self.assertNotIn("ARG OMERO_DROPBOX_VERSION=", dockerfile_text)
        self.assertNotIn("ARG TIFFFILE_VERSION=", dockerfile_text)
        self.assertNotIn("ARG BIOFORMATS_SHA256=", dockerfile_text)
        self.assertIn(
            "OMERO_DROPBOX_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn(
            "TIFFFILE_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn(
            "BIOFORMATS_SHA256 must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn('"omero-dropbox==${OMERO_DROPBOX_VERSION}"', dockerfile_text)
        self.assertIn('"tifffile==${TIFFFILE_VERSION}"', dockerfile_text)
        self.assertIn(
            '"${VENV_DIR}/bin/python" -c "import fsDropBox, fsMonitorServer"',
            dockerfile_text,
        )

    def test_omeroweb_dockerfile_fails_closed_without_version_args(self) -> None:
        """Confirm omeroweb dockerfile fails closed without version args exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in omeroweb dockerfile fails closed without version args.
        """
        dockerfile_text = self.read_text("docker/omero-web.Dockerfile")
        self.assertIn("ARG OMERO_CLI_ZARR_VERSION\n", dockerfile_text)
        self.assertIn("ARG OME_ZARR_PY_VERSION\n", dockerfile_text)
        self.assertIn("ARG BIOFORMATS2RAW_VERSION\n", dockerfile_text)
        self.assertIn("ARG BIOFORMATS2RAW_SHA256\n", dockerfile_text)
        self.assertIn("ARG TIFFFILE_VERSION\n", dockerfile_text)
        self.assertNotIn("ARG OMERO_CLI_ZARR_VERSION=", dockerfile_text)
        self.assertNotIn("ARG OME_ZARR_PY_VERSION=", dockerfile_text)
        self.assertNotIn("ARG BIOFORMATS2RAW_VERSION=", dockerfile_text)
        self.assertNotIn("ARG BIOFORMATS2RAW_SHA256=", dockerfile_text)
        self.assertNotIn("ARG TIFFFILE_VERSION=", dockerfile_text)
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
        self.assertIn(
            "BIOFORMATS2RAW_SHA256 must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn(
            "TIFFFILE_VERSION must be provided from env/omeroserver.env",
            dockerfile_text,
        )
        self.assertIn('"tifffile==${TIFFFILE_VERSION}"', dockerfile_text)

    def test_omeroweb_uses_isolated_supported_bioformats2raw_java(self) -> None:
        """Verify bioformats2raw runs on Java 17 without changing the image-wide Java default.

        Inputs: Dockerfile and launcher fixtures. Output: fails on converter runtime regressions.
        """
        dockerfile_text = self.read_text("docker/omero-web.Dockerfile")
        launcher_text = self.read_text("docker/bioformats2raw-launcher.sh")

        self.assertIn("java-17-openjdk-headless", dockerfile_text)
        self.assertIn(
            'BASE_JAVA="$(readlink -e "$(command -v java)")"',
            dockerfile_text,
        )
        self.assertIn('alternatives --set java "${BASE_JAVA}"', dockerfile_text)
        self.assertIn(
            'java -version 2>&1 | grep -F \'1.8.0\' >/dev/null',
            dockerfile_text,
        )
        self.assertIn(
            "COPY docker/bioformats2raw-launcher.sh /tmp/bioformats2raw-launcher.sh",
            dockerfile_text,
        )
        self.assertIn(
            "install -o root -g root -m 0755 /tmp/bioformats2raw-launcher.sh "
            "/usr/local/bin/bioformats2raw",
            dockerfile_text,
        )
        self.assertNotIn("ENV JAVA_HOME=", dockerfile_text)
        self.assertIn('readonly java_home="/usr/lib/jvm/jre-17-openjdk"', launcher_text)
        self.assertIn('export JAVA_HOME="${java_home}"', launcher_text)
        self.assertIn('exec "${converter}" "$@"', launcher_text)

    def test_omeroweb_dockerfile_installs_single_pinned_vizarr_build(self) -> None:
        """Verify omeroweb dockerfile installs single pinned Vizarr build.

        Inputs: repository fixtures. Output: fails on regressions in Vizarr static install guard.
        """
        dockerfile_text = self.read_text("docker/omero-web.Dockerfile")

        self.assertIn("COPY third_party /tmp/third_party", dockerfile_text)
        self.assertIn("find /tmp/third_party -mindepth 1 -maxdepth 1", dockerfile_text)
        self.assertIn("Expected exactly one vendored Vizarr build", dockerfile_text)
        self.assertIn("^[0-9a-f]{40}$", dockerfile_text)
        self.assertIn(
            "Vendored Vizarr build must not contain source maps", dockerfile_text
        )
        self.assertIn(
            '"/tmp/omero_web_zarr/static/omero_web_zarr/vendor/vizarr/${VIZARR_COMMIT}"',
            dockerfile_text,
        )
        self.assertIn("OMEROWEB_ZARR_STATIC_SOURCE=", dockerfile_text)
        self.assertIn("OMEROWEB_ZARR_STATIC_TARGET=", dockerfile_text)
        self.assertIn('rm -rf "${OMEROWEB_ZARR_STATIC_TARGET}"', dockerfile_text)
        self.assertIn('mkdir -p "${OMEROWEB_ZARR_STATIC_TARGET}"', dockerfile_text)
        self.assertIn(
            'cp -a "${OMEROWEB_ZARR_STATIC_SOURCE}/." "${OMEROWEB_ZARR_STATIC_TARGET}/"',
            dockerfile_text,
        )
        self.assertIn(
            'chown -R omero-web:omero-web "${OMEROWEB_ZARR_STATIC_TARGET}"',
            dockerfile_text,
        )

    def test_installation_script_generated_dot_env_includes_server_env_file(
        self,
    ) -> None:
        """Verify the installation script generated dot env includes server env file execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script generated dot env includes server env file integration.
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
        self.assertIn("BIOFORMATS2RAW_SHA256=${BIOFORMATS2RAW_SHA256}", script_text)
        self.assertIn("TIFFFILE_VERSION=${TIFFFILE_VERSION}", script_text)
        self.assertIn("BIOFORMATS_VERSION=${BIOFORMATS_VERSION}", script_text)
        self.assertIn("BIOFORMATS_SHA256=${BIOFORMATS_SHA256}", script_text)
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
            "Missing required configuration variable BIOFORMATS2RAW_SHA256 in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable TIFFFILE_VERSION in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable BIOFORMATS_VERSION in ${server_env_source}",
            script_text,
        )
        self.assertIn(
            "Missing required configuration variable BIOFORMATS_SHA256 in ${server_env_source}",
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
