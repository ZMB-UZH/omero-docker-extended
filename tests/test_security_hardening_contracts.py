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
BUILD_DEPENDENCY_CLEANUP = REPO_ROOT / "docker" / "remove-build-dependencies.sh"


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

    def test_application_images_enable_final_hardening_by_default(self):
        """Check direct builds remain hardened. Inputs: Dockerfiles. Output: assertions."""
        for dockerfile in (self.server_dockerfile, self.web_dockerfile):
            self.assertIn("ARG APPLY_SECURITY_HARDENING=1\n", dockerfile)
            self.assertNotIn("ARG APPLY_SECURITY_HARDENING=0\n", dockerfile)

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

    def test_server_curated_updates_include_image_and_serialization_libraries(self):
        """Inputs: final server update stage. Output: pinned codecs and pip validation."""
        hardening = self.server_dockerfile.split("# Final security hardening pass", 1)[
            1
        ]
        for name, package, version in (
            ("PILLOW", "pillow", "12.3.0"),
            ("MSGPACK", "msgpack", "1.2.2"),
        ):
            with self.subTest(package=package):
                self.assertIn(f"ARG {name}_VERSION={version}\n", hardening)
                self.assertIn(f'"{package}==${{{name}_VERSION}}"', hardening)
        self.assertIn('"${VENV_DIR}/bin/python" -m pip check;', hardening)

    def test_build_dependency_cleanup_checks_transactions_and_removal(self):
        """Exercise the real cleanup script against an instrumented RPM boundary.

        Inputs: package inventories and transaction failures. Output: exact-only removal.
        """
        cases = (
            ("absent", "python3\nansible-core-extra", {}, 0, False),
            ("present", "python3\nansible-core\npython3.12-pip", {}, 0, True),
            ("inventory-failed", "ansible-core", {"RPM_QUERY_RC": "67"}, 67, False),
            ("dependency-required", "ansible-core", {"RPM_TEST_RC": "68"}, 68, False),
            ("remove-failed", "ansible-core", {"RPM_REMOVE_RC": "69"}, 69, True),
            ("remove-ineffective", "ansible-core", {"RPM_KEEP": "1"}, 1, True),
        )
        for name, inventory, overrides, expected_rc, removal_attempted in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                calls = root / "calls"
                removed = root / "removed"
                executable = root / "rpm"
                executable.write_text(
                    "#!/bin/bash\n"
                    'printf "%s\\n" "$*" >> "$RPM_CALLS"\n'
                    'if [[ "$1" == "-qa" ]]; then\n'
                    '  if [[ ! -f "$RPM_REMOVED" || "${RPM_KEEP:-0}" == "1" ]]; then\n'
                    '    printf "%s\\n" "$RPM_INVENTORY"\n'
                    "  else\n"
                    '    printf "python3\\n"\n'
                    "  fi\n"
                    '  exit "${RPM_QUERY_RC:-0}"\n'
                    "fi\n"
                    'if [[ "$2" == "--test" ]]; then exit "${RPM_TEST_RC:-0}"; fi\n'
                    ': > "$RPM_REMOVED"\n'
                    'exit "${RPM_REMOVE_RC:-0}"\n',
                    encoding="utf-8",
                )
                executable.chmod(0o700)
                result = subprocess.run(
                    [
                        shutil.which("bash") or "/bin/bash",
                        str(BUILD_DEPENDENCY_CLEANUP),
                    ],
                    env={
                        **os.environ,
                        "PATH": str(root),
                        "RPM_CALLS": str(calls),
                        "RPM_REMOVED": str(removed),
                        "RPM_INVENTORY": inventory,
                        **overrides,
                    },
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected_rc, result.stderr)
                self.assertEqual(removed.exists(), removal_attempted)
                commands = calls.read_text(encoding="utf-8").splitlines()
                if name == "present":
                    self.assertEqual(
                        commands[1:3],
                        [
                            "-e --test -- ansible-core python3.12-pip",
                            "-e -- ansible-core python3.12-pip",
                        ],
                    )
                elif name in {"absent", "inventory-failed"}:
                    self.assertEqual(len(commands), 1)
                elif name == "remove-ineffective":
                    self.assertIn("Build dependency remains installed", result.stderr)

    def test_both_images_remove_build_dependencies_after_application_installation(self):
        """Inputs: image recipes. Output: cleanup runs last with privileged package access."""
        for image, content, user in (
            ("server", self.server_dockerfile, "omero-server"),
            ("web", self.web_dockerfile, "omero-web"),
        ):
            with self.subTest(image=image):
                cleanup = content.index(
                    "RUN /bin/bash /tmp/remove-build-dependencies.sh"
                )
                self.assertGreater(cleanup, content.rindex("pip install"))
                self.assertLess(cleanup, content.rindex(f"USER {user}"))

    def test_server_jdbc_update_is_verified_before_installation(self):
        """Inputs: server driver stage. Output: both classpaths share a verified release."""
        stage = self.server_dockerfile.split("ARG POSTGRESQL_JDBC_VERSION=", 1)[1]
        self.assertTrue(stage.startswith("42.7.13\n"))
        self.assertIn(
            "ARG POSTGRESQL_JDBC_SHA256="
            "6e0e4cc2d8cae902084f8a2b18728b073a6fd9d1f87c9d8bff8f298c18185b93\n",
            stage,
        )
        self.assertIn('"${#SERVER_DIRS[@]}" -ne 1', stage)
        self.assertLess(stage.index("sha256sum -c -"), stage.index("unzip -p"))
        self.assertLess(stage.index("unzip -p"), stage.index("install -o"))
        self.assertIn(
            'grep -Fx "Implementation-Version: ${POSTGRESQL_JDBC_VERSION}"', stage
        )
        self.assertIn("for subdir in lib/client lib/server", stage)
        self.assertIn('test -f "${SERVER_DIR}/${subdir}/postgresql.jar"', stage)
        self.assertIn('rm -f "${SERVER_DIR}.zip"', stage)

    def test_pdf_text_parser_updates_the_matching_library_pair(self):
        """Inputs: server parser stage. Output: verified matching libraries on both classpaths."""
        stage = self.server_dockerfile.split("ARG PDFBOX_VERSION=", 1)[1]
        self.assertTrue(stage.startswith("2.0.37\n"))
        self.assertIn(
            "ARG PDFBOX_SHA256="
            "fcb04e6dac53f8681108bb66d5ac2ca72987b6c6795b14a8071636fc49a5d703\n",
            stage,
        )
        self.assertIn(
            "ARG FONTBOX_SHA256="
            "992e14d5e903f69517903a1a817040ed7bf1288e768870e0a27bf9090bb34ec3\n",
            stage,
        )
        self.assertIn("for artifact in pdfbox fontbox", stage)
        self.assertIn("for subdir in lib/client lib/server", stage)
        self.assertLess(stage.index("sha256sum -c -"), stage.index("unzip -p"))
        self.assertLess(stage.index("unzip -p"), stage.index("install -o"))
        self.assertIn('test -f "${SERVER_DIR}/${subdir}/${artifact}.jar"', stage)

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
