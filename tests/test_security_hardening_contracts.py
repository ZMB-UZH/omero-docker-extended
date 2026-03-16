import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DOCKERFILE = REPO_ROOT / "docker" / "omero-server.Dockerfile"
WEB_DOCKERFILE = REPO_ROOT / "docker" / "omero-web.Dockerfile"
INSTALLATION_SCRIPT = REPO_ROOT / "installation" / "installation_script.sh"


class SecurityHardeningContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_dockerfile = SERVER_DOCKERFILE.read_text(encoding="utf-8")
        cls.web_dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
        cls.installation_script = INSTALLATION_SCRIPT.read_text(encoding="utf-8")

    def test_locale_data_is_preserved_while_other_hardening_stays_enabled(self):
        self.assertNotIn("langpacks-en", self.server_dockerfile)
        self.assertNotIn("glibc-langpack-en", self.server_dockerfile)
        self.assertNotIn("localedef --list-archive", self.server_dockerfile)
        self.assertNotIn("/usr/share/i18n/locales", self.server_dockerfile)
        self.assertNotIn("langpacks-en", self.web_dockerfile)
        self.assertNotIn("glibc-langpack-en", self.web_dockerfile)
        self.assertIn('echo "=== Final security hardening: OS packages (dnf) ==="; \\', self.server_dockerfile)
        self.assertIn('echo "=== Final security hardening: Python packages (pip) ==="; \\', self.server_dockerfile)
        self.assertIn('find /usr/lib64 /usr/lib -type f -name "*.so*" -exec strip --strip-unneeded {} 2>/dev/null \\; || true', self.server_dockerfile)

    def test_security_hardening_prompt_defaults_yes_while_scout_stays_opt_in(self):
        self.assertIn('APPLY_SECURITY_HARDENING="${APPLY_SECURITY_HARDENING:-}"', self.installation_script)
        self.assertIn('ENABLE_VULNERABILITY_SCAN="${ENABLE_VULNERABILITY_SCAN:-0}"', self.installation_script)
        self.assertRegex(
            self.installation_script,
            re.compile(
                r'if \[ -n "\$\{APPLY_SECURITY_HARDENING\}" \]; then\s+'
                r'if ! validate_toggle_config "APPLY_SECURITY_HARDENING" "\$\{APPLY_SECURITY_HARDENING\}"; then\s+'
                r'exit 1\s+'
                r'fi\s+'
                r'fi',
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            self.installation_script,
            re.compile(
                r'if ! validate_toggle_config "APPLY_SECURITY_HARDENING" "\$\{APPLY_SECURITY_HARDENING\}"; then\s+'
                r'exit 1\s+'
                r'fi\s+'
                r'# Export for the buildx compressed build script',
                re.DOTALL,
            ),
        )
        self.assertNotIn('Security hardening: DISABLED (default)', self.installation_script)
        self.assertIn(
            'Interactive installs default this option to enabled; re-run with hardening enabled to reduce vulnerabilities.',
            self.installation_script,
        )
        self.assertRegex(
            self.installation_script,
            re.compile(
                r"resolve_security_hardening_choice\(\) \{.*?local prompt_default=\"Y\".*?local default_choice=\"yes\"",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.installation_script,
            re.compile(
                r"resolve_vulnerability_scan_choice\(\) \{.*?local prompt_default=\"n\".*?local default_choice=\"no\"",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
