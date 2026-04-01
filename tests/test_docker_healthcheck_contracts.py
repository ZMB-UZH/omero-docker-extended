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
        }

    def test_image_level_healthchecks_exist_for_hardened_auxiliary_images(self) -> None:
        expected_checks = {
            "omero-web": "curl -fsS http://127.0.0.1:4090/webgateway/ >/dev/null || exit 1",
            "omero-celery-worker": "/opt/venv/bin/python -c 'import celery, omeroweb_imaris_connector, omero_plugin_common' || exit 1",
            "pg-maintenance": "pgrep -x cron >/dev/null || exit 1",
            "crowdsec": "wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1",
            "firewall-bouncer": "test -x /usr/local/bin/custom-entrypoint.sh || exit 1",
            "path-usage-exporter": "test -f /textfile/omero_paths.prom || exit 1",
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

    def test_firewall_bouncer_runs_as_non_root_placeholder_image(self) -> None:
        dockerfile_text = self.dockerfiles["firewall-bouncer"]
        self.assertIn("addgroup -S firewallbouncer", dockerfile_text)
        self.assertIn("adduser -S -D -H -G firewallbouncer", dockerfile_text)
        self.assertIn("USER firewallbouncer", dockerfile_text)


if __name__ == "__main__":
    unittest.main()
