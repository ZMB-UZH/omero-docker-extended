from __future__ import annotations

from iter_test_helpers import next_or_fail

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class OmeroWebStartupScriptRegressionTests(unittest.TestCase):
    """Test cases for OMERO web startup script regression tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `OmeroWebStartupScriptRegressionTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.config_script = cls.repo_root / "startup" / "50-config.py"
        cls.default_config_script = (
            cls.repo_root / "startup" / "60-default-web-config.sh"
        )
        cls.imaris_worker_script = (
            cls.repo_root / "startup" / "40-start-imaris-celery-worker.sh"
        )
        cls.tools_worker_script = (
            cls.repo_root / "startup" / "40-start-tools-celery-worker.sh"
        )
        cls.cleanprevious_script = cls.repo_root / "startup" / "98-cleanprevious.sh"

    @staticmethod
    def _make_fake_omero(workspace: Path) -> tuple[Path, Path]:
        """Create the fake OMERO for `OmeroWebStartupScriptRegressionTests`.

        Inputs: `workspace` (Path). Output: `tuple[Path, Path]`.
        """
        calls_file = workspace / "omero-calls.log"
        fake_omero = workspace / "omero"
        fake_omero.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'%s\\n\' "$*" >> "$OMERO_CALLS_FILE"\n',
            encoding="utf-8",
        )
        fake_omero.chmod(fake_omero.stat().st_mode | stat.S_IXUSR)
        return fake_omero, calls_file

    @staticmethod
    def _make_fake_python_validator(workspace: Path) -> tuple[Path, Path]:
        """Fake python validator.

        Inputs: `workspace`. Output: `tuple[Path, Path]`.
        """
        calls_file = workspace / "python-calls.log"
        fake_python = workspace / "python3"
        fake_python.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "calls_file = Path(os.environ['PYTHON_CALLS_FILE'])\n"
            "modules = sys.argv[3:]\n"
            "calls_file.write_text('\\n'.join(modules) + ('\\n' if modules else ''), encoding='utf-8')\n"
            "missing = set(json.loads(os.environ.get('PYTHON_MISSING_MODULES', '[]')))\n"
            "missing_modules = [module for module in modules if module in missing]\n"
            "if missing_modules:\n"
            "    sys.stderr.write(\n"
            "        'Missing OMERO.web app modules referenced by CONFIG_omero_web_apps: '\n"
            "        + ', '.join(missing_modules)\n"
            "        + '\\n'\n"
            "    )\n"
            "    raise SystemExit(1)\n",
            encoding="utf-8",
        )
        fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
        return fake_python, calls_file

    @staticmethod
    def _make_fake_worker_venv(web_root: Path, venv_name: str) -> tuple[Path, Path]:
        """Create a fake OMERO.web worker venv.

        Inputs: `web_root`, `venv_name`. Output: `tuple[Path, Path]`.
        """
        bin_dir = web_root / venv_name / "bin"
        bin_dir.mkdir(parents=True)
        calls_file = web_root / "worker-calls.log"
        fake_python = bin_dir / "python"
        fake_python.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'python %s\\n\' "$*" >> "$WORKER_CALLS_FILE"\n',
            encoding="utf-8",
        )
        fake_celery = bin_dir / "celery"
        fake_celery.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'celery %s\\n\' "$*" >> "$WORKER_CALLS_FILE"\n',
            encoding="utf-8",
        )
        fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
        fake_celery.chmod(fake_celery.stat().st_mode | stat.S_IXUSR)
        return bin_dir, calls_file

    def test_50_config_applies_globbed_files_and_config_env_overrides(self) -> None:
        """Verify 50 config applies globbed files and config env overrides.

        Inputs: repository fixtures. Output: fails on regressions in 50 config applies globbed files and config env overrides.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            fake_omero, calls_file = self._make_fake_omero(workspace)
            fake_python, python_calls_file = self._make_fake_python_validator(workspace)
            config_dir = workspace / "config"
            config_dir.mkdir()
            (config_dir / "site.omero").write_text("# test\n", encoding="utf-8")

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_OMERO_BIN": str(fake_omero),
                "OMERO_WEB_PYTHON_BIN": str(fake_python),
                "PYTHON_CALLS_FILE": str(python_calls_file),
                "OMERO_WEB_CONFIG_GLOB": str(config_dir / "*.omero"),
                "CONFIG_omero_web_login__logo": "/static/branding/logo.png",
                "CONFIG_omero_web_public_enabled": "false",
            }

            subprocess.run(
                [sys.executable, str(self.config_script)], check=True, env=env
            )

            calls = calls_file.read_text(encoding="utf-8").splitlines()
            self.assertIn(f"load --glob {config_dir}/*.omero", calls)
            self.assertIn(
                "config set -- omero.web.login_logo /static/branding/logo.png",
                calls,
            )
            self.assertIn("config set -- omero.web.public.enabled false", calls)
            self.assertFalse(python_calls_file.exists())

    def test_50_config_sets_empty_values_from_file(self) -> None:
        """Verify 50 config sets empty values from file.

        Inputs: repository fixtures. Output: fails on regressions in 50 config sets empty values from file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            fake_omero, calls_file = self._make_fake_omero(workspace)
            fake_python, python_calls_file = self._make_fake_python_validator(workspace)

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_OMERO_BIN": str(fake_omero),
                "OMERO_WEB_PYTHON_BIN": str(fake_python),
                "PYTHON_CALLS_FILE": str(python_calls_file),
                "CONFIG_omero_fs_importArgs": "",
            }

            subprocess.run(
                [sys.executable, str(self.config_script)], check=True, env=env
            )

            calls = calls_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 1)
            self.assertRegex(
                calls[0],
                r"^config set omero\.fs\.importArgs -f /tmp/",
            )
            self.assertFalse(python_calls_file.exists())

    def test_50_config_auto_detects_config_glob_from_omero_binary(self) -> None:
        """Verify 50 config auto detects config glob from OMERO binary.

        Inputs: repository fixtures. Output: fails on regressions in 50 config auto detects config glob from OMERO binary.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            fake_bin_dir = workspace / "runtime" / "venv" / "bin"
            fake_bin_dir.mkdir(parents=True)
            fake_omero = fake_bin_dir / "omero"
            calls_file = workspace / "omero-calls.log"
            fake_omero.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf \'%s\\n\' "$*" >> "$OMERO_CALLS_FILE"\n',
                encoding="utf-8",
            )
            fake_omero.chmod(fake_omero.stat().st_mode | stat.S_IXUSR)
            fake_python = fake_bin_dir / "python3"
            fake_python.write_text(
                "#!/usr/bin/env python3\n",
                encoding="utf-8",
            )
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
            config_dir = workspace / "runtime" / "config"
            config_dir.mkdir()
            (config_dir / "site.omero").write_text("# test\n", encoding="utf-8")

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_OMERO_BIN": str(fake_omero),
                "OMERO_WEB_PYTHON_BIN": str(fake_python),
            }

            subprocess.run(
                [sys.executable, str(self.config_script)], check=True, env=env
            )

            calls = calls_file.read_text(encoding="utf-8").splitlines()
            self.assertIn(f"load --glob {config_dir}/*.omero", calls)

    def test_50_config_discovers_omero_cli_from_omeroweb_root_contract(self) -> None:
        """Verify 50 config discovers OMERO CLI from OMERO_WEB_ROOT.

        Inputs: repository fixtures. Output: fails on hardcoded OMERO.web root regressions.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            web_root = workspace / "custom-web-root"
            fake_bin_dir = web_root / "venv-3.12" / "bin"
            fake_bin_dir.mkdir(parents=True)
            fake_omero = fake_bin_dir / "omero"
            calls_file = workspace / "omero-calls.log"
            fake_omero.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf \'%s\\n\' "$*" >> "$OMERO_CALLS_FILE"\n',
                encoding="utf-8",
            )
            fake_python = fake_bin_dir / "python3"
            fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            fake_omero.chmod(fake_omero.stat().st_mode | stat.S_IXUSR)
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

            env = {
                "PATH": "/bin:/usr/bin",
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_ROOT": str(web_root),
                "OMERO_WEB_VENV": "venv-3.12",
                "CONFIG_omero_web_public_enabled": "false",
            }

            subprocess.run(
                [sys.executable, str(self.config_script)], check=True, env=env
            )

            self.assertEqual(
                calls_file.read_text(encoding="utf-8").splitlines(),
                ["config set -- omero.web.public.enabled false"],
            )

    def test_50_config_requires_omeroweb_root_when_auto_discovery_is_needed(
        self,
    ) -> None:
        """Verify 50 config requires OMERO_WEB_ROOT for automatic discovery.

        Inputs: repository fixtures. Output: fails on hidden fallback root regressions.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            result = subprocess.run(
                [sys.executable, str(self.config_script)],
                check=False,
                env={
                    "PATH": str(workspace),
                    "CONFIG_omero_web_public_enabled": "false",
                },
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("OMERO_WEB_ROOT is required", result.stderr)

    def test_50_config_normalizes_legacy_plugin_aliases_before_apply(self) -> None:
        """Check 50 config normalizes legacy plugin aliases before apply parsing against the documented contract.

        Inputs: repository fixtures. Output: fails on regressions in 50 config normalizes legacy plugin aliases before apply.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            fake_omero, calls_file = self._make_fake_omero(workspace)
            fake_python, python_calls_file = self._make_fake_python_validator(workspace)

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_OMERO_BIN": str(fake_omero),
                "OMERO_WEB_PYTHON_BIN": str(fake_python),
                "PYTHON_CALLS_FILE": str(python_calls_file),
                "CONFIG_omero_web_apps": json.dumps(
                    ["omeroweb_upload", "omeroweb_admin_tools"]
                ),
                "CONFIG_omero_web_ui_top__links": json.dumps(
                    [
                        ["Upload", "omeroweb_upload_index", {"title": "Open Upload"}],
                        ["Legacy path", "/omeroweb_upload/", {"target": "_blank"}],
                    ]
                ),
            }

            subprocess.run(
                [sys.executable, str(self.config_script)], check=True, env=env
            )

            self.assertEqual(
                python_calls_file.read_text(encoding="utf-8").splitlines(),
                ["omeroweb_import", "omeroweb_admin_tools"],
            )

            calls = calls_file.read_text(encoding="utf-8").splitlines()
            apps_call = next_or_fail(
                call
                for call in calls
                if call.startswith("config set -- omero.web.apps ")
            )
            top_links_call = next_or_fail(
                call
                for call in calls
                if call.startswith("config set -- omero.web.ui.top_links ")
            )
            self.assertIn("omeroweb_import", apps_call)
            self.assertNotIn("omeroweb_upload", apps_call)
            self.assertIn("omeroweb_import_index", top_links_call)
            self.assertIn("/omeroweb_import/", top_links_call)
            self.assertNotIn("omeroweb_upload", top_links_call)

    def test_50_config_fails_fast_when_app_modules_are_missing(self) -> None:
        """Confirm 50 config fails fast when app modules are missing exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in 50 config fails fast when app modules are missing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            fake_omero, calls_file = self._make_fake_omero(workspace)
            fake_python, python_calls_file = self._make_fake_python_validator(workspace)

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_OMERO_BIN": str(fake_omero),
                "OMERO_WEB_PYTHON_BIN": str(fake_python),
                "PYTHON_CALLS_FILE": str(python_calls_file),
                "PYTHON_MISSING_MODULES": json.dumps(["broken_plugin"]),
                "CONFIG_omero_web_apps": json.dumps(["broken_plugin"]),
            }

            result = subprocess.run(
                [sys.executable, str(self.config_script)],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Missing OMERO.web app modules referenced by CONFIG_omero_web_apps: broken_plugin",
                result.stderr,
            )
            self.assertEqual(
                python_calls_file.read_text(encoding="utf-8").splitlines(),
                ["broken_plugin"],
            )
            self.assertFalse(calls_file.exists())

    def test_60_default_web_config_uses_dynamic_omero_binary(self) -> None:
        """Verify 60 default web config uses dynamic OMERO binary.

        Inputs: repository fixtures. Output: fails on regressions in 60 default web config uses dynamic OMERO binary.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            fake_omero, calls_file = self._make_fake_omero(workspace)

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_OMERO_BIN": str(fake_omero),
                "OMEROHOST": "omeroserver",
                "OMERO_PORT": "14064",
            }

            subprocess.run(
                [BASH_BIN, str(self.default_config_script)], check=True, env=env
            )

            calls = calls_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                calls,
                ['config set omero.web.server_list [["omeroserver", 14064, "omero"]]'],
            )

    def test_60_default_web_config_discovers_cli_from_omeroweb_root_contract(
        self,
    ) -> None:
        """Verify 60 default web config uses OMERO_WEB_ROOT for CLI discovery.

        Inputs: repository fixtures. Output: fails on hardcoded OMERO.web root regressions.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            web_root = workspace / "web-root"
            fake_bin_dir = web_root / "venv-3.12" / "bin"
            fake_bin_dir.mkdir(parents=True)
            fake_omero = fake_bin_dir / "omero"
            calls_file = workspace / "omero-calls.log"
            fake_omero.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf \'%s\\n\' "$*" >> "$OMERO_CALLS_FILE"\n',
                encoding="utf-8",
            )
            fake_omero.chmod(fake_omero.stat().st_mode | stat.S_IXUSR)

            env = {
                "PATH": "/bin:/usr/bin",
                "OMERO_CALLS_FILE": str(calls_file),
                "OMERO_WEB_ROOT": str(web_root),
                "OMERO_WEB_VENV": "venv-3.12",
                "OMEROHOST": "omeroserver",
                "OMERO_PORT": "14064",
            }

            subprocess.run(
                [BASH_BIN, str(self.default_config_script)], check=True, env=env
            )

            self.assertEqual(
                calls_file.read_text(encoding="utf-8").splitlines(),
                ['config set omero.web.server_list [["omeroserver", 14064, "omero"]]'],
            )

    def test_celery_worker_scripts_use_omeroweb_root_contract(self) -> None:
        """Verify Celery worker scripts use OMERO_WEB_ROOT for venv discovery.

        Inputs: repository fixtures. Output: fails on hardcoded OMERO.web root regressions.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            web_root = workspace / "web-root"
            _bin_dir, calls_file = self._make_fake_worker_venv(web_root, "venv-3.12")

            common_env = {
                "PATH": "/bin:/usr/bin",
                "WORKER_CALLS_FILE": str(calls_file),
                "OMERO_WEB_ROOT": str(web_root),
                "OMERO_WEB_VENV": "venv-3.12",
            }

            subprocess.run(
                [BASH_BIN, str(self.imaris_worker_script)],
                check=True,
                env={
                    **common_env,
                    "OMERO_IMS_CELERY_QUEUE": "imaris",
                    "OMERO_IMS_CELERY_LOGLEVEL": "info",
                    "OMERO_IMS_CELERY_WORKER_CONCURRENCY": "1",
                },
            )
            subprocess.run(
                [BASH_BIN, str(self.tools_worker_script)],
                check=True,
                env={
                    **common_env,
                    "TOOLS_ENHANCED_SEARCH_CELERY_QUEUE": "enhanced_search",
                    "TOOLS_ENHANCED_SEARCH_CELERY_LOGLEVEL": "info",
                    "TOOLS_ENHANCED_SEARCH_CELERY_WORKER_CONCURRENCY": "1",
                },
            )

            calls = calls_file.read_text(encoding="utf-8").splitlines()
            self.assertIn(
                "-A omeroweb_imaris_connector.celery_app worker "
                "--loglevel=info --concurrency=1 -Q imaris --hostname=imaris@%h",
                calls[1],
            )
            self.assertIn(
                "-A omeroweb_tools.celery_app worker --loglevel=info "
                "--concurrency=1 -Q enhanced_search --hostname=enhanced-search@%h",
                calls[3],
            )

    def test_98_cleanprevious_removes_stale_pid_file(self) -> None:
        """Check 98 cleanprevious removes stale pid file cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions in 98 cleanprevious removes stale pid file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            pid_file = workspace / "django.pid"
            pid_file.write_text("123\n", encoding="utf-8")

            env = {
                "PATH": os.environ.get("PATH", ""),
                "OMERO_WEB_DJANGO_PIDFILE": str(pid_file),
            }

            subprocess.run(
                [BASH_BIN, str(self.cleanprevious_script)], check=True, env=env
            )

            self.assertFalse(pid_file.exists())

    def test_dockerfile_replaces_inherited_startup_scripts_with_repo_managed_versions(
        self,
    ) -> None:
        """Verify dockerfile replaces inherited startup scripts with repo managed versions.

        Inputs: repository fixtures. Output: fails on regressions in dockerfile replaces inherited startup scripts with repo managed versions.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-web.Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "rm -f /startup/50-config.py /startup/60-default-web-config.sh /startup/98-cleanprevious.sh /startup/99-run.sh",
            dockerfile_text,
        )
        self.assertIn(
            "COPY startup/50-config.py /startup/50-config.py", dockerfile_text
        )
        self.assertIn(
            "COPY startup/60-default-web-config.sh /startup/60-default-web-config.sh",
            dockerfile_text,
        )
        self.assertIn(
            "COPY startup/98-cleanprevious.sh /startup/98-cleanprevious.sh",
            dockerfile_text,
        )
        self.assertIn("COPY omeroweb_tools /tmp/omeroweb_tools", dockerfile_text)
        self.assertIn(
            "COPY startup/40-start-tools-celery-worker.sh /opt/omero/web/bin/start-tools-celery-worker.sh",
            dockerfile_text,
        )


if __name__ == "__main__":
    unittest.main()
