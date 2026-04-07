from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CrowdSecDockerfilePackageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dockerfile_text = (REPO_ROOT / "docker" / "crowdsec.Dockerfile").read_text(
            encoding="utf-8"
        )

    def test_crowdsec_installs_required_firewall_packages(self) -> None:
        for package_name in (
            "cs-firewall-bouncer",
            "nftables",
            "iptables",
            "ipset",
        ):
            self.assertIn(
                f'"{package_name}=$(require_apk_version {package_name})"',
                self.dockerfile_text,
            )

    def test_crowdsec_does_not_pin_nonexistent_ip6tables_package(self) -> None:
        self.assertNotIn(
            '"ip6tables=$(require_apk_version ip6tables)"',
            self.dockerfile_text,
        )
        self.assertIn(
            "no separate ip6tables package to install or pin here",
            self.dockerfile_text,
        )


if __name__ == "__main__":
    unittest.main()
