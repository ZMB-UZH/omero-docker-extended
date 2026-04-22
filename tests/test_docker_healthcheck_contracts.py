from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class DockerHealthcheckContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose_text = (REPO_ROOT / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        cls.dockerfiles = {
            "omero-server": (
                REPO_ROOT / "docker" / "omero-server.Dockerfile"
            ).read_text(encoding="utf-8"),
            "omero-web": (REPO_ROOT / "docker" / "omero-web.Dockerfile").read_text(
                encoding="utf-8"
            ),
            "omero-celery-worker": (
                REPO_ROOT / "docker" / "omero-celery-worker.Dockerfile"
            ).read_text(encoding="utf-8"),
            "pg-maintenance": (
                REPO_ROOT / "docker" / "pg-maintenance.Dockerfile"
            ).read_text(encoding="utf-8"),
            "crowdsec": (REPO_ROOT / "docker" / "crowdsec.Dockerfile").read_text(
                encoding="utf-8"
            ),
            "firewall-bouncer": (
                REPO_ROOT / "docker" / "firewall-bouncer.Dockerfile"
            ).read_text(encoding="utf-8"),
            "path-usage-exporter": (
                REPO_ROOT / "docker" / "path-usage-exporter.Dockerfile"
            ).read_text(encoding="utf-8"),
            "redis-sysctl-init": (
                REPO_ROOT / "docker" / "redis-sysctl-init.Dockerfile"
            ).read_text(encoding="utf-8"),
        }
        cls.redis_sysctl_script = (
            REPO_ROOT / "docker" / "redis-sysctl-init.sh"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _last_user(dockerfile_text: str) -> str:
        users = [
            line.strip()
            for line in dockerfile_text.splitlines()
            if line.strip().startswith("USER ")
        ]
        if not users:
            return ""
        return users[-1]

    @staticmethod
    def _compose_service_text(compose_text: str, service_name: str) -> str:
        compose_lines = compose_text.splitlines(keepends=True)
        service_header = f"  {service_name}:\n"
        service_start = compose_lines.index(service_header)
        service_end = len(compose_lines)
        for index in range(service_start + 1, len(compose_lines)):
            line = compose_lines[index]
            if line.startswith("  ") and not line.startswith("    "):
                service_end = index
                break
        return "".join(compose_lines[service_start:service_end])

    def test_image_level_healthchecks_exist_for_hardened_auxiliary_images(self) -> None:
        expected_checks = {
            "omero-web": "curl -fsS http://127.0.0.1:4090/webgateway/ >/dev/null || exit 1",
            "omero-celery-worker": "/opt/venv/bin/python -c 'import celery, omeroweb_imaris_connector, omero_plugin_common' || exit 1",
            "pg-maintenance": "pgrep -x cron >/dev/null || exit 1",
            "crowdsec": "wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1",
            "firewall-bouncer": "test -x /usr/local/bin/custom-entrypoint.sh || exit 1",
            "path-usage-exporter": "test -f /textfile/omero_paths.prom || exit 1",
            "redis-sysctl-init": "test -x /usr/local/bin/redis-sysctl-init || exit 1",
        }
        for image_name, snippet in expected_checks.items():
            dockerfile_text = self.dockerfiles[image_name]
            self.assertIn("HEALTHCHECK", dockerfile_text)
            self.assertIn(snippet, dockerfile_text)

    def test_omeroweb_and_compose_share_the_same_runtime_health_probe(self) -> None:
        dockerfile_text = self.dockerfiles["omero-web"]
        probe = "curl -fsS http://127.0.0.1:4090/webgateway/ >/dev/null"
        self.assertIn(probe, dockerfile_text)
        self.assertIn(probe, self.compose_text)

    def test_crowdsec_and_compose_share_the_same_runtime_health_probe(self) -> None:
        dockerfile_text = self.dockerfiles["crowdsec"]
        probe = "wget --no-verbose --tries=1 --spider http://localhost:8080/health"
        self.assertIn(probe, dockerfile_text)
        self.assertIn(probe, self.compose_text)

    def test_omeroserver_healthcheck_uses_env_driven_helper(self) -> None:
        helper_text = (REPO_ROOT / "startup" / "healthcheck-omeroserver.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("/startup/healthcheck-omeroserver.sh", self.compose_text)
        self.assertIn("OMERO_CLI_USER is required", helper_text)
        self.assertIn("OMERO_TMPDIR is required", helper_text)
        self.assertIn("OMERODIR is required", helper_text)
        self.assertIn('OMERO_PASSWORD="${ROOTPASS}"', helper_text)
        self.assertIn('OMERO_PASSWORD="${OMERO_PASSWORD}"', helper_text)
        self.assertIn('runuser -u "${OMERO_CLI_USER}" -- env', helper_text)
        self.assertIn('TMPDIR="${OMERO_TMPDIR}"', helper_text)
        self.assertNotIn("HOME=/tmp", self.compose_text)
        self.assertNotIn("HOME=/tmp", helper_text)
        self.assertNotIn('-w "$$ROOTPASS"', self.compose_text)

    def test_firewall_bouncer_runs_as_non_root_placeholder_image(self) -> None:
        dockerfile_text = self.dockerfiles["firewall-bouncer"]
        self.assertIn("addgroup -S firewallbouncer", dockerfile_text)
        self.assertIn("adduser -S -D -H -G firewallbouncer", dockerfile_text)
        self.assertIn("USER firewallbouncer", dockerfile_text)

    def test_crowdsec_image_defaults_to_named_non_root_user(self) -> None:
        dockerfile_text = self.dockerfiles["crowdsec"]
        self.assertIn("addgroup -S crowdsec-runtime", dockerfile_text)
        self.assertIn("adduser -S -D -H -G crowdsec-runtime", dockerfile_text)
        self.assertIn("USER crowdsec-runtime", dockerfile_text)
        self.assertNotIn("USER root", dockerfile_text)

    def test_pg_maintenance_image_defaults_to_postgres_user(self) -> None:
        dockerfile_text = self.dockerfiles["pg-maintenance"]
        self.assertIn(
            "COPY maintenance/postgres/pg-maintenance-cron-runner",
            dockerfile_text,
        )
        self.assertIn("USER postgres", dockerfile_text)
        self.assertNotIn("USER root", dockerfile_text)

    def test_omero_server_image_defaults_to_application_user(self) -> None:
        dockerfile_text = self.dockerfiles["omero-server"]
        self.assertEqual("USER omero-server", self._last_user(dockerfile_text))
        self.assertIn("skipping root startup bootstrap", dockerfile_text)
        self.assertIn("runuser -p -m -u omero-server", dockerfile_text)
        self.assertIn("admin start --foreground", dockerfile_text)
        self.assertIn('exec "${omero_bin}" admin diagnostics', dockerfile_text)

    def test_omero_web_image_defaults_to_application_user(self) -> None:
        dockerfile_text = self.dockerfiles["omero-web"]
        self.assertEqual("USER omero-web", self._last_user(dockerfile_text))
        self.assertIn("skipping root startup bootstrap", dockerfile_text)
        self.assertIn("runuser -p -m -u omero-web", dockerfile_text)
        self.assertIn('exec \\"\\$@\\"', dockerfile_text)

    def test_root_required_helper_services_are_explicit_compose_handoffs(
        self,
    ) -> None:
        root_required_services = (
            "crowdsec",
            "omeroserver",
            "omeroweb",
            "pg-maintenance",
            "redis-sysctl-init",
        )
        for service_name in root_required_services:
            service_text = self._compose_service_text(self.compose_text, service_name)
            self.assertIn("    user: root\n", service_text)

    def test_redis_sysctl_init_image_defaults_to_named_non_root_user(self) -> None:
        dockerfile_text = self.dockerfiles["redis-sysctl-init"]
        self.assertIn("addgroup -S redis-sysctl", dockerfile_text)
        self.assertIn("adduser -S -D -H -G redis-sysctl", dockerfile_text)
        self.assertIn("USER redis-sysctl", dockerfile_text)
        self.assertNotIn("USER root", dockerfile_text)

    def test_redis_sysctl_init_script_fails_closed_on_sysctl_errors(self) -> None:
        self.assertIn(
            'SYSCTL_KEY="${SYSCTL_KEY:-vm.overcommit_memory}"', self.redis_sysctl_script
        )
        self.assertIn('SYSCTL_VALUE="${SYSCTL_VALUE:-1}"', self.redis_sysctl_script)
        self.assertIn(
            'if [ "${SYSCTL_KEY}" != "vm.overcommit_memory" ]; then',
            self.redis_sysctl_script,
        )
        self.assertIn(
            'sysctl -w "${SYSCTL_KEY}=${SYSCTL_VALUE}"', self.redis_sysctl_script
        )
        self.assertNotIn("|| true", self.redis_sysctl_script)


if __name__ == "__main__":
    unittest.main()
