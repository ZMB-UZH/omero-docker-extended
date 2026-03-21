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
        self.assertIn("branding_logo_fallback_enabled()", self.web_bootstrap_text)
        self.assertIn("branding_logo_uses_generated_fallback()", self.web_bootstrap_text)
        self.assertIn("install_branding_logo_fallback()", self.web_bootstrap_text)
        self.assertIn('local branding_fallback_marker_path="${static_dir}/branding/.generated-logo-fallback"', self.web_bootstrap_text)
        self.assertIn('local configured_login_logo="${CONFIG_omero_web_login__logo:-}"', self.web_bootstrap_text)
        self.assertIn('[[ "${configured_login_logo}" == "/static/branding/logo.png" ]]', self.web_bootstrap_text)
        self.assertIn('if ! branding_logo_fallback_enabled; then', self.web_bootstrap_text)
        self.assertIn('Preserving existing branding logo across static sync', self.web_bootstrap_text)
        self.assertIn('Restored pre-existing branding logo after static sync', self.web_bootstrap_text)
        self.assertIn('Restored branding logo from repository logo path', self.web_bootstrap_text)
        self.assertIn('WARNING: Branding logo missing after static sync', self.web_bootstrap_text)
        self.assertIn('Installing generated fallback icon', self.web_bootstrap_text)
        self.assertIn('Installed generated branding fallback icon', self.web_bootstrap_text)
        self.assertIn('rm -f "${branding_logo_path}" "${branding_fallback_marker_path}"', self.web_bootstrap_text)
        self.assertNotIn('ERROR: Branding logo missing after static sync', self.web_bootstrap_text)

    def test_web_bootstrap_repairs_branding_logo_permissions(self) -> None:
        self.assertIn('chmod 0444 "${logo_path}"', self.web_bootstrap_text)
        self.assertIn('chown "${runtime_user}:${runtime_group}" "${logo_path}"', self.web_bootstrap_text)

    def test_web_bootstrap_uses_deterministic_fallback_writer(self) -> None:
        self.assertIn('/opt/omero/tools/write_branding_logo_fallback.py', self.web_bootstrap_text)
        self.assertIn('cmp -s "${generated_fallback_path}" "${logo_path}"', self.web_bootstrap_text)


if __name__ == "__main__":
    unittest.main()
