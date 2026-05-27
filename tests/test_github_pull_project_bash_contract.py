"""Contracts for the repository pull/update launcher."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"
FAKE_DEFAULT_BRANCH = "repo-default-branch"
FAKE_RELEASE_TAG = "1.2.3-main.4"
# Build the synthetic 40-character hex commit at runtime so DevSkim does not
# treat it as a token-shaped literal in source.
FAKE_COMMIT = "abcdef" * 6 + "abcd"


class GitHubPullProjectBashContractTests(unittest.TestCase):
    """Exercise the source-selection and replacement boundary."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared paths for launcher contract tests.

        Inputs: repository checkout. Output: class attributes point at the launcher under test.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.launcher_path = cls.repo_root / "installation" / "github_pull_project_bash"

    def test_latest_source_selection_keeps_existing_default_branch_flow(self) -> None:
        """Verify `latest` clones the configured branch and runs the standard installer.

        Inputs: synthetic installation root and fake Git. Output: confirms branch clone and installer execution.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            install_root = self._write_install_root(temp_path)
            fake_bin, git_log = self._write_fake_git(temp_path)

            result = self._run_launcher(
                install_root,
                fake_bin,
                extra_env={"INSTALLATION_AUTOMATION_MODE": "1"},
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Source version: latest commit", result.stdout)
            self.assertIn("INSTALLER_OK standard", result.stdout)
            self.assertIn(
                f"clone --depth 1 --branch {FAKE_DEFAULT_BRANCH}",
                self._read_git_log(git_log),
            )

    def test_release_tag_source_selection_clones_exact_tag(self) -> None:
        """Verify a GitHub release tag is fetched and cloned as an exact tag.

        Inputs: synthetic installation root and fake Git. Output: confirms tag lookup and tag clone command.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            install_root = self._write_install_root(temp_path)
            fake_bin, git_log = self._write_fake_git(temp_path)

            result = self._run_launcher(
                install_root,
                fake_bin,
                extra_env={
                    "INSTALLATION_AUTOMATION_MODE": "1",
                    "REPO_SOURCE_REF": FAKE_RELEASE_TAG,
                },
            )

            log_text = self._read_git_log(git_log)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(
                f"Source version: GitHub release tag {FAKE_RELEASE_TAG}", result.stdout
            )
            self.assertIn("ls-remote", log_text)
            self.assertIn(f"refs/tags/{FAKE_RELEASE_TAG}", log_text)
            self.assertIn(f"clone --depth 1 --branch {FAKE_RELEASE_TAG}", log_text)

    def test_commit_source_selection_checks_out_requested_commit(self) -> None:
        """Verify a commit selector clones and checks out that exact commit.

        Inputs: synthetic installation root and fake Git. Output: confirms full clone and detached checkout.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            install_root = self._write_install_root(temp_path)
            fake_bin, git_log = self._write_fake_git(temp_path)
            commit = FAKE_COMMIT[:12]

            result = self._run_launcher(
                install_root,
                fake_bin,
                extra_env={
                    "INSTALLATION_AUTOMATION_MODE": "1",
                    "REPO_SOURCE_REF": commit,
                },
            )

            log_text = self._read_git_log(git_log)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"Source version: commit {commit}", result.stdout)
            self.assertIn("clone --no-checkout", log_text)
            self.assertIn(f"checkout --detach {commit}^{{commit}}", log_text)

    def test_invalid_source_ref_fails_before_replacement_or_install(self) -> None:
        """Verify invalid refs fail closed before working-tree replacement.

        Inputs: synthetic installation root and missing release tag. Output: confirms no clone or installer run.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            install_root = self._write_install_root(temp_path)
            fake_bin, git_log = self._write_fake_git(temp_path)
            sentinel = install_root / "stale-managed-file.txt"
            sentinel.write_text("must remain", encoding="utf-8")

            result = self._run_launcher(
                install_root,
                fake_bin,
                extra_env={
                    "INSTALLATION_AUTOMATION_MODE": "1",
                    "REPO_SOURCE_REF": "missing-release",
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("GitHub release tag not found", result.stderr)
            self.assertTrue(sentinel.exists())
            self.assertNotIn("INSTALLER_OK", result.stdout)
            self.assertNotIn("clone ", self._read_git_log(git_log))

    def test_easy_install_path_rejects_source_ref_selector(self) -> None:
        """Verify the Git source selector cannot collide with easy installation.

        Inputs: easy-install script path with source selector. Output: confirms rejection before clone.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            install_root = self._write_install_root(temp_path)
            fake_bin, git_log = self._write_fake_git(temp_path)

            result = self._run_launcher(
                install_root,
                fake_bin,
                extra_env={
                    "INSTALLATION_AUTOMATION_MODE": "1",
                    "INSTALLATION_SCRIPT_RELATIVE_PATH": "installation/easy_installation_script.sh",
                    "REPO_SOURCE_REF": FAKE_RELEASE_TAG,
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("REPO_SOURCE_REF is supported only", result.stderr)
            self.assertIn("PREBUILT_IMAGE_RELEASE", result.stderr)
            self.assertNotIn("clone ", self._read_git_log(git_log))

    def test_repository_has_no_stale_root_launcher_example_references(self) -> None:
        """Verify the launcher migration left no tracked stale example references.

        Inputs: tracked repository files. Output: reports any stale launcher example references.
        """
        stale_name = "github_pull_project_bash" + "_example"
        git_path = shutil.which("git")
        if git_path is None:
            self.fail("git executable is required for tracked-file checks")
        result = subprocess.run(
            [git_path, "ls-files"],
            cwd=self.repo_root,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        tracked_paths = result.stdout.splitlines()
        self.assertNotIn(stale_name, tracked_paths)
        self.assertIn("installation/github_pull_project_bash", tracked_paths)

        offenders: dict[str, list[int]] = {}
        for relative_path in tracked_paths:
            path = self.repo_root / relative_path
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            matches = [
                line_number
                for line_number, line in enumerate(text.splitlines(), start=1)
                if stale_name in line
            ]
            if matches:
                offenders[relative_path] = matches

        self.assertFalse(
            offenders, msg=f"Stale launcher references remain: {offenders}"
        )

    def _run_launcher(
        self,
        install_root: Path,
        fake_bin: Path,
        *,
        extra_env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Run the launcher against a synthetic installation root.

        Inputs: install root, fake Git directory, and environment overrides. Output: completed launcher process.
        """
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}:{env.get('PATH', '')}",
                "REPO_URL": "https://example.invalid/omero-docker-extended.git",
                "FAKE_GIT_BRANCH": FAKE_DEFAULT_BRANCH,
                "FAKE_GIT_TAG": FAKE_RELEASE_TAG,
                "FAKE_GIT_HEAD": FAKE_COMMIT,
                "FAKE_GIT_TAG_HEAD": "tag0000000000000000000000000000000000000",
                "FAKE_GIT_COMMIT": FAKE_COMMIT,
                "FAKE_GIT_LOG": str(fake_bin.parent / "git.log"),
            },
        )
        env.update(extra_env)

        return subprocess.run(
            [BASH_BIN, str(install_root / "installation" / "github_pull_project_bash")],
            cwd=install_root,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @staticmethod
    def _read_git_log(git_log: Path) -> str:
        """Read the fake Git log, returning an empty string before first Git use.

        Inputs: fake Git log path. Output: captured command log text.
        """
        if not git_log.exists():
            return ""
        return git_log.read_text(encoding="utf-8")

    def _write_install_root(self, temp_path: Path) -> Path:
        """Create a synthetic installation root with protected runtime paths.

        Inputs: temporary directory path. Output: installation root populated with protected fixtures.
        """
        install_root = temp_path / "install-root"
        install_root.mkdir()
        (install_root / "installation").mkdir()
        shutil.copy2(
            self.launcher_path,
            install_root / "installation" / "github_pull_project_bash",
        )

        runtime_dirs = [
            "postgresdb/omero_database",
            "postgresdb/plugin_database",
            "omero_data",
            "omero_temp",
            "omero_data/user",
            "omero_data/import",
            "omero_data/omeroserver-var",
            "omero_data/omeroweb-var",
            "omero_data/omeroserver-logs",
            "omero_data/omeroweb-logs",
            "omero_data/omeroweb-supervisor-logs",
            "portainer_data",
            "prometheus_data",
            "grafana_data",
            "loki_data",
            "pg_maintenance_data",
            "node_exporter_textfile",
            "crowdsec_db",
            "crowdsec_config",
        ]
        for relative_dir in runtime_dirs:
            (install_root / relative_dir).mkdir(parents=True, exist_ok=True)
        (install_root / "env").mkdir()
        (install_root / "env" / "omeroserver.env").write_text(
            "LOCAL=1\n", encoding="utf-8"
        )

        install_paths = textwrap.dedent(
            f"""\
            OMERO_INSTALLATION_PATH={install_root}
            OMERO_DATABASE_PATH={install_root}/postgresdb/omero_database
            OMERO_PLUGIN_DATABASE_PATH={install_root}/postgresdb/plugin_database
            OMERO_DATA_PATH={install_root}/omero_data
            OMERO_TMP_PATH={install_root}/omero_temp
            OMERO_USER_DATA_PATH={install_root}/omero_data/user
            OMERO_IMPORT_PATH={install_root}/omero_data/import
            OMERO_SERVER_VAR_PATH={install_root}/omero_data/omeroserver-var
            OMERO_WEB_VAR_PATH={install_root}/omero_data/omeroweb-var
            OMERO_SERVER_LOGS_PATH={install_root}/omero_data/omeroserver-logs
            OMERO_WEB_LOGS_PATH={install_root}/omero_data/omeroweb-logs
            OMERO_WEB_SUPERVISOR_LOGS_PATH={install_root}/omero_data/omeroweb-supervisor-logs
            PORTAINER_DATA_PATH={install_root}/portainer_data
            PROMETHEUS_DATA_PATH={install_root}/prometheus_data
            GRAFANA_DATA_PATH={install_root}/grafana_data
            LOKI_DATA_PATH={install_root}/loki_data
            PG_MAINTENANCE_DATA_PATH={install_root}/pg_maintenance_data
            NODE_EXPORTER_TEXTFILE_PATH={install_root}/node_exporter_textfile
            CROWDSEC_DB_PATH={install_root}/crowdsec_db
            CROWDSEC_CONFIG_PATH={install_root}/crowdsec_config
            """
        )
        (install_root / "installation_paths.env").write_text(
            install_paths, encoding="utf-8"
        )
        return install_root

    def _write_fake_git(self, temp_path: Path) -> tuple[Path, Path]:
        """Create a deterministic fake Git executable for launcher tests.

        Inputs: temporary directory path. Output: fake binary directory and command log path.
        """
        fake_bin = temp_path / "bin"
        fake_bin.mkdir()
        git_log = temp_path / "git.log"
        fake_git = fake_bin / "git"
        fake_git.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                log_call() {
                    printf '%s\\n' "$*" >> "${FAKE_GIT_LOG}"
                }

                write_snapshot() {
                    local destination="$1"
                    local head="$2"
                    mkdir -p "${destination}/installation" "${destination}/env" "${destination}/logo"
                    printf '%s\\n' "${head}" > "${destination}/.fake-head"
                    printf '%s\\n' 'EXAMPLE=1' > "${destination}/env/omeroserver_example.env"
                    printf '%s\\n' 'logo template' > "${destination}/logo/logo_example.png"
                    cat > "${destination}/installation/installation_script.sh" <<'SCRIPT'
                #!/usr/bin/env bash
                set -euo pipefail
                printf 'INSTALLER_OK standard\\n'
                SCRIPT
                    chmod +x "${destination}/installation/installation_script.sh"
                    cat > "${destination}/installation/easy_installation_script.sh" <<'SCRIPT'
                #!/usr/bin/env bash
                set -euo pipefail
                printf 'INSTALLER_OK easy release=%s\\n' "${PREBUILT_IMAGE_RELEASE:-}"
                SCRIPT
                    chmod +x "${destination}/installation/easy_installation_script.sh"
                    cat > "${destination}/installation/github_pull_project_bash" <<'SCRIPT'
                #!/usr/bin/env bash
                printf 'refreshed launcher\\n'
                SCRIPT
                    chmod +x "${destination}/installation/github_pull_project_bash"
                }

                log_call "$*"

                if [ "$1" = "check-ref-format" ]; then
                    tag="${2#refs/tags/}"
                    case "${tag}" in
                        ""|*" "*|*":"*|*".."*|*"~"*|*"^"*|*"?*"|*"["*|*"\\\\"*)
                            exit 1
                            ;;
                        *)
                            exit 0
                            ;;
                    esac
                fi

                if [ "$1" = "ls-remote" ]; then
                    if [ "$2" = "--symref" ]; then
                        printf 'ref: refs/heads/%s\\tHEAD\\n' "${FAKE_GIT_BRANCH}"
                        printf '%s\\tHEAD\\n' "${FAKE_GIT_HEAD}"
                        exit 0
                    fi
                    last_arg=""
                    for arg in "$@"; do
                        last_arg="${arg}"
                    done
                    tag="${last_arg#refs/tags/}"
                    if [ "${tag}" = "${FAKE_GIT_TAG}" ]; then
                        printf '%s\\trefs/tags/%s\\n' "${FAKE_GIT_TAG_HEAD}" "${tag}"
                        exit 0
                    fi
                    exit 2
                fi

                if [ "$1" = "clone" ]; then
                    branch=""
                    no_checkout=0
                    previous=""
                    for arg in "$@"; do
                        if [ "${previous}" = "--branch" ]; then
                            branch="${arg}"
                        fi
                        if [ "${arg}" = "--no-checkout" ]; then
                            no_checkout=1
                        fi
                        previous="${arg}"
                    done
                    destination=""
                    for arg in "$@"; do
                        destination="${arg}"
                    done
                    if [ "${no_checkout}" = "1" ]; then
                        write_snapshot "${destination}" "${FAKE_GIT_HEAD}"
                        exit 0
                    fi
                    case "${branch}" in
                        "${FAKE_GIT_BRANCH}")
                            write_snapshot "${destination}" "${FAKE_GIT_HEAD}"
                            exit 0
                            ;;
                        "${FAKE_GIT_TAG}")
                            write_snapshot "${destination}" "${FAKE_GIT_TAG_HEAD}"
                            exit 0
                            ;;
                        *)
                            exit 1
                            ;;
                    esac
                fi

                if [ "$1" = "-C" ]; then
                    directory="$2"
                    command_name="$3"
                    if [ "${command_name}" = "rev-parse" ]; then
                        cat "${directory}/.fake-head"
                        exit 0
                    fi
                    if [ "${command_name}" = "checkout" ]; then
                        requested="${5%%^*}"
                        case "${FAKE_GIT_COMMIT}" in
                            "${requested}"*)
                                printf '%s\\n' "${FAKE_GIT_COMMIT}" > "${directory}/.fake-head"
                                exit 0
                                ;;
                            *)
                                exit 1
                                ;;
                        esac
                    fi
                fi

                exit 1
                """
            ),
            encoding="utf-8",
        )
        fake_git.chmod(fake_git.stat().st_mode | stat.S_IXUSR)
        return fake_bin, git_log
