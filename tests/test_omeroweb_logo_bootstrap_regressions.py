from __future__ import annotations

import unittest
from pathlib import Path


class OmeroWebLogoBootstrapRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.web_bootstrap_text = (cls.repo_root / "startup" / "10-web-bootstrap.sh").read_text(
            encoding="utf-8"
        )

    def test_pull_scripts_preserve_site_local_logo_png(self) -> None:
        public_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        private_text = (self.repo_root / "github_pull_private_project_bash_example").read_text(
            encoding="utf-8"
        )

        for script_text in (public_text, private_text):
            self.assertIn('if [ -f "${current_repo_dir}/logo/logo.png" ]; then', script_text)
            self.assertIn('active_protected_files+=("logo/logo.png")', script_text)
            self.assertIn('clone_move_find_args+=( ! -name \'logo\' )', script_text)

    def test_web_bootstrap_preserves_logo_and_does_not_fail_when_missing(self) -> None:
        self.assertIn("repair_branding_logo_permissions()", self.web_bootstrap_text)
        self.assertIn('Preserving existing branding logo across static sync', self.web_bootstrap_text)
        self.assertIn('Restored pre-existing branding logo after static sync', self.web_bootstrap_text)
        self.assertIn('Restored branding logo from repository logo path', self.web_bootstrap_text)
        self.assertIn('WARNING: Branding logo missing after static sync', self.web_bootstrap_text)
        self.assertNotIn('ERROR: Branding logo missing after static sync', self.web_bootstrap_text)

    def test_web_bootstrap_repairs_branding_logo_permissions(self) -> None:
        self.assertIn('chmod 0444 "${logo_path}"', self.web_bootstrap_text)
        self.assertIn('chown "${runtime_user}:${runtime_group}" "${logo_path}"', self.web_bootstrap_text)


if __name__ == "__main__":
    unittest.main()
