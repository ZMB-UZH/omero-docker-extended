from __future__ import annotations

import unittest
from pathlib import Path


_EXPECTED_HASHES = [
    "a755d0d82d51c3292bb7047b7bdfbb92"  # DevSkim: ignore DS173237
    + "c6f430b6d99cd91c463510b43b462e84",  # DevSkim: ignore DS173237 -- branding file content hash
    "fed3805fd27203cb1d2d80df346d625e"  # DevSkim: ignore DS173237
    + "e5b9fa127e7f5408c0ede31eeb148bc7",  # DevSkim: ignore DS173237 -- branding file content hash
    "4962acc5fbf52f8ef72721990487fdc9"  # DevSkim: ignore DS173237
    + "a1e76c862e8e0676acd4aa0dad867286",  # DevSkim: ignore DS173237 -- branding file content hash
]


class OmeroWebLogoBootstrapRegressionTests(unittest.TestCase):
    """Test cases for OMERO web logo bootstrap regression tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `OmeroWebLogoBootstrapRegressionTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.web_bootstrap_text = (
            cls.repo_root / "startup" / "10-web-bootstrap.sh"
        ).read_text(encoding="utf-8")

    def test_pull_scripts_preserve_site_local_logo_png(self) -> None:
        """Verify pull scripts preserve site local logo png.

        Inputs: repository fixtures. Output: fails on regressions in pull scripts preserve site local logo png.
        """
        scripts = [self.repo_root / "installation" / "github_pull_project_bash"]

        for script in scripts:
            script_text = script.read_text(encoding="utf-8")
            self.assertIn(
                'if [ -f "${current_repo_dir}/logo/logo.png" ]; then', script_text
            )
            self.assertIn('active_protected_files+=("logo/logo.png")', script_text)
            self.assertIn("clone_move_find_args+=( ! -name 'logo' )", script_text)

    def test_gitignore_keeps_real_logo_local_only(self) -> None:
        """Check that gitignore keeps real logo local only remains stable.

        Inputs: repository fixtures. Output: fails on regressions in gitignore keeps real logo local only.
        """
        gitignore_text = (self.repo_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/logo/logo.png", gitignore_text)

    def test_web_bootstrap_preserves_logo_and_does_not_fail_when_missing(self) -> None:
        """Confirm web bootstrap preserves logo and does not fail when missing exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions when web bootstrap preserves logo and does not fail when missing stops reporting the expected error.
        """
        self.assertIn("repair_branding_logo_permissions()", self.web_bootstrap_text)
        self.assertIn("branding_logo_fallback_enabled()", self.web_bootstrap_text)
        self.assertIn(
            "branding_logo_uses_generated_fallback()", self.web_bootstrap_text
        )
        self.assertIn("install_branding_logo_fallback()", self.web_bootstrap_text)
        self.assertIn(
            "clear_static_directory_for_backup_sync()", self.web_bootstrap_text
        )
        self.assertIn(
            'clear_static_directory_for_backup_sync "${static_dir}"',
            self.web_bootstrap_text,
        )
        self.assertIn(
            'find "${target_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +',
            self.web_bootstrap_text,
        )
        self.assertIn(
            "Refusing unsafe static directory cleanup target",
            self.web_bootstrap_text,
        )
        self.assertIn(
            "Refusing to clean symlinked static directory",
            self.web_bootstrap_text,
        )
        self.assertIn(
            'local branding_fallback_marker_path="${static_dir}/branding/.generated-logo-fallback"',
            self.web_bootstrap_text,
        )
        self.assertIn(
            'local configured_login_logo="${CONFIG_omero_web_login__logo:-}"',
            self.web_bootstrap_text,
        )
        self.assertIn(
            '[[ "${configured_login_logo}" = "/static/branding/logo.png" ]]',
            self.web_bootstrap_text,
        )
        self.assertIn(
            "if ! branding_logo_fallback_enabled; then", self.web_bootstrap_text
        )
        self.assertIn(
            "Preserving existing branding logo across static sync",
            self.web_bootstrap_text,
        )
        self.assertIn(
            "Restored pre-existing branding logo after static sync",
            self.web_bootstrap_text,
        )
        self.assertIn(
            "Restored branding logo from site-local logo path", self.web_bootstrap_text
        )
        self.assertIn(
            "WARNING: Branding logo missing after static sync", self.web_bootstrap_text
        )
        self.assertIn("Installing generated fallback icon", self.web_bootstrap_text)
        self.assertIn(
            "Installed generated branding fallback icon", self.web_bootstrap_text
        )
        self.assertIn(
            'rm -f "${branding_logo_path}" "${branding_fallback_marker_path}"',
            self.web_bootstrap_text,
        )
        self.assertNotIn(
            "ERROR: Branding logo missing after static sync", self.web_bootstrap_text
        )

    def test_web_bootstrap_repairs_branding_logo_permissions(self) -> None:
        """Verify web bootstrap repairs branding logo permissions.

        Inputs: repository fixtures. Output: fails on regressions in web bootstrap repairs branding logo permissions.
        """
        self.assertIn('chmod 0444 "${logo_path}"', self.web_bootstrap_text)
        self.assertIn(
            'chown "${runtime_user}:${runtime_group}" "${logo_path}"',
            self.web_bootstrap_text,
        )

    def test_web_bootstrap_uses_deterministic_fallback_writer(self) -> None:
        """Verify web bootstrap uses deterministic fallback writer.

        Inputs: repository fixtures. Output: fails on regressions in web bootstrap uses deterministic fallback writer.
        """
        self.assertIn(
            "/opt/omero/tools/write_branding_logo_fallback.py", self.web_bootstrap_text
        )
        self.assertIn(
            'cmp -s "${generated_fallback_path}" "${logo_path}"',
            self.web_bootstrap_text,
        )
        self.assertIn(
            "branding_logo_is_known_generated_fallback()", self.web_bootstrap_text
        )
        self.assertIn(
            "Refreshing legacy generated branding fallback icon",
            self.web_bootstrap_text,
        )
        self.assertIn(
            'if [[ ! -f "${logo_path}" || ! -f "${fallback_writer_path}" ]]; then',
            self.web_bootstrap_text,
        )
        self.assertIn('if [[ -f "${marker_path}" ]]; then', self.web_bootstrap_text)
        for expected_hash in _EXPECTED_HASHES:
            self.assertIn(expected_hash, self.web_bootstrap_text)

    def test_web_bootstrap_skips_zarr_jar_scan_until_cache_exists(self) -> None:
        """Verify web bootstrap skips Zarr jar scan until cache exists.

        Inputs: repository fixtures. Output: fails on regressions in web bootstrap skips Zarr jar scan until cache exists.
        """
        self.assertIn('local cache_root="${var_dir}/.cache"', self.web_bootstrap_text)
        self.assertIn('if [[ ! -d "${cache_root}" ]]; then', self.web_bootstrap_text)
        self.assertIn(
            "OMERO CLI cache directory not yet created; zarr JAR upgrade will apply on next container restart",
            self.web_bootstrap_text,
        )
        self.assertIn(
            'find "${cache_root}" -maxdepth 7 -type d -name "libs"',
            self.web_bootstrap_text,
        )


if __name__ == "__main__":
    unittest.main()
