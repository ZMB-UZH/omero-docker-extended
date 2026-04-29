"""Tests for the env safety guard tool."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import env_safety_guard


class EnvSafetyGuardTests(unittest.TestCase):
    """Verify the env safety guard protects deployment config files."""

    def _make_repo(
        self, manifest_lines: list[str], files: dict[str, str] | None = None
    ):
        """Create a temporary repo root with a manifest and optional files."""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))

        manifest_text = "\n".join(manifest_lines) + "\n"
        (d / ".env_manifest").write_text(manifest_text, encoding="utf-8")

        if files:
            for rel_path, content in files.items():
                p = d / rel_path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

        return d

    # ---- check command ----

    def test_check_passes_when_all_manifest_entries_exist(self):
        repo = self._make_repo(
            ["env/omeroweb.env", "installation_paths.env"],
            {
                "env/omeroweb.env": "CONFIG_omero_web_apps=[]",
                "installation_paths.env": "OMERO_DATA_PATH=/data",
            },
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 0)

    def test_check_fails_when_manifest_entry_is_missing(self):
        repo = self._make_repo(
            ["env/omeroweb.env", "env/missing.env"],
            {"env/omeroweb.env": "CONFIG_omero_web_apps=[]"},
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 1)

    def test_check_fails_when_manifest_entry_is_empty(self):
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": ""},
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 1)

    def test_check_ignores_comment_and_blank_lines_in_manifest(self):
        repo = self._make_repo(
            ["# This is a comment", "", "env/omeroweb.env", "  "],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 0)

    def test_load_manifest_keeps_symlinked_entries_repo_relative(self):
        repo = self._make_repo(["env/omeroweb.env"])
        external = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(external, ignore_errors=True)
        )
        target = external / "omeroweb.env"
        target.write_text("CONFIG=value", encoding="utf-8")
        env_dir = repo / "env"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "omeroweb.env").symlink_to(target)

        entries = env_safety_guard.load_manifest(repo)

        self.assertEqual(entries, [repo / "env/omeroweb.env"])
        self.assertTrue(entries[0].exists())

    def test_load_manifest_rejects_absolute_or_traversal_entries(self):
        for manifest_entry in (
            "/etc/passwd",
            "../secrets.env",
            "env/../secret.env",
            "env//secret.env",
            "env/secret.env/",
        ):
            with self.subTest(manifest_entry=manifest_entry):
                repo = self._make_repo([manifest_entry])
                with self.assertRaises(SystemExit):
                    env_safety_guard.load_manifest(repo)

    def test_derive_compose_project_name_uses_installation_basename(self):
        self.assertEqual(
            env_safety_guard.derive_compose_project_name("/srv/OMERO Live"),
            "omero-live",
        )

    def test_compose_guard_passes_for_canonical_installation_root(self):
        compose_env_files = ",".join(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES)
        repo = self._make_repo(
            [
                "installation_paths.env",
                "env/omeroweb.env",
                "env/omeroserver.env",
                "env/omero_secrets.env",
                "env/grafana.env",
                "env/omero-celery.env",
            ],
            {
                "installation_paths.env": "",
                "env/omeroweb.env": "CONFIG=value",
                "env/omeroserver.env": "CONFIG=value",
                "env/omero_secrets.env": "SECRET=value",
                "env/grafana.env": "GF=value",
                "env/omero-celery.env": "QUEUE=value",
            },
        )
        compose_project_name = env_safety_guard.derive_compose_project_name(repo)
        (repo / "installation_paths.env").write_text(
            f"OMERO_INSTALLATION_PATH={repo}\n",
            encoding="utf-8",
        )
        (repo / ".env").write_text(
            "\n".join(
                [
                    f"COMPOSE_ENV_FILES={compose_env_files}",
                    f"COMPOSE_PROJECT_NAME={compose_project_name}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 0)

    def test_compose_guard_fails_for_non_canonical_worktree(self):
        compose_env_files = ",".join(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES)
        repo = self._make_repo(
            [
                "installation_paths.env",
                "env/omeroweb.env",
                "env/omeroserver.env",
                "env/omero_secrets.env",
                "env/grafana.env",
                "env/omero-celery.env",
            ],
            {
                "installation_paths.env": "",
                "env/omeroweb.env": "CONFIG=value",
                "env/omeroserver.env": "CONFIG=value",
                "env/omero_secrets.env": "SECRET=value",
                "env/grafana.env": "GF=value",
                "env/omero-celery.env": "QUEUE=value",
            },
        )
        live_root = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(live_root, ignore_errors=True)
        )
        compose_project_name = env_safety_guard.derive_compose_project_name(live_root)
        (repo / "installation_paths.env").write_text(
            f"OMERO_INSTALLATION_PATH={live_root}\n",
            encoding="utf-8",
        )
        (repo / ".env").write_text(
            "\n".join(
                [
                    f"COMPOSE_ENV_FILES={compose_env_files}",
                    f"COMPOSE_PROJECT_NAME={compose_project_name}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_compose_guard_fails_when_dot_env_project_name_is_missing(self):
        repo = self._make_repo(
            [
                "installation_paths.env",
                "env/omeroweb.env",
                "env/omeroserver.env",
                "env/omero_secrets.env",
                "env/grafana.env",
                "env/omero-celery.env",
            ],
            {
                "installation_paths.env": "",
                "env/omeroweb.env": "CONFIG=value",
                "env/omeroserver.env": "CONFIG=value",
                "env/omero_secrets.env": "SECRET=value",
                "env/grafana.env": "GF=value",
                "env/omero-celery.env": "QUEUE=value",
            },
        )
        (repo / "installation_paths.env").write_text(
            f"OMERO_INSTALLATION_PATH={repo}\n",
            encoding="utf-8",
        )
        (repo / ".env").write_text(
            "COMPOSE_ENV_FILES=installation_paths.env\n", encoding="utf-8"
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_dot_env_check_fails_when_dot_env_uses_stale_env_file_list(self):
        repo = self._make_repo(
            [
                "installation_paths.env",
                "env/omeroweb.env",
                "env/omeroserver.env",
                "env/omero_secrets.env",
                "env/grafana.env",
                "env/omero-celery.env",
            ],
            {
                "installation_paths.env": "",
                "env/omeroweb.env": "CONFIG=value",
                "env/omeroserver.env": "CONFIG=value",
                "env/omero_secrets.env": "SECRET=value",
                "env/grafana.env": "GF=value",
                "env/omero-celery.env": "QUEUE=value",
            },
        )
        compose_project_name = env_safety_guard.derive_compose_project_name(repo)
        (repo / "installation_paths.env").write_text(
            f"OMERO_INSTALLATION_PATH={repo}\n",
            encoding="utf-8",
        )
        (repo / ".env").write_text(
            "\n".join(
                [
                    "COMPOSE_ENV_FILES=installation_paths.env,env/omero_secrets.env,env/omeroserver.env,env/omeroweb.env,env/omero-celery.env,env/grafana.env",
                    f"COMPOSE_PROJECT_NAME={compose_project_name}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 0)
        self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 1)

    def test_dot_env_check_passes_for_complete_generated_dot_env_shape(self):
        compose_env_files = ",".join(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES)
        repo = self._make_repo(
            [
                "installation_paths.env",
                "env/omeroweb.env",
                "env/omeroserver.env",
                "env/omero_secrets.env",
                "env/grafana.env",
                "env/omero-celery.env",
            ],
            {
                "installation_paths.env": "",
                "env/omeroweb.env": "CONFIG=value",
                "env/omeroserver.env": "CONFIG=value",
                "env/omero_secrets.env": "SECRET=value",
                "env/grafana.env": "GF=value",
                "env/omero-celery.env": "QUEUE=value",
            },
        )
        compose_project_name = env_safety_guard.derive_compose_project_name(repo)
        (repo / "installation_paths.env").write_text(
            f"OMERO_INSTALLATION_PATH={repo}\n",
            encoding="utf-8",
        )
        dot_env_lines = [
            f"COMPOSE_ENV_FILES={compose_env_files}",
            f"COMPOSE_PROJECT_NAME={compose_project_name}",
        ]
        dot_env_lines.extend(
            f"{key}={'value' if key != 'REDIS_SAVE_POLICY' else ''}"
            for key in env_safety_guard.DOT_ENV_REQUIRED_KEYS
            if key != "COMPOSE_PROJECT_NAME"
        )
        (repo / ".env").write_text("\n".join(dot_env_lines) + "\n", encoding="utf-8")

        self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 0)

    def test_template_check_passes_when_env_keys_match_examples(self):
        files: dict[str, str] = {}
        manifest_lines = []
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "# comment\nA=example\n\nB=example\n"
            files[actual_rel] = "# different comments are allowed\nA=live\nB=live\n"
            manifest_lines.append(actual_rel)
        repo = self._make_repo(manifest_lines, files)

        self.assertEqual(env_safety_guard.cmd_template_check(repo), 0)

    def test_template_check_reports_missing_extra_and_reordered_keys_only(self):
        files: dict[str, str] = {}
        manifest_lines = []
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "A=example\nB=example\n"
            files[actual_rel] = "B=live\nA=live\n"
            manifest_lines.append(actual_rel)
        first_example, first_actual = env_safety_guard.ENV_TEMPLATE_PAIRS[0]
        files[first_example] = "A=example\nB=example\n"
        files[first_actual] = "A=secret-live\nC=secret-live\n"
        repo = self._make_repo(manifest_lines, files)

        self.assertEqual(env_safety_guard.cmd_template_check(repo), 1)

    def test_runtime_env_check_reports_missing_extra_and_type_errors(self):
        files: dict[str, str] = {}
        manifest_lines = []
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "A=example\n"
            files[actual_rel] = "A=live\n"
            manifest_lines.append(actual_rel)

        server_example, server_actual = env_safety_guard.ENV_TEMPLATE_PAIRS[2]
        self.assertEqual(server_example, "env/omeroserver_example.env")
        files[server_example] = "\n".join(
            [
                "OMERO_CLI_HOST=localhost",
                "OMERO_CLI_PORT=4064",
                "OMERO_JOB_SERVICE_SECURE=true",
                "OMERO_INSTALL_GROUP_LIST=users:private",
                "",
            ]
        )
        files[server_actual] = "\n".join(
            [
                "OMERO_CLI_HOST=localhost",
                "OMERO_CLI_PORT=bad-port",
                "OMERO_JOB_SERVICE_SECURE=maybe",
                "EXTRA_KEY=value",
                "",
            ]
        )
        repo = self._make_repo(manifest_lines, files)

        self.assertEqual(
            env_safety_guard.cmd_runtime_env_check(repo, include_dot_env=False),
            1,
        )

    def test_runtime_env_check_accepts_optional_commented_keys_and_references(self):
        files: dict[str, str] = {}
        manifest_lines = []
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "A=example\n# OPTIONAL=value\n"
            files[actual_rel] = "A=live\nOPTIONAL=custom\n"
            manifest_lines.append(actual_rel)

        paths_example, paths_actual = env_safety_guard.ENV_TEMPLATE_PAIRS[0]
        files[paths_example] = (
            "OMERO_DATA_PATH=/srv/omero/data\n"
            "OMERO_USER_DATA_PATH=${OMERO_DATA_PATH}/user\n"
        )
        files[paths_actual] = (
            "OMERO_DATA_PATH=/srv/omero/data\n"
            "OMERO_USER_DATA_PATH=${OMERO_DATA_PATH}/user\n"
        )
        repo = self._make_repo(manifest_lines, files)

        self.assertEqual(
            env_safety_guard.cmd_runtime_env_check(repo, include_dot_env=False),
            0,
        )

    def test_runtime_value_validators_cover_supported_contract_types(self):
        invalid_cases = [
            ("OMERO_JOB_SERVICE_SECURE", "maybe", "maybe", "must be a boolean"),
            ("OMERO_CLI_PORT", "0", "0", "must be a TCP port"),
            ("OMERO_WEB_HOST_PORT", "65536", "65536", "must be a TCP port"),
            (
                "ADMIN_TOOLS_DEFAULT_GROUP_QUOTA_GB",
                "abc",
                "abc",
                "must be a numeric decimal value",
            ),
            ("CONFIG_omero_web_apps", "[bad", "[bad", "must be valid JSON"),
            (
                "OMERO_INSTALL_GROUP_LIST",
                "bad group:private",
                "bad group:private",
                "invalid group name",
            ),
            (
                "OMERO_INSTALL_GROUP_LIST",
                "users:admin",
                "users:admin",
                "unsupported group permission",
            ),
            (
                "OMERO_INSTALL_GROUP_LIST",
                "users",
                "users",
                "entries must be name:permission",
            ),
            (
                "OMERO_DROPBOX_USER_DIR_MODE",
                "9999",
                "9999",
                "must be an octal mode",
            ),
            ("REDIS_MAXMEMORY", "ten", "ten", "must be a memory size"),
            ("OMERO_DATA_PATH", "relative", "relative", "must be an absolute path"),
            (
                "CONFIG_omero_fs_watchDir",
                "relative",
                "relative",
                "must be empty or an absolute path",
            ),
            (
                "ADMIN_TOOLS_LOG_CACHE_MAX_MB",
                "nope",
                "nope",
                "must be a non-negative integer",
            ),
            (
                "OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS",
                "0",
                "0",
                "must be a positive integer",
            ),
            ("BIOFORMATS_VERSION", "@bad", "@bad", "must be a non-empty version"),
        ]

        for key, raw_value, resolved_value, expected_error in invalid_cases:
            with self.subTest(key=key):
                errors = env_safety_guard.validate_assignment_value(
                    key,
                    raw_value,
                    resolved_value,
                )
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

        valid_cases = [
            ("OMERO_JOB_SERVICE_SECURE", "true", "true"),
            ("OMERO_CLI_PORT", "4064", "4064"),
            ("CONFIG_omero_web_apps", "[]", "[]"),
            ("OMERO_INSTALL_GROUP_LIST", "users:read-write", "users:read-write"),
            ("OMERO_DROPBOX_USER_DIR_MODE", "2775", "2775"),
            ("REDIS_MAXMEMORY", "512mb", "512mb"),
            ("OMERO_DATA_PATH", "/srv/omero", "/srv/omero"),
            ("CONFIG_omero_fs_watchDir", "", ""),
            ("ADMIN_TOOLS_LOG_CACHE_MAX_MB", "0", "0"),
            ("OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS", "1", "1"),
            ("BIOFORMATS_VERSION", "8.5.0", "8.5.0"),
        ]

        for key, raw_value, resolved_value in valid_cases:
            with self.subTest(key=key):
                self.assertEqual(
                    [],
                    env_safety_guard.validate_assignment_value(
                        key,
                        raw_value,
                        resolved_value,
                    ),
                )

    def test_runtime_env_parsers_reject_duplicates_and_unsafe_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "example.env"
            env_path.write_text(
                "\n".join(
                    [
                        "# OPTIONAL='quoted'",
                        'export ACTIVE="quoted"',
                        "ACTIVE=duplicate",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                {"OPTIONAL": "quoted"},
                env_safety_guard.parse_commented_env_assignments(env_path),
            )
            with self.assertRaises(ValueError):
                env_safety_guard.parse_active_env_assignments(env_path)

        self.assertEqual(
            "/srv/omero/data",
            env_safety_guard.resolve_env_references(
                "${ROOT}/$NAME",
                {"ROOT": "/srv/omero", "NAME": "data"},
            ),
        )
        with self.assertRaises(ValueError):
            env_safety_guard.resolve_env_references("$(id)", {})
        with self.assertRaises(ValueError):
            env_safety_guard.resolve_env_references("${ROOT:-/tmp}", {})

    def test_validate_env_file_pair_reports_missing_empty_duplicate_and_bad_values(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            errors = env_safety_guard.validate_env_file_pair(
                repo,
                "env/example.env",
                "env/actual.env",
                {},
            )
            self.assertEqual(["env/example.env: template is missing"], errors)

            (repo / "env").mkdir()
            (repo / "env/example.env").write_text("OMERO_CLI_PORT=4064\n")
            errors = env_safety_guard.validate_env_file_pair(
                repo,
                "env/example.env",
                "env/actual.env",
                {},
            )
            self.assertEqual(["env/actual.env: deployment env file is missing"], errors)

            (repo / "env/actual.env").write_text("", encoding="utf-8")
            errors = env_safety_guard.validate_env_file_pair(
                repo,
                "env/example.env",
                "env/actual.env",
                {},
            )
            self.assertEqual(["env/actual.env: deployment env file is empty"], errors)

            (repo / "env/actual.env").write_text(
                "OMERO_CLI_PORT=bad\nOMERO_CLI_PORT=4064\n",
                encoding="utf-8",
            )
            errors = env_safety_guard.validate_env_file_pair(
                repo,
                "env/example.env",
                "env/actual.env",
                {},
            )
            self.assertEqual(
                ["env/actual.env: actual.env defines OMERO_CLI_PORT more than once"],
                errors,
            )

            (repo / "env/actual.env").write_text(
                "OMERO_CLI_PORT=bad\nUNSUPPORTED=value\n",
                encoding="utf-8",
            )
            errors = env_safety_guard.validate_env_file_pair(
                repo,
                "env/example.env",
                "env/actual.env",
                {},
            )
            self.assertTrue(
                any("unsupported keys: UNSUPPORTED" in error for error in errors)
            )
            self.assertTrue(any("must be a TCP port" in error for error in errors))

    def test_validate_env_file_pair_requires_secret_values_when_template_is_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "env").mkdir()
            (repo / "env/example.env").write_text(
                "OMERO_DB_PASS=\nCROWDSEC_ENROLL_KEY=\n",
                encoding="utf-8",
            )
            (repo / "env/actual.env").write_text(
                "OMERO_DB_PASS=\nCROWDSEC_ENROLL_KEY=\n",
                encoding="utf-8",
            )

            errors = env_safety_guard.validate_env_file_pair(
                repo,
                "env/example.env",
                "env/actual.env",
                {},
            )

            self.assertIn("env/actual.env: OMERO_DB_PASS must not be empty", errors)
            self.assertFalse(
                any(
                    "CROWDSEC_ENROLL_KEY must not be empty" in error for error in errors
                )
            )

    def test_validate_dot_env_values_reports_shape_and_type_errors(self):
        compose_env_files = ",".join(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES)
        repo = self._make_repo(
            ["installation_paths.env"],
            {"installation_paths.env": "OMERO_INSTALLATION_PATH=/srv/omero\n"},
        )
        errors = env_safety_guard.validate_dot_env_values(repo, {})
        self.assertEqual([".env: file is missing"], errors)

        (repo / ".env").write_text(
            "\n".join(
                [
                    "COMPOSE_PROJECT_NAME=wrong",
                    "COMPOSE_ENV_FILES=stale.env",
                    "OMERO_CLI_PORT=bad",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        errors = env_safety_guard.validate_dot_env_values(repo, {})
        self.assertTrue(any("missing required keys" in error for error in errors))
        self.assertTrue(any("COMPOSE_ENV_FILES must be" in error for error in errors))
        self.assertTrue(any("COMPOSE_PROJECT_NAME" in error for error in errors))
        self.assertTrue(
            any("OMERO_CLI_PORT must be a TCP port" in error for error in errors)
        )

        def valid_dot_env_value(key: str) -> str:
            if key in env_safety_guard.DOT_ENV_REQUIRED_ALLOW_EMPTY_KEYS:
                return ""
            if key in env_safety_guard.BOOL_KEYS:
                return "true"
            if key in env_safety_guard.PORT_KEYS or key.endswith("_PORT"):
                return "4064"
            if key in env_safety_guard.FLOAT_KEYS:
                return "1.5"
            if key in env_safety_guard.JSON_KEYS:
                return "[]"
            if key in {"REDIS_MAXMEMORY", "REDIS_DATA_TMPFS_SIZE"}:
                return "512mb"
            if key in env_safety_guard.ABSOLUTE_PATH_KEYS:
                return "/srv/omero"
            if key in env_safety_guard.NON_NEGATIVE_INTEGER_KEYS:
                return "0"
            if key.endswith(env_safety_guard.POSITIVE_INTEGER_SUFFIXES):
                return "1"
            if key.endswith("_VERSION"):
                return "1.0.0"
            return "value"

        dot_env_lines = [
            f"COMPOSE_ENV_FILES={compose_env_files}",
            "COMPOSE_PROJECT_NAME=omero",
        ]
        dot_env_lines.extend(
            f"{key}={valid_dot_env_value(key)}"
            for key in env_safety_guard.DOT_ENV_REQUIRED_KEYS
            if key != "COMPOSE_PROJECT_NAME"
        )
        (repo / ".env").write_text("\n".join(dot_env_lines) + "\n", encoding="utf-8")
        self.assertEqual([], env_safety_guard.validate_dot_env_values(repo, {}))

    # ---- backup command ----

    def test_backup_creates_timestamped_copy(self):
        repo = self._make_repo(
            ["env/omeroweb.env", "installation_paths.env"],
            {
                "env/omeroweb.env": "CONFIG_omero_web_apps=[]",
                "installation_paths.env": "OMERO_DATA_PATH=/data",
            },
        )
        self.assertEqual(env_safety_guard.cmd_backup(repo), 0)

        backups_dir = repo / ".env_backups"
        self.assertTrue(backups_dir.exists())

        backup_dirs = list(backups_dir.iterdir())
        self.assertEqual(len(backup_dirs), 1)
        self.assertEqual(
            backup_dirs[0].stat().st_mode & 0o777,
            env_safety_guard.PRIVATE_DIR_MODE,
        )

        backup_files = list(backup_dirs[0].rglob("*"))
        file_names = {
            f.relative_to(backup_dirs[0]).as_posix()
            for f in backup_files
            if f.is_file()
        }
        self.assertIn("env/omeroweb.env", file_names)
        self.assertIn("installation_paths.env", file_names)

    def test_backup_skips_missing_files_without_failing(self):
        repo = self._make_repo(
            ["env/omeroweb.env", "env/missing.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        self.assertEqual(env_safety_guard.cmd_backup(repo), 0)

    def test_backup_fails_when_all_files_missing(self):
        repo = self._make_repo(["env/missing.env"], {})
        self.assertEqual(env_safety_guard.cmd_backup(repo), 1)

    # ---- restore command ----

    def test_restore_recovers_deleted_files(self):
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "CONFIG_omero_web_apps=[]"},
        )
        env_safety_guard.cmd_backup(repo)

        # Delete the file
        (repo / "env/omeroweb.env").unlink()
        self.assertFalse((repo / "env/omeroweb.env").exists())

        # Restore
        self.assertEqual(env_safety_guard.cmd_restore(repo), 0)
        self.assertTrue((repo / "env/omeroweb.env").exists())
        self.assertEqual(
            (repo / "env/omeroweb.env").read_text(encoding="utf-8"),
            "CONFIG_omero_web_apps=[]",
        )

    def test_restore_specific_backup_by_name(self):
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "version_1"},
        )
        env_safety_guard.cmd_backup(repo)
        first_backup = list((repo / ".env_backups").iterdir())[0].name

        # Modify and backup again
        (repo / "env/omeroweb.env").write_text("version_2", encoding="utf-8")
        env_safety_guard.cmd_backup(repo)

        # Delete and restore from first backup
        (repo / "env/omeroweb.env").unlink()
        self.assertEqual(
            env_safety_guard.cmd_restore(repo, backup_name=first_backup), 0
        )
        self.assertEqual(
            (repo / "env/omeroweb.env").read_text(encoding="utf-8"),
            "version_1",
        )

    def test_restore_rejects_traversal_backup_name(self):
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        env_safety_guard.cmd_backup(repo)

        self.assertEqual(env_safety_guard.cmd_restore(repo, backup_name="../x"), 1)

    def test_restore_refuses_symlinked_backup_files(self):
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        backup_dir = repo / ".env_backups" / "manual"
        backup_dir.mkdir(parents=True)
        external = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(external, ignore_errors=True)
        )
        target = external / "leaked.env"
        target.write_text("SECRET=value", encoding="utf-8")
        (backup_dir / "leaked.env").symlink_to(target)

        self.assertEqual(env_safety_guard.cmd_restore(repo, backup_name="manual"), 1)

    def test_restore_fails_when_no_backups_exist(self):
        repo = self._make_repo(["env/omeroweb.env"], {})
        self.assertEqual(env_safety_guard.cmd_restore(repo), 1)

    # ---- list command ----

    def test_list_shows_available_backups(self):
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        env_safety_guard.cmd_backup(repo)
        self.assertEqual(env_safety_guard.cmd_list(repo), 0)

    # ---- manifest on real repo ----

    def test_real_repo_manifest_exists(self):
        """The .env_manifest file must exist in the repository root."""
        repo_root = Path(__file__).resolve().parent.parent
        manifest = repo_root / ".env_manifest"
        self.assertTrue(
            manifest.exists(),
            f".env_manifest not found at {manifest}",
        )

    def test_real_repo_manifest_has_expected_entries(self):
        """The manifest must list all critical deployment files."""
        repo_root = Path(__file__).resolve().parent.parent
        entries = env_safety_guard.load_manifest(repo_root)
        entry_names = {e.relative_to(repo_root).as_posix() for e in entries}

        expected = {
            ".env",
            "installation_paths.env",
            "env/omeroweb.env",
            "env/omeroserver.env",
            "env/omero_secrets.env",
            "env/grafana.env",
            "env/omero-celery.env",
        }
        self.assertEqual(
            expected,
            entry_names,
            f"Manifest entries do not match expected set. "
            f"Missing: {expected - entry_names}. "
            f"Extra: {entry_names - expected}.",
        )

    def test_real_repo_manifest_entries_are_gitignored(self):
        """Every manifest entry must be covered by .gitignore."""
        repo_root = Path(__file__).resolve().parent.parent
        gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")

        # Simple check: each path or its parent glob must appear in gitignore
        for entry_line in [
            ".env",
            "installation_paths.env",
            "env/*",
        ]:
            self.assertIn(
                entry_line,
                gitignore,
                f"Expected .gitignore to contain '{entry_line}' "
                f"to protect manifest entries.",
            )

    def test_real_repo_backups_dir_is_gitignored(self):
        """The .env_backups directory must be gitignored."""
        repo_root = Path(__file__).resolve().parent.parent
        gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env_backups/", gitignore)

    def test_real_repo_gitignore_behavior_preserves_config_contract(self):
        """Git must ignore local deployment config while keeping examples visible."""
        repo_root = Path(__file__).resolve().parent.parent
        git = shutil.which("git")
        self.assertIsNotNone(git)

        def is_ignored(path: str) -> bool:
            result = subprocess.run(
                [git, "check-ignore", "--no-index", "-q", path],
                cwd=repo_root,
                check=False,
            )
            self.assertIn(result.returncode, {0, 1}, path)
            return result.returncode == 0

        for path in (
            ".env",
            "installation_paths.env",
            "env/omeroweb.env",
            "env/omero_secrets.env",
            ".env_backups/backup.env",
            "logo/logo.png",
            "node_modules/package/index.js",
            "var/runtime/file",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path))

        for path in (
            "installation_paths_example.env",
            "env/omeroweb_example.env",
            "logo/logo_example.png",
            ".github/workflows/tests.yml",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_ignored(path))
