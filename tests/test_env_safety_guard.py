"""Tests for the env safety guard tool."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from pathlib import Path
from unittest import TestCase, mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import env_safety_guard

ALL_INTERFACES_IPV4 = ".".join(("0", "0", "0", "0"))


class EnvSafetyGuardTests(TestCase):
    """Verify the env safety guard protects deployment config files."""

    def _make_repo(
        self, manifest_lines: list[str], files: dict[str, str] | None = None
    ):
        """A temporary repo root with a manifest and optional files.

        Inputs: `manifest_lines`, `files`. Output: `d`.
        """
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

    def _write_compose_mirror(
        self,
        repo: Path,
        *,
        installation_root: Path | None = None,
        compose_env_files: str | None = None,
        source_overrides: dict[str, str] | None = None,
        dot_overrides: dict[str, str] | None = None,
        include_project_name: bool = True,
    ) -> None:
        """Write complete source and generated Compose mirror fixtures.

        Inputs: fixture paths and optional value overrides. Output: fixture files.
        """
        declared_root = installation_root or repo
        source_values = {
            key: str(declared_root) if key == "OMERO_INSTALLATION_PATH" else "value"
            for key in env_safety_guard.DOT_ENV_MIRRORED_KEYS
        }
        source_values.update(source_overrides or {})
        (repo / "installation_paths.env").write_text(
            "".join(f"{key}={value}\n" for key, value in source_values.items()),
            encoding="utf-8",
        )

        dot_values = {
            key: source_values.get(key, "value")
            for key in env_safety_guard.DOT_ENV_REQUIRED_KEYS
            if key != "COMPOSE_PROJECT_NAME"
        }
        dot_values["REDIS_SAVE_POLICY"] = ""
        dot_values.update(dot_overrides or {})
        env_files = compose_env_files or ",".join(
            env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
        )
        lines = [f"COMPOSE_ENV_FILES={env_files}"]
        if include_project_name:
            lines.append(
                "COMPOSE_PROJECT_NAME="
                f"{env_safety_guard.derive_compose_project_name(declared_root)}"
            )
        lines.extend(f"{key}={value}" for key, value in dot_values.items())
        (repo / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- check command ----

    def test_dot_env_diagnostics_never_print_project_values(self):
        """Reject a mismatched project without disclosing deployment values.

        Inputs: complete generated env fixtures. Output: redacted failure and unchanged files.
        """
        repo = self._make_repo(
            list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
            {
                name: "PLACEHOLDER=value\n"
                for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        private_project = "operator-private-project"
        self._write_compose_mirror(
            repo,
            include_project_name=False,
            dot_overrides={"COMPOSE_PROJECT_NAME": private_project},
        )
        before = (repo / ".env").read_bytes()
        diagnostics = io.StringIO()
        with redirect_stderr(diagnostics):
            self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 1)
        self.assertIn("COMPOSE_PROJECT_NAME", diagnostics.getvalue())
        self.assertNotIn(private_project, diagnostics.getvalue())
        self.assertNotIn(repo.name, diagnostics.getvalue())
        self.assertEqual((repo / ".env").read_bytes(), before)

    def test_dot_env_check_reports_missing_installation_metadata(self):
        """Fail cleanly when the canonical installation identity is unavailable.

        Inputs: an env mirror without installation metadata. Output: failure, not an exception.
        """
        repo = self._make_repo([], {".env": "COMPOSE_PROJECT_NAME=private-project\n"})
        before = (repo / ".env").read_bytes()
        diagnostics = io.StringIO()
        with redirect_stderr(diagnostics):
            self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 1)
        self.assertIn("installation_paths.env", diagnostics.getvalue())
        self.assertNotIn("private-project", diagnostics.getvalue())
        self.assertEqual((repo / ".env").read_bytes(), before)

    def test_dot_env_check_redacts_read_failures(self):
        """Report unreadable and undecodable files without echoing exception details.

        Inputs: isolated read failures. Output: controlled failure and unchanged env files.
        """
        repo = self._make_repo(
            list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
            {
                name: "PLACEHOLDER=value\n"
                for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        self._write_compose_mirror(repo)
        dot_env = repo / ".env"
        before = dot_env.read_bytes()
        read_text = Path.read_text
        for error in (
            PermissionError("private-exception-detail"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "private-exception-detail"),
        ):
            with self.subTest(error=type(error).__name__):

                def fail_dot_env(path, *args, **kwargs):
                    """Fail the selected fixture read; preserve all other file behavior.

                    Inputs: path and read options. Output: original read or injected error.
                    """
                    if path == dot_env:
                        raise error
                    return read_text(path, *args, **kwargs)

                diagnostics = io.StringIO()
                with mock.patch.object(Path, "read_text", fail_dot_env):
                    with redirect_stderr(diagnostics):
                        self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 1)
                self.assertIn(".env could not be read", diagnostics.getvalue())
                self.assertNotIn("private-exception-detail", diagnostics.getvalue())
                self.assertEqual(dot_env.read_bytes(), before)

    def test_project_normalization_always_produces_a_valid_compose_name(self):
        """Normalize punctuation-only and mixed installation names consistently.

        Inputs: portable path components. Output: nonempty ASCII names with a valid prefix.
        """
        for name in ("---", "___", "!!!", " A Name! ", "-9_data", "_UPPER", "a.b"):
            with self.subTest(name=name):
                normalized = env_safety_guard.derive_compose_project_name(Path(name))
                self.assertRegex(normalized, r"^[a-z0-9][a-z0-9_-]*$")
                self.assertEqual(
                    env_safety_guard.derive_compose_project_name(normalized), normalized
                )
        self.assertEqual(env_safety_guard.derive_compose_project_name("!!!"), "omero")

    def test_dot_env_cli_rejects_invalid_encoding_without_a_traceback(self):
        """Exercise the real CLI against an invalid UTF-8 deployment file.

        Inputs: temporary invalid file bytes. Output: redacted nonzero result, no file rewrite.
        """
        repo = self._make_repo([], {".env": "placeholder"})
        payload = b"CONFIG=private-marker\xff\n"
        (repo / ".env").write_bytes(payload)
        result = subprocess.run(
            [
                sys.executable,
                str(Path(env_safety_guard.__file__).resolve()),
                "--repo-root",
                str(repo),
                "dot-env-check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(".env could not be read as UTF-8", result.stderr)
        self.assertNotIn("private-marker", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual((repo / ".env").read_bytes(), payload)

    def test_empty_manifest_blocks_check_compose_and_backup(self):
        """Reject an empty safety manifest before creating or changing files.

        Inputs: an empty temporary manifest. Output: three failures and no backup directory.
        """
        repo = self._make_repo([])
        for command in (
            env_safety_guard.cmd_check,
            env_safety_guard.cmd_compose_guard,
            env_safety_guard.cmd_backup,
        ):
            with self.subTest(command=command.__name__):
                self.assertEqual(command(repo), 1)
        self.assertFalse((repo / env_safety_guard.BACKUP_DIR_NAME).exists())

    def test_backup_directory_rejects_files_and_symlinks_without_modifying_targets(
        self,
    ):
        """Prevent the backup directory helper from following an unsafe target.

        Inputs: a regular file and a symlink. Output: rejection with original bytes and modes.
        """
        repo = self._make_repo([])
        original = repo / "original"
        original.write_text("preserved", encoding="utf-8")
        link = repo / "alias"
        link.symlink_to(original)
        before_mode = original.stat().st_mode
        for path in (original, link):
            with self.subTest(path=path.name):
                with self.assertRaisesRegex(RuntimeError, "unsafe backup directory"):
                    env_safety_guard.ensure_private_dir(path)
        self.assertEqual(original.read_text(encoding="utf-8"), "preserved")
        self.assertEqual(original.stat().st_mode, before_mode)
        self.assertTrue(link.is_symlink())

    def test_backup_timestamp_collision_preserves_both_snapshots(self):
        """Create distinct private snapshots when two backups share a timestamp.

        Inputs: two fixture versions and a fixed clock. Output: unchanged first backup and new second backup.
        """
        repo = self._make_repo(
            ["env/service.env"], {"env/service.env": "VALUE=first\n"}
        )
        source = repo / "env/service.env"
        source.chmod(0o640)
        fixed = env_safety_guard.datetime.now(env_safety_guard.timezone.utc)
        with mock.patch.object(env_safety_guard, "datetime") as clock:
            clock.now.return_value = fixed
            self.assertEqual(env_safety_guard.cmd_backup(repo), 0)
            source.write_text("VALUE=second\n", encoding="utf-8")
            source.chmod(0o600)
            self.assertEqual(env_safety_guard.cmd_backup(repo), 0)
        snapshots = sorted((repo / env_safety_guard.BACKUP_DIR_NAME).iterdir())
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[1].name, f"{snapshots[0].name}_1")
        for snapshot, (value, mode) in zip(
            snapshots, (("first", 0o640), ("second", 0o600)), strict=True
        ):
            saved = snapshot / "env/service.env"
            self.assertEqual(saved.read_text(encoding="utf-8"), f"VALUE={value}\n")
            self.assertEqual(saved.stat().st_mode & 0o777, mode)
            self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o700)

    def test_concurrent_backups_allocate_distinct_private_snapshots(self):
        """Keep simultaneous backups separate even when their timestamps match.

        Inputs: synchronized backups of an isolated fixture. Output: two complete snapshots.
        """
        repo = self._make_repo(["service.env"], {"service.env": "VALUE=preserved\n"})
        backup_root = repo / env_safety_guard.BACKUP_DIR_NAME
        fixed = env_safety_guard.datetime.now(env_safety_guard.timezone.utc)
        barrier = threading.Barrier(2)
        ensure_private_dir = env_safety_guard.ensure_private_dir

        def synchronized_parent(path):
            """Synchronize allocation without replacing actual filesystem operations.

            Inputs: directory path. Output: original private-directory preparation.
            """
            if path == backup_root:
                barrier.wait(timeout=5)
            return ensure_private_dir(path)

        with mock.patch.object(env_safety_guard, "datetime") as clock:
            clock.now.return_value = fixed
            with mock.patch.object(
                env_safety_guard, "ensure_private_dir", synchronized_parent
            ):
                with ThreadPoolExecutor(max_workers=2) as workers:
                    futures = [
                        workers.submit(env_safety_guard.cmd_backup, repo)
                        for _ in range(2)
                    ]
                    self.assertEqual(
                        [future.result(timeout=10) for future in futures], [0, 0]
                    )
        snapshots = list(backup_root.iterdir())
        self.assertEqual(len(snapshots), 2)
        for snapshot in snapshots:
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (snapshot / "service.env").read_text(encoding="utf-8"),
                "VALUE=preserved\n",
            )
        self.assertEqual(
            (repo / "service.env").read_text(encoding="utf-8"), "VALUE=preserved\n"
        )

    def test_template_check_reports_missing_files_and_duplicate_keys_only(self):
        """Report shape errors without disclosing actual or example values.

        Inputs: complete templates with missing or duplicate deployment keys. Output: redacted failures.
        """
        repo = self._make_repo(
            [],
            {
                example: "VALUE=private-example\n"
                for example, _ in env_safety_guard.ENV_TEMPLATE_PAIRS
            },
        )
        diagnostics = io.StringIO()
        with redirect_stderr(diagnostics):
            self.assertEqual(env_safety_guard.cmd_template_check(repo), 1)
        self.assertIn("Missing deployment env file:", diagnostics.getvalue())
        for _, actual in env_safety_guard.ENV_TEMPLATE_PAIRS:
            target = repo / actual
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "VALUE=private-first\nVALUE=private-second\n", encoding="utf-8"
            )
        diagnostics = io.StringIO()
        with redirect_stderr(diagnostics):
            self.assertEqual(env_safety_guard.cmd_template_check(repo), 1)
        self.assertIn("Duplicate keys: VALUE", diagnostics.getvalue())
        self.assertNotIn("private-", diagnostics.getvalue())

    def test_check_passes_when_all_manifest_entries_exist(self):
        """Verify check passes when all manifest entries exist.

        Inputs: repository fixtures. Output: fails on regressions in check passes when all manifest entries exist.
        """
        repo = self._make_repo(
            ["env/omeroweb.env", "installation_paths.env"],
            {
                "env/omeroweb.env": "CONFIG_omero_web_apps=[]",
                "installation_paths.env": "OMERO_DATA_PATH=/data",
            },
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 0)

    def test_check_fails_when_manifest_entry_is_missing(self):
        """Confirm check fails when manifest entry is missing exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in check fails when manifest entry is missing.
        """
        repo = self._make_repo(
            ["env/omeroweb.env", "env/missing.env"],
            {"env/omeroweb.env": "CONFIG_omero_web_apps=[]"},
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 1)

    def test_check_fails_when_manifest_entry_is_empty(self):
        """Confirm check fails when manifest entry is empty exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in check fails when manifest entry is empty.
        """
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": ""},
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 1)

    def test_check_ignores_comment_and_blank_lines_in_manifest(self):
        """Verify check ignores comment and blank lines in manifest.

        Inputs: repository fixtures. Output: fails on regressions in check ignores comment and blank lines in manifest.
        """
        repo = self._make_repo(
            ["# This is a comment", "", "env/omeroweb.env", "  "],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        self.assertEqual(env_safety_guard.cmd_check(repo), 0)

    def test_load_manifest_keeps_symlinked_entries_repo_relative(self):
        """Check that load manifest keeps symlinked entries repo relative remains stable.

        Inputs: repository fixtures. Output: fails on regressions in load manifest keeps symlinked entries repo relative.
        """
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
        """Confirm load manifest rejects absolute or traversal entries is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in load manifest rejects absolute or traversal entries.
        """
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
        """Verify derive compose project name uses installation basename.

        Inputs: repository fixtures. Output: fails on regressions in derive compose project name uses installation basename.
        """
        self.assertEqual(
            env_safety_guard.derive_compose_project_name("/srv/OMERO Live"),
            "omero-live",
        )

    def test_compose_guard_passes_for_canonical_installation_root(self):
        """Verify compose guard passes for canonical installation root.

        Inputs: repository fixtures. Output: fails on regressions in compose guard passes for canonical installation root.
        """
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
        self._write_compose_mirror(repo, compose_env_files=compose_env_files)

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 0)

    def test_compose_guard_fails_for_non_canonical_worktree(self):
        """Confirm compose guard fails for non canonical worktree exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in compose guard fails for non canonical worktree.
        """
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
        self._write_compose_mirror(
            repo,
            installation_root=live_root,
            compose_env_files=compose_env_files,
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_compose_guard_fails_when_dot_env_project_name_is_missing(self):
        """Confirm compose guard fails when dot env project name is missing exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in compose guard fails when dot env project name is missing.
        """
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
        self._write_compose_mirror(
            repo,
            compose_env_files="installation_paths.env",
            include_project_name=False,
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_optional_figure_mirror_preserves_old_installations(self):
        """Reject stale optional build pins without requiring an env migration.

        Inputs: complete temporary env fixtures. Output: presence and value checks.
        """
        for source, mirror, expected_error in (
            (None, None, None),
            ("8.0.1", None, None),
            ("8.0.1", "8.0.1", None),
            ("8.0.1", "7.4.1", "does not match"),
            ("8.0.1", "", "does not match"),
            (None, "8.0.1", "source deployment env is missing"),
        ):
            with self.subTest(source=source, mirror=mirror):
                repo = self._make_repo(
                    list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
                    {
                        relative_path: "CONFIG=value\n"
                        for relative_path in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
                    },
                )
                self._write_compose_mirror(
                    repo,
                    source_overrides=(
                        {"OMERO_FIGURE_VERSION": source} if source is not None else {}
                    ),
                    dot_overrides=(
                        {"OMERO_FIGURE_VERSION": mirror} if mirror is not None else {}
                    ),
                )
                errors = env_safety_guard.validate_dot_env_mirror_values(
                    repo, env_safety_guard.parse_active_env_assignments(repo / ".env")
                )
                if expected_error is None:
                    self.assertEqual(errors, [])
                else:
                    self.assertEqual(len(errors), 1)
                    self.assertIn(expected_error, errors[0])
                    self.assertIn("OMERO_FIGURE_VERSION", errors[0])
                    self.assertNotIn("8.0.1", errors[0])
                    self.assertNotIn("7.4.1", errors[0])

    def test_compose_guard_fails_when_dot_env_mirror_is_stale(self):
        """Reject a stale generated build pin before Compose can consume it.

        Inputs: temporary repository fixtures. Output: a failing guard result.
        """
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
                "env/omeroserver.env": "BIOFORMATS2RAW_VERSION=0.12.1",
                "env/omero_secrets.env": "SECRET=value",
                "env/grafana.env": "GF=value",
                "env/omero-celery.env": "QUEUE=value",
            },
        )
        self._write_compose_mirror(
            repo,
            compose_env_files=compose_env_files,
            source_overrides={"BIOFORMATS2RAW_VERSION": "0.12.1"},
            dot_overrides={"BIOFORMATS2RAW_VERSION": "0.11.0"},
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_compose_guard_fails_when_mirrored_source_key_is_missing(self):
        """Reject generated values that no longer have a deployment source.

        Inputs: complete fixtures with one removed source key. Output: failure.
        """
        repo = self._make_repo(
            list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
            {
                relative_path: "CONFIG=value\n"
                for relative_path in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        self._write_compose_mirror(repo)
        source_path = repo / "installation_paths.env"
        source_path.write_text(
            "\n".join(
                line
                for line in source_path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("BIOFORMATS2RAW_SHA256=")
            )
            + "\n",
            encoding="utf-8",
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_compose_guard_fails_when_source_assignments_are_duplicated(self):
        """Reject ambiguous source env files before comparing generated values.

        Inputs: complete fixtures with a duplicate assignment. Output: failure.
        """
        repo = self._make_repo(
            list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
            {
                relative_path: "CONFIG=value\n"
                for relative_path in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        self._write_compose_mirror(repo)
        source_path = repo / "installation_paths.env"
        with source_path.open("a", encoding="utf-8") as source_file:
            source_file.write("BIOFORMATS2RAW_SHA256=duplicate\n")

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 1)

    def test_dot_env_check_fails_when_dot_env_uses_stale_env_file_list(self):
        """Confirm dot env check fails when dot env uses stale env file list exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in dot env check fails when dot env uses stale env file list.
        """
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
        self._write_compose_mirror(
            repo,
            compose_env_files=",".join(
                env_safety_guard.EXPECTED_COMPOSE_ENV_FILES[:-1]
            ),
        )

        self.assertEqual(env_safety_guard.cmd_compose_guard(repo), 0)
        self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 1)

    def test_dot_env_check_passes_for_complete_generated_dot_env_shape(self):
        """Verify dot env check passes for complete generated dot env shape.

        Inputs: repository fixtures. Output: fails on regressions in dot env check passes for complete generated dot env shape.
        """
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
        self._write_compose_mirror(repo, compose_env_files=compose_env_files)

        self.assertEqual(env_safety_guard.cmd_dot_env_check(repo), 0)

    def test_template_check_passes_when_env_keys_match_examples(self):
        """Check template check passes when env keys match examples renders the expected surface.

        Inputs: repository fixtures. Output: fails on regressions in template check passes when env keys match examples.
        """
        files: dict[str, str] = {}
        manifest_lines = []
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "# comment\nA=example\n\nB=example\n"
            files[actual_rel] = "# different comments are allowed\nA=live\nB=live\n"
            manifest_lines.append(actual_rel)
        repo = self._make_repo(manifest_lines, files)

        self.assertEqual(env_safety_guard.cmd_template_check(repo), 0)

    def test_template_check_reports_missing_extra_and_reordered_keys_only(self):
        """Check template check reports missing extra and reordered keys only renders the expected surface.

        Inputs: repository fixtures. Output: fails on regressions in template check reports missing extra and reordered keys only.
        """
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

    def test_template_check_accepts_configured_optional_keys(self):
        """Verify optional template assignments may be activated deployment-locally.

        Inputs: repository fixtures. Output: fails when optional keys are rejected.
        """
        files: dict[str, str] = {}
        manifest_lines = []
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "A=example\n# OPTIONAL=example\nB=example\n"
            files[actual_rel] = "OPTIONAL=live\nA=live\nB=live\n"
            manifest_lines.append(actual_rel)
        repo = self._make_repo(manifest_lines, files)

        self.assertEqual(env_safety_guard.cmd_template_check(repo), 0)

    def test_optional_web_tiff_pin_preserves_existing_deployment_contract(self):
        """Inputs: old and new server environments. Output: compatible, validated schemas."""
        files = {}
        for example_rel, actual_rel in env_safety_guard.ENV_TEMPLATE_PAIRS:
            files[example_rel] = "A=example\nB=example\n"
            files[actual_rel] = "A=live\nB=live\n"
        example = "env/omeroserver_example.env"
        actual = "env/omeroserver.env"
        files[example] = "TIFFFILE_VERSION=2026.3.3\nWEB_TIFFFILE_VERSION=2026.10.15\n"
        files[actual] = "TIFFFILE_VERSION=2026.3.3\n"
        repo = self._make_repo([], files)
        original = (repo / actual).read_bytes()
        self.assertEqual(env_safety_guard.cmd_template_check(repo), 0)
        self.assertEqual(
            env_safety_guard.validate_env_file_pair(repo, example, actual, {}), []
        )
        self.assertEqual((repo / actual).read_bytes(), original)

        (repo / actual).write_text(
            "TIFFFILE_VERSION=2026.3.3\nWEB_TIFFFILE_VERSION=2026.10.15\n",
            encoding="utf-8",
        )
        self.assertEqual(env_safety_guard.cmd_template_check(repo), 0)
        self.assertEqual(
            env_safety_guard.validate_env_file_pair(repo, example, actual, {}), []
        )
        (repo / actual).write_text(
            "TIFFFILE_VERSION=2026.3.3\nWEB_TIFFFILE_VERSION=@invalid\n",
            encoding="utf-8",
        )
        self.assertTrue(
            any(
                "WEB_TIFFFILE_VERSION" in error
                for error in env_safety_guard.validate_env_file_pair(
                    repo, example, actual, {}
                )
            )
        )

    def test_web_tiff_pin_remains_required_in_unrelated_templates(self):
        """Inputs: an unrelated environment template. Output: its active pin stays required."""
        repo = self._make_repo(
            [],
            {
                "env/example.env": "WEB_TIFFFILE_VERSION=2026.10.15\nA=value\n",
                "env/actual.env": "A=value\n",
            },
        )
        errors = env_safety_guard.validate_env_file_pair(
            repo, "env/example.env", "env/actual.env", {}
        )
        self.assertTrue(
            any("missing required keys: WEB_TIFFFILE_VERSION" in x for x in errors)
        )

    def test_runtime_env_check_reports_missing_extra_and_type_errors(self):
        """Verify runtime env check reports missing extra and type errors.

        Inputs: repository fixtures. Output: fails on regressions in runtime env check reports missing extra and type errors.
        """
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
        """Verify runtime env check accepts optional commented keys and references.

        Inputs: repository fixtures. Output: fails on regressions in runtime env check accepts optional commented keys and references.
        """
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
        """Verify runtime value validators cover supported contract types.

        Inputs: repository fixtures. Output: fails on regressions in runtime value validators cover supported contract types.
        """
        invalid_cases = [
            ("OMERO_JOB_SERVICE_SECURE", "maybe", "maybe", "must be a boolean"),
            (
                "CONFIG_omero_web_debug",
                "true",
                "true",
                "must be disabled in production",
            ),
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
            (
                "PORTAINER_HOST_BIND",
                "localhost",
                "localhost",
                "must be an IPv4 bind address",
            ),
            ("PORTAINER_HOST_BIND", "::1", "::1", "must be an IPv4 bind address"),
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
            (
                "BIOFORMATS_SHA256",
                "ABC",
                "ABC",
                "must be a 64-character lowercase SHA-256 digest",
            ),
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
            ("PORTAINER_HOST_BIND", ALL_INTERFACES_IPV4, ALL_INTERFACES_IPV4),
            ("PORTAINER_HOST_BIND", "127.0.0.1", "127.0.0.1"),
            ("PORTAINER_HOST_BIND", "192.0.2.10", "192.0.2.10"),
            ("OMERO_DATA_PATH", "/srv/omero", "/srv/omero"),
            ("CONFIG_omero_fs_watchDir", "", ""),
            ("ADMIN_TOOLS_LOG_CACHE_MAX_MB", "0", "0"),
            ("OMERO_JOB_SERVICE_SYNC_INTERVAL_SECONDS", "1", "1"),
            ("BIOFORMATS_VERSION", "8.5.0", "8.5.0"),
            ("BIOFORMATS_SHA256", "a" * 64, "a" * 64),
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
        """Confirm runtime env parsers reject duplicates and unsafe references is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions when runtime env parsers reject duplicates and unsafe references stops reporting the expected error.
        """
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
        """Verify validate env file pair reports missing empty duplicate and bad values.

        Inputs: repository fixtures. Output: fails on regressions in validate env file pair reports missing empty duplicate and bad values.
        """
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
        """Check that validate env file pair requires secret values when template is empty keeps sensitive data out of output.

        Inputs: repository fixtures. Output: fails on regressions in validate env file pair requires secret values when template is empty.
        """
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
        """Verify validate dot env values reports shape and type errors.

        Inputs: repository fixtures. Output: fails on regressions in validate dot env values reports shape and type errors.
        """
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
            """Return the value for a key from the valid test dot-env file.

            Inputs: `key`. Output: `str`.
            """
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
            if key == "PORTAINER_HOST_BIND":
                return ALL_INTERFACES_IPV4
            if key in env_safety_guard.ABSOLUTE_PATH_KEYS:
                return "/srv/omero"
            if key in env_safety_guard.NON_NEGATIVE_INTEGER_KEYS:
                return "0"
            if key.endswith(env_safety_guard.POSITIVE_INTEGER_SUFFIXES):
                return "1"
            if key.endswith("_SHA256"):
                return "a" * 64
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
        source_values = {
            key: valid_dot_env_value(key)
            for key in env_safety_guard.DOT_ENV_MIRRORED_KEYS
        }
        for relative_path in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES:
            env_path = repo / relative_path
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text("CONFIG=value\n", encoding="utf-8")
        (repo / "installation_paths.env").write_text(
            "".join(f"{key}={value}\n" for key, value in source_values.items()),
            encoding="utf-8",
        )
        (repo / ".env").write_text("\n".join(dot_env_lines) + "\n", encoding="utf-8")
        self.assertEqual([], env_safety_guard.validate_dot_env_values(repo, {}))

    def test_mirror_rejects_missing_generated_key_without_mutating_sources(self):
        """Inputs: incomplete mirror. Output: exact missing-key error with unchanged files."""
        repo = self._make_repo(
            list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
            {
                name: "CONFIG=value\n"
                for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        self._write_compose_mirror(repo)
        values = env_safety_guard.parse_active_env_assignments(repo / ".env")
        del values["OMERO_INSTALLATION_PATH"]
        before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
        self.assertEqual(
            [".env is missing mirrored key OMERO_INSTALLATION_PATH"],
            env_safety_guard.validate_dot_env_mirror_values(repo, values),
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_mirror_and_monitoring_reject_unsafe_reference_expansions(self):
        """Inputs: shell expressions and cycles. Output: key-only errors and no execution."""
        for unsafe in ("$(echo forbidden)", "${MISSING:-fallback}", "$CYCLE"):
            with self.subTest(expression=unsafe):
                repo = self._make_repo(
                    list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
                    {
                        name: "CONFIG=value\n"
                        for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
                    },
                )
                self._write_compose_mirror(repo)
                web = repo / "env/omeroweb.env"
                web.write_text(
                    f"CYCLE=$CYCLE\nADMIN_TOOLS_LOKI_URL={unsafe}\n",
                    encoding="utf-8",
                )
                values = env_safety_guard.parse_active_env_assignments(repo / ".env")
                values["OMERO_INSTALLATION_PATH"] = unsafe
                mirror_errors = env_safety_guard.validate_dot_env_mirror_values(
                    repo, values
                )
                self.assertEqual(1, len(mirror_errors))
                self.assertTrue(
                    mirror_errors[0].startswith(
                        ".env mirror for OMERO_INSTALLATION_PATH cannot be safely resolved:"
                    )
                )
                self.assertNotIn(unsafe, mirror_errors[0])
                self.assertEqual(
                    ["ADMIN_TOOLS_LOKI_URL cannot be resolved safely"],
                    env_safety_guard.validate_monitoring_tls_urls(repo),
                )

    def test_compose_guard_rejects_missing_installation_identity(self):
        """Inputs: readable files without installation identity. Output: no Compose authorization."""
        repo = self._make_repo(
            ["installation_paths.env"],
            {"installation_paths.env": "UNRELATED=value\n"},
        )
        self.assertEqual(1, env_safety_guard.cmd_compose_guard(repo))
        self.assertEqual(
            "UNRELATED=value\n", (repo / "installation_paths.env").read_text()
        )

    def test_compose_guard_rejects_duplicate_generated_assignment(self):
        """Inputs: duplicate mirror assignment. Output: failure without normalizing either value."""
        repo = self._make_repo(
            list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
            {
                name: "CONFIG=value\n"
                for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        self._write_compose_mirror(repo)
        with (repo / ".env").open("a", encoding="utf-8") as stream:
            stream.write("COMPOSE_PROJECT_NAME=duplicate\n")
        before = (repo / ".env").read_bytes()
        self.assertEqual(1, env_safety_guard.cmd_compose_guard(repo))
        self.assertEqual(before, (repo / ".env").read_bytes())
        self.assertTrue(
            any(
                "COMPOSE_PROJECT_NAME more than once" in error
                for error in env_safety_guard.validate_dot_env_values(repo, {})
            )
        )

    def test_required_mirror_value_cannot_expand_to_empty_or_shell_expression(self):
        """Inputs: syntactically nonempty but unusable values. Output: semantic rejection."""
        for value, expected in (
            ("$UNDEFINED", ".env: OMERO_CLI_PORT must not be empty"),
            ("$(echo forbidden)", ".env: OMERO_CLI_PORT has an unsafe value:"),
        ):
            with self.subTest(value=value):
                repo = self._make_repo(
                    list(env_safety_guard.EXPECTED_COMPOSE_ENV_FILES),
                    {
                        name: "CONFIG=value\n"
                        for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
                    },
                )
                self._write_compose_mirror(
                    repo, dot_overrides={"OMERO_CLI_PORT": value}
                )
                before = (repo / ".env").read_bytes()
                errors = env_safety_guard.validate_dot_env_values(repo, {})
                self.assertTrue(any(error.startswith(expected) for error in errors))
                self.assertTrue(all(value not in error for error in errors))
                self.assertEqual(before, (repo / ".env").read_bytes())

    def test_group_list_allows_empty_segments_but_rejects_missing_permissions(self):
        """Inputs: installer-compatible empty entries. Output: valid groups retained, malformed ones rejected."""
        self.assertEqual([], env_safety_guard.validate_group_list(""))
        self.assertEqual(
            [], env_safety_guard.validate_group_list(",research:read-only,,")
        )
        self.assertEqual(
            ["OMERO_INSTALL_GROUP_LIST entries must be name:permission"],
            env_safety_guard.validate_group_list(",research,,"),
        )

    def test_env_pair_rejects_unsafe_references_and_preserves_optional_empty_values(
        self,
    ):
        """Inputs: recursive or shell-like fixture values. Output: redacted errors without file mutation."""
        for value in ("${OMERO_CLI_PORT}", "$(echo private-fixture-detail)"):
            with self.subTest(value=value):
                repo = self._make_repo(
                    [],
                    {
                        "env/example.env": "OMERO_CLI_PORT=4064\nREDIS_SAVE_POLICY=\n",
                        "env/actual.env": f"OMERO_CLI_PORT={value}\nREDIS_SAVE_POLICY=\n",
                    },
                )
                actual = repo / "env/actual.env"
                before = actual.read_bytes()
                context = {}
                errors = env_safety_guard.validate_env_file_pair(
                    repo, "env/example.env", "env/actual.env", context
                )
                self.assertEqual(1, len(errors))
                self.assertTrue(
                    errors[0].startswith(
                        "env/actual.env: OMERO_CLI_PORT has an unsafe value:"
                    )
                )
                self.assertNotIn(value, errors[0])
                self.assertNotIn("private-fixture-detail", errors[0])
                self.assertEqual("", context["REDIS_SAVE_POLICY"])
                self.assertNotIn("OMERO_CLI_PORT", context)
                self.assertEqual(before, actual.read_bytes())

    def test_source_assignment_read_failure_does_not_expose_exception_detail(self):
        """Inputs: an unreadable source env file. Output: filename-only failure with unchanged bytes."""
        repo = self._make_repo(
            [],
            {
                name: "FIXTURE=value\n"
                for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        first = env_safety_guard.EXPECTED_COMPOSE_ENV_FILES[0]
        before = (repo / first).read_bytes()
        with mock.patch.object(
            env_safety_guard,
            "parse_active_env_assignments",
            side_effect=PermissionError("private-fixture-detail"),
        ):
            with self.assertRaisesRegex(ValueError, "could not be read") as error:
                env_safety_guard.load_compose_source_assignments(repo)
        self.assertNotIn("private-fixture-detail", str(error.exception))
        self.assertEqual(before, (repo / first).read_bytes())

    def test_dot_env_checks_reject_duplicate_keys_and_missing_project_metadata(self):
        """Inputs: duplicate keys and missing canonical project metadata. Output: read-only rejection."""
        repo = self._make_repo(
            [],
            {
                name: "FIXTURE=value\n"
                for name in env_safety_guard.EXPECTED_COMPOSE_ENV_FILES
            },
        )
        self._write_compose_mirror(repo)
        with (repo / ".env").open("a", encoding="utf-8") as stream:
            stream.write("COMPOSE_PROJECT_NAME=private-fixture-detail\n")
        before = (repo / ".env").read_bytes()
        captured = io.StringIO()
        with redirect_stderr(captured):
            self.assertEqual(1, env_safety_guard.cmd_dot_env_check(repo))
        self.assertIn("COMPOSE_PROJECT_NAME more than once", captured.getvalue())
        self.assertNotIn("private-fixture-detail", captured.getvalue())
        self.assertEqual(before, (repo / ".env").read_bytes())
        self._write_compose_mirror(repo)
        (repo / "installation_paths.env").write_text("FIXTURE=value\n")
        errors = env_safety_guard.validate_dot_env_values(repo, {})
        self.assertIn(
            ".env: Missing OMERO_INSTALLATION_PATH in installation_paths.env", errors
        )

    # ---- backup command ----

    def test_backup_creates_timestamped_copy(self):
        """Verify backup creates timestamped copy.

        Inputs: repository fixtures. Output: fails on regressions in backup creates timestamped copy.
        """
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
        """Verify backup skips missing files without failing.

        Inputs: repository fixtures. Output: fails on regressions in backup skips missing files without failing.
        """
        repo = self._make_repo(
            ["env/omeroweb.env", "env/missing.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        self.assertEqual(env_safety_guard.cmd_backup(repo), 0)

    def test_backup_fails_when_all_files_missing(self):
        """Confirm backup fails when all files missing exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in backup fails when all files missing.
        """
        repo = self._make_repo(["env/missing.env"], {})
        self.assertEqual(env_safety_guard.cmd_backup(repo), 1)

    # ---- restore command ----

    def test_restore_recovers_deleted_files(self):
        """Verify restore recovers deleted files.

        Inputs: repository fixtures. Output: fails on regressions in restore recovers deleted files.
        """
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
        """Verify restore specific backup by name.

        Inputs: repository fixtures. Output: fails on regressions in restore specific backup by name.
        """
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
        """Confirm restore rejects traversal backup name is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in restore rejects traversal backup name.
        """
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        env_safety_guard.cmd_backup(repo)

        self.assertEqual(env_safety_guard.cmd_restore(repo, backup_name="../x"), 1)

    def test_restore_refuses_symlinked_backup_files(self):
        """Verify restore refuses symlinked backup files.

        Inputs: repository fixtures. Output: fails on regressions in restore refuses symlinked backup files.
        """
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
        """Confirm restore fails when no backups exist exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions in restore fails when no backups exist.
        """
        repo = self._make_repo(["env/omeroweb.env"], {})
        self.assertEqual(env_safety_guard.cmd_restore(repo), 1)

    # ---- list command ----

    def test_list_shows_available_backups(self):
        """Verify list shows available backups.

        Inputs: repository fixtures. Output: fails on regressions in list shows available backups.
        """
        repo = self._make_repo(
            ["env/omeroweb.env"],
            {"env/omeroweb.env": "CONFIG=value"},
        )
        env_safety_guard.cmd_backup(repo)
        self.assertEqual(env_safety_guard.cmd_list(repo), 0)

    # ---- manifest on real repo ----

    def test_real_repo_manifest_exists(self):
        """Verify real repo manifest exists.

        Inputs: repository fixtures. Output: fails on regressions in real repo manifest exists.
        """
        repo_root = Path(__file__).resolve().parent.parent
        manifest = repo_root / ".env_manifest"
        self.assertTrue(
            manifest.exists(),
            f".env_manifest not found at {manifest}",
        )

    def test_real_repo_manifest_has_expected_entries(self):
        """Verify real repo manifest has expected entries.

        Inputs: repository fixtures. Output: fails on regressions in real repo manifest has expected entries.
        """
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
        """Verify real repo manifest entries are gitignored.

        Inputs: repository fixtures. Output: fails on regressions in real repo manifest entries are gitignored.
        """
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
        """Verify real repo backups dir is gitignored.

        Inputs: repository fixtures. Output: fails on regressions in real repo backups dir is gitignored.
        """
        repo_root = Path(__file__).resolve().parent.parent
        gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env_backups/", gitignore)

    def test_real_repo_gitignore_behavior_preserves_config_contract(self):
        """Check that real repo gitignore behavior preserves config contract remains stable.

        Inputs: repository fixtures. Output: fails on regressions in real repo gitignore behavior preserves config contract.
        """
        repo_root = Path(__file__).resolve().parent.parent
        git = shutil.which("git")
        self.assertIsNotNone(git)

        def is_ignored(path: str) -> bool:
            """Return whether ignored.

            Inputs: `path`. Output: `bool`.
            """
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
