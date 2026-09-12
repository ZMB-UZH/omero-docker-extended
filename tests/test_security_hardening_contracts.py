import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DOCKERFILE = REPO_ROOT / "docker" / "omero-server.Dockerfile"
WEB_DOCKERFILE = REPO_ROOT / "docker" / "omero-web.Dockerfile"
INSTALLATION_SCRIPT = REPO_ROOT / "installation" / "installation_script.sh"


class SecurityHardeningContractTests(unittest.TestCase):
    """Test cases for security hardening contract tests."""

    @classmethod
    def setUpClass(cls):
        """Prepare shared fixtures for `SecurityHardeningContractTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.server_dockerfile = SERVER_DOCKERFILE.read_text(encoding="utf-8")
        cls.web_dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
        cls.installation_script = INSTALLATION_SCRIPT.read_text(encoding="utf-8")

    def test_failed_os_package_updates_stop_hardened_builds(self):
        """Execute the package-update boundary with a failing package manager.

        Inputs: actual Dockerfile RUN prefixes. Output: requires fatal failures.
        """
        for name, dockerfile, expected_attempts in (
            ("server", self.server_dockerfile, 3),
            ("web", self.web_dockerfile, 1),
        ):
            with self.subTest(image=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                calls = root / "dnf-calls"
                for command, body in (
                    ("dnf", '#!/bin/sh\nprintf "called\\n" >> "$DNF_CALLS"\nexit 67\n'),
                    ("sleep", "#!/bin/sh\nexit 0\n"),
                ):
                    executable = root / command
                    executable.write_text(body, encoding="utf-8")
                    executable.chmod(0o700)
                hardening = dockerfile.split("# Final security hardening pass", 1)[1]
                prefix = hardening.split("RUN ", 1)[1]
                prefix = prefix.split("dnf clean all", 1)[0]
                prefix = prefix.split(
                    'echo "=== Final security hardening: removing unnecessary packages ==="',
                    1,
                )[0]
                result = subprocess.run(
                    [
                        shutil.which("bash") or "/bin/bash",
                        "-c",
                        prefix.replace("\\\n", ""),
                    ],
                    env={
                        **os.environ,
                        "PATH": str(root),
                        "DNF_CALLS": str(calls),
                        "APPLY_SECURITY_HARDENING": "1",
                    },
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(
                    len(calls.read_text(encoding="utf-8").splitlines()),
                    expected_attempts,
                )

    def test_failed_curated_python_update_stops_server_build(self):
        """Execute the actual curated pip update with a failing interpreter.

        Inputs: Dockerfile update commands. Output: requires fatal failure.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            executable = root / "bin" / "python"
            executable.write_text("#!/bin/sh\nexit 67\n", encoding="utf-8")
            executable.chmod(0o700)
            boundary = self.server_dockerfile.split(
                'echo "Applying curated compatibility-safe Python security updates', 1
            )[1]
            commands = boundary.split('"${VENV_DIR}/bin/python"', 1)[1]
            commands = (
                '"${VENV_DIR}/bin/python"'
                + commands.split('echo "Stripping test directories', 1)[0]
            )
            env = {**os.environ, "VENV_DIR": str(root)}
            env.update(
                dict(
                    re.findall(
                        r"^ARG ([A-Z0-9_]+_VERSION)=([^\s]+)$",
                        self.server_dockerfile,
                        re.M,
                    )
                )
            )
            result = subprocess.run(
                [
                    shutil.which("bash") or "/bin/bash",
                    "-c",
                    "set -euo pipefail; " + commands.replace("\\\n", ""),
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 67, result.stdout + result.stderr)

    def test_locale_data_is_preserved_while_other_hardening_stays_enabled(self):
        """Verify locale data is preserved while other hardening stays enabled.

        Inputs: repository fixtures. Output: fails on regressions in locale data is preserved while other hardening stays enabled.
        """
        self.assertNotIn("langpacks-en", self.server_dockerfile)
        self.assertNotIn("glibc-langpack-en", self.server_dockerfile)
        self.assertNotIn("localedef --list-archive", self.server_dockerfile)
        self.assertNotIn("/usr/share/i18n/locales", self.server_dockerfile)
        self.assertNotIn("langpacks-en", self.web_dockerfile)
        self.assertNotIn("glibc-langpack-en", self.web_dockerfile)
        self.assertIn(
            'echo "=== Final security hardening: OS packages (dnf) ==="; \\',
            self.server_dockerfile,
        )
        self.assertIn(
            'echo "=== Final security hardening: Python packages (pip) ==="; \\',
            self.server_dockerfile,
        )
        self.assertIn(
            'echo "=== Final security hardening: preserving shared libraries ==="; \\',
            self.server_dockerfile,
        )
        self.assertIn(
            "Skipping blanket shared-library stripping because it can corrupt critical runtime libraries.",
            self.server_dockerfile,
        )
        self.assertNotIn("strip --strip-unneeded", self.server_dockerfile)

    def test_security_hardening_prompt_defaults_yes_while_scout_stays_opt_in(self):
        """Verify the security hardening prompt defaults yes while scout stays opt in safety boundary.

        Inputs: repository fixtures. Output: fails on regressions when security hardening prompt defaults yes while scout stays opt in accepts unsafe input.
        """
        self.assertIn(
            'APPLY_SECURITY_HARDENING="${APPLY_SECURITY_HARDENING:-}"',
            self.installation_script,
        )
        self.assertIn(
            'ENABLE_VULNERABILITY_SCAN="${ENABLE_VULNERABILITY_SCAN:-0}"',
            self.installation_script,
        )
        self.assertRegex(
            self.installation_script,
            re.compile(
                r'if \[ -n "\$\{APPLY_SECURITY_HARDENING\}" \]; then\s+'
                r'if ! validate_toggle_config "APPLY_SECURITY_HARDENING" "\$\{APPLY_SECURITY_HARDENING\}"; then\s+'
                r"exit 1\s+"
                r"fi\s+"
                r"fi",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            self.installation_script,
            re.compile(
                r'if ! validate_toggle_config "APPLY_SECURITY_HARDENING" "\$\{APPLY_SECURITY_HARDENING\}"; then\s+'
                r"exit 1\s+"
                r"fi\s+"
                r"# Export for the buildx compressed build script",
                re.DOTALL,
            ),
        )
        self.assertNotIn(
            "Security hardening: DISABLED (default)", self.installation_script
        )
        self.assertIn(
            "Interactive installs default this option to enabled; re-run with hardening enabled to reduce vulnerabilities.",
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
        self.assertRegex(
            self.installation_script,
            re.compile(
                r"resolve_storage_quotas_choice\(\) \{.*?local prompt_default=\"n\".*?local default_choice=\"no\"",
                re.DOTALL,
            ),
        )
        self.assertIn(
            "Enable ext4 project quotas for OMERO user data?",
            self.installation_script,
        )
        self.assertIn("STORAGE_QUOTAS_CHOICE", self.installation_script)
        self.assertNotIn("OMERO_QUOTA_SKIP_COMPOSE=1", self.installation_script)
        self.assertIn("STORAGE_QUOTAS_ENABLEMENT_RAN", self.installation_script)


if __name__ == "__main__":
    unittest.main()
