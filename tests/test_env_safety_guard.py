"""Tests for the env safety guard tool."""

from __future__ import annotations

import os
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
            f"COMPOSE_PROJECT_NAME={compose_project_name}\n", encoding="utf-8"
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 0)

    def test_compose_guard_fails_for_non_canonical_worktree(self):
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
            f"COMPOSE_PROJECT_NAME={compose_project_name}\n", encoding="utf-8"
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
