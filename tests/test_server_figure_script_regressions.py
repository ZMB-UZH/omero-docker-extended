import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DOCKERFILE = REPO_ROOT / "docker" / "omero-server.Dockerfile"
SERVER_BOOTSTRAP = REPO_ROOT / "startup" / "10-server-bootstrap.sh"


class ServerFigureScriptRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dockerfile = SERVER_DOCKERFILE.read_text(encoding="utf-8")
        cls.bootstrap = SERVER_BOOTSTRAP.read_text(encoding="utf-8")

    def test_server_image_bundles_figure_to_pdf_script(self):
        self.assertIn('ARG OME_OMERO_FIGURE_REPO="https://github.com/ome/omero-figure.git"', self.dockerfile)
        self.assertIn('ARG OME_OMERO_FIGURE_REF="7.3.1"', self.dockerfile)
        self.assertIn(
            "/opt/omero/server/OMERO.server/lib/scripts/omero/figure_scripts/Figure_To_Pdf.py",
            self.dockerfile,
        )

    def test_bootstrap_register_script_sync_skips_package_markers(self):
        self.assertIn(
            "if not file.endswith('.py') or file == '__init__.py':",
            self.bootstrap,
        )

    def test_bootstrap_requires_figure_version_env_var(self):
        self.assertIn(
            'echo "ERROR: OMERO_FIGURE_VERSION must be set in env/omeroserver.env and must not be empty." >&2',
            self.bootstrap,
        )
        self.assertNotIn('figure_version="7.3.0"', self.bootstrap)

    def test_bootstrap_installs_figure_script_before_registration(self):
        self.assertRegex(
            self.bootstrap,
            re.compile(
                r"configure_script_python\n"
                r"\s*ensure_certificate_sans\n"
                r"\s*install_figure_script\n"
                r"\s*schedule_script_registration\n",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
