from __future__ import annotations

import unittest
from pathlib import Path


class OmeroWebLogoFallbackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_omeroweb_dockerfile_copies_logo_fallback_writer(self) -> None:
        dockerfile_text = (
            self.repo_root / "docker" / "omero-web.Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "COPY tools/write_branding_logo_fallback.py /opt/omero/tools/write_branding_logo_fallback.py",
            dockerfile_text,
        )

    def test_web_bootstrap_uses_logo_fallback_writer_path(self) -> None:
        bootstrap_text = (self.repo_root / "startup" / "10-web-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'local fallback_writer_path="/opt/omero/tools/write_branding_logo_fallback.py"',
            bootstrap_text,
        )


if __name__ == "__main__":
    unittest.main()
