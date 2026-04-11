"""Contract tests for compressed build workflow integration points."""

from __future__ import annotations

import unittest
from pathlib import Path
import re


class BuildWorkflowIntegrationContractTests(unittest.TestCase):
    """Verify compressed build workflow is wired into update/install scripts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_installation_script_references_compressed_helper(self) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("USE_BUILDX_COMPRESSED_BUILD", script_text)
        self.assertIn("run_image_build()", script_text)
        self.assertIn("docker_buildx_compressed_push.sh", script_text)
        self.assertIn(
            'DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE:-0}"',
            script_text,
        )
        self.assertIn("resolve_flatten_final_image_choice()", script_text)
        self.assertIn('local prompt_hint="Y/n"', script_text)
        self.assertIn(
            "Flatten final images into single-layer outputs? (slower; rebuilds each image)",
            script_text,
        )
        self.assertIn('DOCKER_BUILD_FLATTEN_ONLY="1"', script_text)
        self.assertIn("resolve_build_provenance_setting()", script_text)
        self.assertIn('--provenance "${provenance_setting}"', script_text)
        self.assertNotIn("DOCKER_BUILD_SQUASH", script_text)

    def test_installation_script_checks_build_and_flatten_helper_failures_explicitly(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'if ! compose_with_installation_env "${COMPOSE_FILE}" "${compose_build_args[@]}"; then',
            script_text,
        )
        self.assertIn("ERROR: docker compose build workflow failed.", script_text)
        self.assertIn("ERROR: Compose image flatten workflow failed.", script_text)
        self.assertIn("ERROR: Buildx compressed build workflow failed.", script_text)

    def test_installation_script_propagates_omero_data_dir_into_generated_compose_env(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "        OMERO_TMP_PATH\n        OMERO_DATA_DIR\n        OMERO_USER_DATA_PATH\n",
            script_text,
        )
        self.assertGreaterEqual(
            script_text.count("OMERO_DATA_DIR=${OMERO_DATA_DIR}"), 2
        )
        self.assertIn("OMERO_DATA_DIR=${old_omero_data_dir}", script_text)
        self.assertIn('DEFAULT_OMERO_DATA_DIR="${OMERO_DATA_DIR}"', script_text)
        self.assertIn(
            'require_path_config_var "OMERO_DATA_DIR" "${SCRIPT_ENV_FILE}"', script_text
        )

    def test_installation_script_does_not_inject_top_logo_defaults(self) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ensure_omeroweb_logo_defaults()", script_text)
        self.assertNotIn("CONFIG_omero_web_top__logo=", script_text)
        self.assertNotIn("CONFIG_omero_web_top__logo__link=/webclient/", script_text)

    def test_omeroweb_example_env_defines_only_login_logo_default(self) -> None:
        env_text = (self.repo_root / "env" / "omeroweb_example.env").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "CONFIG_omero_web_login__logo=/static/branding/logo.png", env_text
        )
        self.assertNotIn("CONFIG_omero_web_top__logo=", env_text)
        self.assertNotIn("CONFIG_omero_web_top__logo__link=", env_text)

    def test_omeroweb_dockerfile_applies_logo_context_patch(self) -> None:
        dockerfile_text = (
            self.repo_root / "docker" / "omero-web.Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn("patch_omeroweb_logo_context.py", dockerfile_text)

    def test_installation_group_bootstrap_uses_dynamic_omero_cli_discovery(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'resolve_omero_bin() { local candidate=""; for candidate in /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do [ -x "${candidate}" ] || continue; printf "%s" "${candidate}"; return 0; done; return 1; }',
            script_text,
        )

    def test_server_bootstrap_job_service_uses_cli_autodetection_and_hosted_login(
        self,
    ) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'SERVER_HOME="${SERVER_HOME:-/opt/omero/server/OMERO.server}"', script_text
        )
        self.assertIn("resolve_omero_bin() {", script_text)
        self.assertIn('server_root="${SERVER_HOME%/*}"', script_text)
        self.assertIn(
            'for candidate in "${server_root}"/venv*/bin/omero "${SERVER_HOME}"/bin/omero; do',
            script_text,
        )
        self.assertIn(
            "for candidate in /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do",
            script_text,
        )
        self.assertIn(
            'run_omero -C -s "${host}" -p "${port}" login -u root -w "${root_pass}"',
            script_text,
        )

    def test_server_bootstrap_normalizes_managed_repo_shared_prefixes_for_runtime_groups(
        self,
    ) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'REPO_ROOT_SYNC_HELPER="${SCRIPT_DIR}/repo_root_sync_helper.py"',
            script_text,
        )
        self.assertIn("repo_root_sync_stable_prefix_depth()", script_text)
        self.assertIn("build_repo_root_sync_plan()", script_text)
        self.assertIn("lookup_repo_root_prefix()", script_text)
        self.assertIn(
            'path_list="$(build_repo_root_sync_plan "${venv_py}" "${cli_home}" 2>&1)"',
            script_text,
        )
        self.assertIn(
            'lookup_output="$(lookup_repo_root_prefix "${venv_py}" "${cli_home}" "${root_pass}" "${repo_dir_path}" "${managed_repo_root}" 2>&1)"',
            script_text,
        )
        self.assertIn('run_omero fs mkdir --parents "${repo_dir_path}"', script_text)
        self.assertIn(
            'run_omero chown root "OriginalFile:${root_dir_id}" --force', script_text
        )
        self.assertIn(
            'REPO_ROOT_SYNC_STATUS_FILE="${SERVER_VAR_DIR}/repo-root-sync.status"',
            script_text,
        )
        self.assertIn("write_repo_root_sync_status()", script_text)
        self.assertIn("run_repo_root_bootstrap_once()", script_text)
        self.assertIn("schedule_repo_root_sync()", script_text)
        self.assertIn("validate_repo_root_sync_configuration()", script_text)
        self.assertNotIn("list_repo_root_bootstrap_groups()", script_text)
        self.assertNotIn("collect_repo_root_bootstrap_paths()", script_text)

    def test_server_bootstrap_python_helpers_use_dynamic_server_paths_and_cli_home(
        self,
    ) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('venv_py="$(resolve_server_venv_python)"', script_text)
        self.assertIn("resolve_cli_home()", script_text)
        self.assertIn("run_repo_root_sync_helper()", script_text)
        self.assertIn(
            'runuser -u "${OMERO_CLI_USER}" -- env HOME="${cli_home}" TMPDIR="${TMPDIR:-/tmp}"',
            script_text,
        )
        self.assertIn('"${python_bin}" "${REPO_ROOT_SYNC_HELPER}"', script_text)
        self.assertNotIn("repo-root-lookup.XXXXXX.py", script_text)

    def test_omeroserver_image_copies_repo_root_sync_helper(self) -> None:
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        helper_rel = self.repo_root.joinpath("startup", "repo_root_sync_helper.py")
        helper_name = helper_rel.name
        self.assertIn(
            f"COPY startup/{helper_name} /startup/{helper_name}",
            dockerfile_text,
        )
        self.assertIn(f"/startup/{helper_name}", dockerfile_text)

    def test_server_bootstrap_uses_dedicated_runtime_tmp_slot(self) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"${expected_tmp_dir}/runtime"', script_text)
        self.assertIn('export TMPDIR="${runtime_tmp_dir}"', script_text)
        self.assertIn('ln -sf "${runtime_tmp_dir}" "${legacy_tmp_dir}"', script_text)
        self.assertIn(
            'local legacy_omero_py_user_dir="${expected_tmp_dir}/omero_${requested_owner}"',
            script_text,
        )
        self.assertIn(
            'rm -rf "${omero_py_dir}" "${omero_py_user_dir}" "${legacy_omero_py_user_dir}"',
            script_text,
        )

    def test_server_bootstrap_schedules_binary_repository_cleanse_with_keepalive(
        self,
    ) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("schedule_binary_repository_cleanse()", script_text)
        self.assertIn("cleanup_stale_repository_lock_files()", script_text)
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_ON_START", script_text)
        self.assertIn("OMERO_REPOSITORY_LOCK_CLEANUP_ON_START", script_text)
        self.assertIn("run_omero_with_keepalive", script_text)
        self.assertIn(
            'admin cleanse -q -C -s localhost -p 4064 -u root -w "${root_pass}" "${data_dir}"',
            script_text,
        )
        self.assertIn("proc_start_ticks", script_text)
        self.assertIn("Removed stale repository lock file", script_text)

    def test_installation_script_preserves_server_temp_namespace_ownership(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("ensure_omero_tmp_layout()", script_text)
        self.assertIn('if ! ensure_omero_tmp_layout "${OMERO_TMP_PATH}"', script_text)
        self.assertIn(
            'if [ "${top_level_entry}" = "${server_namespace_dir}" ]; then', script_text
        )
        self.assertIn(
            'chown -R "${server_uid}:${server_gid}" "${server_namespace_dir}"',
            script_text,
        )
        self.assertNotIn('chown_tree_or_die "${OMERO_TMP_PATH}"', script_text)

    def test_installation_script_reports_binary_repository_cleanse_runtime_hook(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("print_binary_repository_cleanse_notice()", script_text)
        self.assertIn(
            "OMERO binary repository cleanse is configured to run automatically on each omeroserver start",
            script_text,
        )
        self.assertIn(
            "OMERO binary repository cleanse will run automatically on the next omeroserver start",
            script_text,
        )

    def test_omeroserver_example_env_defines_binary_repository_cleanse_defaults(
        self,
    ) -> None:
        env_text = (self.repo_root / "env" / "omeroserver_example.env").read_text(
            encoding="utf-8"
        )
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_ON_START=1", env_text)
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_DATA_DIR=/OMERO", env_text)
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS=30", env_text)
        self.assertIn("OMERO_REPOSITORY_LOCK_CLEANUP_ON_START=1", env_text)
        self.assertIn("CONFIG_omero_managed_dir=/OMERO/ManagedRepository", env_text)

    def test_omeroserver_runtime_does_not_force_server_tree_cwd(self) -> None:
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        compose_text = (self.repo_root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("'cd /opt/omero/server'", dockerfile_text)
        self.assertNotIn("working_dir: /opt/omero/server/OMERO.server", compose_text)

    def test_supervisord_sets_writable_gunicorn_chdir_by_default(self) -> None:
        supervisord_text = (self.repo_root / "supervisord.conf").read_text(
            encoding="utf-8"
        )
        env_text = (self.repo_root / "env" / "omeroweb_example.env").read_text(
            encoding="utf-8"
        )
        web_bootstrap_text = (
            self.repo_root / "startup" / "10-web-bootstrap.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("OMERO_WEB_WSGI_ARGS", supervisord_text)
        self.assertIn("--chdir /opt/omero/web/OMERO.web/var/run", supervisord_text)
        self.assertIn(
            "OMERO_WEB_WSGI_ARGS=--chdir /opt/omero/web/OMERO.web/var/run", env_text
        )
        self.assertIn('local run_dir="${var_dir}/run"', web_bootstrap_text)
        self.assertIn('local static_dir="${var_dir}/static"', web_bootstrap_text)
        self.assertIn(
            'ensure_runtime_directory "${var_dir}" "OMERO.web var directory" 0755',
            web_bootstrap_text,
        )
        self.assertIn(
            'ensure_runtime_directory "${var_dir}/omero/tmp" "OMERO.web tmp directory" 1777',
            web_bootstrap_text,
        )
        self.assertIn(
            'ensure_runtime_directory "${run_dir}" "OMERO.web runtime directory" 0755',
            web_bootstrap_text,
        )
        self.assertIn(
            'ensure_runtime_directory "${static_dir}" "OMERO.web static directory" 0755',
            web_bootstrap_text,
        )

    def test_github_pull_script_exports_compressed_build_env(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn("exec env", script_text)
        self.assertIn(
            'USE_BUILDX_COMPRESSED_BUILD="${USE_BUILDX_COMPRESSED_BUILD:-1}"',
            script_text,
        )
        self.assertIn(
            'DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE:-0}"',
            script_text,
        )
        self.assertIn(
            'INSTALLATION_AUTOMATION_MODE="${INSTALLATION_AUTOMATION_MODE}"',
            script_text,
        )

    def test_pull_scripts_enable_transcript_capture(self) -> None:
        scripts = [self.repo_root / "github_pull_project_bash_example"]

        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertIn(
                'TRANSCRIPT_HELPER_PATH="${SCRIPT_DIR}/installation/install_transcript_utils.sh"',
                text,
            )
            self.assertIn(
                'install_transcript_enable "${SCRIPT_DIR}/${INSTALLATION_PATHS_ENV_RELATIVE_PATH}" "$0" "$@"',
                text,
            )

    def test_installation_script_publishes_transcript_destination_after_path_resolution(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'TRANSCRIPT_HELPER_PATH="${SCRIPT_DIR}/install_transcript_utils.sh"',
            script_text,
        )
        self.assertIn(
            'install_transcript_enable "${REPO_ROOT_DIR}/installation_paths.env" "$0" "$@"',
            script_text,
        )
        self.assertIn("install_transcript_publish_final_path_if_needed \\", script_text)
        self.assertIn("tty_echo()", script_text)
        self.assertIn("tty_read_line()", script_text)

    def test_public_pull_script_defaults_to_public_repo(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'REPO_URL="${REPO_URL:-https://github.com/ZMB-UZH/omero-docker-extended.git}"',
            script_text,
        )
        self.assertIn('REPO_BRANCH="${REPO_BRANCH:-main}"', script_text)

    def test_public_pull_script_is_https_only(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("GIT_SSH_COMMAND", script_text)
        self.assertIn("supports only HTTP(S) repository URLs", script_text)

    def test_public_pull_script_protects_runtime_pull_helper(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn("! -name 'github_pull_project_bash'", script_text)

    # ------------------------------------------------------------------
    # CrowdSec conditional probe injection
    # ------------------------------------------------------------------

    def test_prometheus_yml_contains_crowdsec_probe_marker(self) -> None:
        """The marker comment must always be present so the installation script
        can locate the injection point.  The actual CrowdSec probe line may or
        may not be present — the installation script injects it when CrowdSec
        is enabled and removes it when disabled.  Both states are valid for the
        checked-in file."""
        prom_text = (
            self.repo_root / "monitoring" / "prometheus" / "prometheus.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("# CROWDSEC_PROBE_MARKER", prom_text)

    def test_installation_script_injects_crowdsec_probe_conditionally(self) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("CROWDSEC_PROBE_MARKER", script_text)
        self.assertIn("crowdsec:8080/health", script_text)
        self.assertIn("Injected CrowdSec health probe into prometheus.yml", script_text)
        self.assertIn("Removed CrowdSec health probe from prometheus.yml", script_text)

    def test_is_crowdsec_enabled_rejects_both_placeholder_values(self) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('"CHANGEVALUE2"', script_text)
        self.assertIn('"CHANGEVALUE3"', script_text)

    def test_installation_script_schedules_one_shot_crowdsec_restart_only_when_needed(
        self,
    ) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS="${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS:-600}"',
            script_text,
        )
        self.assertIn("prepare_crowdsec_install_bootstrap_enrollment()", script_text)
        self.assertIn(
            'CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="${crowdsec_bootstrap_enroll}" compose_with_installation_env',
            script_text,
        )
        self.assertIn("schedule_crowdsec_install_auto_restart()", script_text)
        self.assertIn("CrowdSec Console Approval Required", script_text)
        self.assertIn(
            "This enrollment request is created during installation", script_text
        )
        self.assertIn("Scheduled one-time CrowdSec install auto-restart", script_text)

    def test_installation_script_prints_crowdsec_banner_before_compose_up(self) -> None:
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        banner_call_index = script_text.rindex(
            'print_crowdsec_install_enrollment_notice "${CROWDSEC_INSTALL_AUTO_RESTART_DELAY_SECONDS}"'
        )
        compose_up_index = script_text.rindex(
            'compose_up_with_retries "${COMPOSE_FILE}"'
        )
        self.assertLess(
            banner_call_index,
            compose_up_index,
            "The CrowdSec approval banner must be emitted before container startup begins.",
        )

    def test_crowdsec_restart_helper_is_single_shot(self) -> None:
        helper_text = (
            self.repo_root / "installation" / "crowdsec_install_auto_restart.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("trap cleanup_marker EXIT HUP INT TERM", helper_text)
        self.assertIn('docker restart "${container_name}"', helper_text)
        self.assertNotIn("while ", helper_text)

    def test_crowdsec_entrypoint_enrolls_only_when_install_bootstrap_is_armed(
        self,
    ) -> None:
        entrypoint_text = (
            self.repo_root / "docker" / "crowdsec-entrypoint.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'CROWDSEC_CONFIG_DIR="${CROWDSEC_CONFIG_DIR:-/etc/crowdsec}"',
            entrypoint_text,
        )
        self.assertIn(
            'CROWDSEC_INSTALL_BOOTSTRAP_ENROLL="${CROWDSEC_INSTALL_BOOTSTRAP_ENROLL:-0}"',
            entrypoint_text,
        )
        self.assertIn("crowdsec_install_enrollment_done_marker_path()", entrypoint_text)
        self.assertIn(
            "CrowdSec install-only enrollment is not armed for this startup. Skipping console enrollment.",
            entrypoint_text,
        )
        self.assertIn("--overwrite", entrypoint_text)

    def test_docker_compose_defaults_crowdsec_install_bootstrap_enroll_to_disabled(
        self,
    ) -> None:
        compose_text = (self.repo_root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'CROWDSEC_INSTALL_BOOTSTRAP_ENROLL: "${CROWDSEC_INSTALL_BOOTSTRAP_ENROLL:-0}"',
            compose_text,
        )

    # ------------------------------------------------------------------
    # Managed repository data-volume binding
    # ------------------------------------------------------------------

    def test_docker_compose_omeroserver_passes_omero_data_dir_and_omero_dir(
        self,
    ) -> None:
        """The omeroserver service MUST pass OMERO_DATA_DIR and OMERO_DIR into
        the container environment so the OMERO server resolves managed
        repository paths against the bind-mounted data volume, not the
        ephemeral server install directory.  Removing these causes imports
        to land inside the container and be lost on restart."""
        compose_text = (self.repo_root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'OMERO_DATA_DIR: "${OMERO_DATA_DIR:?Set OMERO_DATA_DIR',
            compose_text,
        )
        self.assertIn(
            'OMERO_DIR: "${OMERO_DATA_DIR:?Set OMERO_DATA_DIR',
            compose_text,
        )

    def test_server_bootstrap_validates_managed_repository_before_startup(self) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("validate_managed_repository_configuration", script_text)
        self.assertIn("expected_managed_repository_root()", script_text)
        self.assertIn("find_unexpected_server_managed_repository_dirs()", script_text)
        self.assertIn(
            "CONFIG_omero_managed_dir must be an absolute path",
            script_text,
        )

    def test_omeroserver_example_env_uses_absolute_managed_dir(self) -> None:
        """CONFIG_omero_managed_dir in the tracked env template must be an
        absolute path so OMERO never resolves it against the server install
        directory.  A relative value causes silent data loss on restart."""
        env_text = (self.repo_root / "env" / "omeroserver_example.env").read_text(
            encoding="utf-8"
        )
        for line in env_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("CONFIG_omero_managed_dir="):
                value = stripped.split("=", 1)[1]
                self.assertTrue(
                    value.startswith("/"),
                    f"CONFIG_omero_managed_dir must be absolute, got: {value!r}",
                )
                break
        else:
            self.fail("CONFIG_omero_managed_dir not found in omeroserver_example.env")

    def test_server_bootstrap_rejects_managed_dir_outside_omero_dir(self) -> None:
        """The managed-repository guard must check that the configured path
        lives inside OMERO_DIR and must produce a clear error when it does
        not, so the container refuses to start with a misconfigured path."""
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("normalize_dir_path()", script_text)
        self.assertIn(
            "Refusing startup because unexpected image-local managed repository",
            script_text,
        )

    # ------------------------------------------------------------------
    # Coverage pipeline completeness
    # ------------------------------------------------------------------

    def test_coveragerc_tracks_all_python_source_directories(self) -> None:
        """Every plugin/library directory that contains Python source must
        appear in .coveragerc [run] source so coverage.py traces it."""
        expected_dirs = [
            "./omero_plugin_common",
            "./omeroweb_omp_plugin",
            "./omeroweb_import",
            "./omeroweb_admin_tools",
            "./omeroweb_imaris_connector",
            "./omero_web_zarr",
        ]
        coveragerc_text = (self.repo_root / ".coveragerc").read_text(encoding="utf-8")
        for d in expected_dirs:
            self.assertIn(
                d,
                coveragerc_text,
                f"{d} missing from .coveragerc [run] source",
            )

    def test_ci_workflow_runs_all_test_suites(self) -> None:
        """The CI workflow must run every test suite as a separate coverage
        invocation so the conftest mock stubs do not interfere."""
        expected_suites = [
            "tests/",
            "omero_plugin_common/tests/",
            "omeroweb_imaris_connector/tests/",
            "omeroweb_admin_tools/tests/",
            "omeroweb_omp_plugin/tests/",
            "omeroweb_import/tests/",
            "omero_web_zarr/tests/",
        ]
        ci_text = (self.repo_root / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        for suite in expected_suites:
            self.assertIn(
                suite,
                ci_text,
                f"Test suite {suite!r} missing from CI workflow",
            )

    def test_all_workflow_checkout_steps_use_verified_v6_pin(self) -> None:
        expected_checkout = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
        workflow_dir = self.repo_root / ".github" / "workflows"
        for workflow_path in workflow_dir.glob("*.yml"):
            workflow_text = workflow_path.read_text(encoding="utf-8")
            checkout_uses = re.findall(
                r"actions/checkout@[0-9a-f]{40}",
                workflow_text,
            )
            if not checkout_uses:
                continue
            self.assertEqual(
                {expected_checkout},
                set(checkout_uses),
                f"{workflow_path.name} has an unexpected checkout pin",
            )

    def test_security_code_scanning_workflow_includes_zero_delta_alert_gate(
        self,
    ) -> None:
        import yaml  # noqa: F811  — available in CI

        workflow_path = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        security_delta_job = workflow["jobs"]["security-delta"]

        self.assertEqual("security", workflow["name"])
        self.assertEqual("always()", security_delta_job["if"])
        self.assertEqual("read", security_delta_job["permissions"]["actions"])
        self.assertEqual("read", security_delta_job["permissions"]["contents"])
        self.assertEqual("read", security_delta_job["permissions"]["security-events"])
        self.assertEqual("read", security_delta_job["permissions"]["pull-requests"])
        self.assertEqual("ubuntu-24.04", security_delta_job["runs-on"])
        self.assertEqual(
            [
                "codeql",
                "trivy-filesystem",
                "semgrep",
                "bandit",
                "hadolint-discover",
                "hadolint",
                "devskim",
                "osv-scanner-audit",
                "osv-scanner",
                "scorecard",
            ],
            security_delta_job["needs"],
        )

        workflow_text = workflow_path.read_text(encoding="utf-8")
        self.assertIn("python3 tools/security_delta_guard.py", workflow_text)
        self.assertIn('--event-name "$GITHUB_EVENT_NAME"', workflow_text)
        self.assertIn('--event-path "$GITHUB_EVENT_PATH"', workflow_text)
        self.assertIn('--ref "$GITHUB_REF"', workflow_text)
        self.assertIn('--repository "$GITHUB_REPOSITORY"', workflow_text)
        self.assertIn('--run-id "$GITHUB_RUN_ID"', workflow_text)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", workflow_text)

    def test_standalone_security_delta_workflow_is_not_present(self) -> None:
        self.assertFalse(
            (self.repo_root / ".github" / "workflows" / "security-delta.yml").exists()
        )

    def test_codecov_yml_has_component_for_each_source_directory(self) -> None:
        """Each plugin/library tracked in .coveragerc must have a matching
        Codecov project component so per-module coverage is reported."""
        import yaml  # noqa: F811  — available in CI

        codecov_path = self.repo_root / "codecov.yml"
        with open(codecov_path, encoding="utf-8") as fh:
            codecov_cfg = yaml.safe_load(fh)

        project_components = codecov_cfg["coverage"]["status"]["project"]
        # Collect all path prefixes from all components (excluding negation patterns)
        covered_prefixes = set()
        for name, component in project_components.items():
            if name == "default":
                continue
            for path_entry in component.get("paths", []):
                if not path_entry.startswith("!"):
                    covered_prefixes.add(path_entry.rstrip("/"))

        expected_prefixes = {
            "omero_plugin_common",
            "omeroweb_omp_plugin",
            "omeroweb_import",
            "omeroweb_admin_tools",
            "omeroweb_imaris_connector",
            "omero_web_zarr",
        }
        for prefix in expected_prefixes:
            self.assertIn(
                prefix,
                covered_prefixes,
                f"Codecov component for {prefix!r} is missing",
            )

    def test_ci_workflows_install_from_pinned_requirement_manifests(self) -> None:
        tests_workflow = (
            self.repo_root / ".github" / "workflows" / "tests.yml"
        ).read_text(encoding="utf-8")
        security_workflow = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "python3 -m pip install --require-hashes --requirement .github/requirements/tests-ci.txt",
            tests_workflow,
        )
        self.assertIn(
            "python3 -m pip install --require-hashes --requirement .github/requirements/security-code-scanning.txt",
            security_workflow,
        )

    def test_super_linter_workflow_is_pinned_and_covers_repo_hygiene_surfaces(
        self,
    ) -> None:
        import yaml  # noqa: F811  — available in CI

        workflow_path = self.repo_root / ".github" / "workflows" / "super-linter.yml"
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        triggers = workflow[True]

        self.assertEqual("super-linter", workflow["name"])
        self.assertEqual(["main"], triggers["pull_request"]["branches"])
        self.assertEqual(["main"], triggers["push"]["branches"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("ubuntu-24.04", workflow["jobs"]["super-linter"]["runs-on"])

        job_permissions = workflow["jobs"]["super-linter"]["permissions"]
        self.assertEqual("read", job_permissions["contents"])
        self.assertEqual("read", job_permissions["packages"])
        self.assertEqual("write", job_permissions["statuses"])

        steps = workflow["jobs"]["super-linter"]["steps"]
        checkout_step = next(step for step in steps if step.get("name") == "Checkout")
        self.assertEqual(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            checkout_step["uses"],
        )
        self.assertEqual(0, checkout_step["with"]["fetch-depth"])
        self.assertFalse(checkout_step["with"]["persist-credentials"])

        lint_step = next(step for step in steps if step.get("name") == "Super-Linter")
        self.assertEqual(
            "super-linter/super-linter@9e863354e3ff62e0727d37183162c4a88873df41",
            lint_step["uses"],
        )
        self.assertEqual(
            "${{ secrets.GITHUB_TOKEN }}", lint_step["env"]["GITHUB_TOKEN"]
        )
        self.assertEqual(
            "(^|/)third_party/(ecc-v1\\.10\\.0|caveman-v1\\.5\\.0)/",
            lint_step["env"]["FILTER_REGEX_EXCLUDE"],
        )
        self.assertEqual(".", lint_step["env"]["LINTER_RULES_PATH"])
        self.assertEqual(".markdownlint.yaml", lint_step["env"]["MARKDOWN_CONFIG_FILE"])
        self.assertEqual(".yamllint", lint_step["env"]["YAML_CONFIG_FILE"])
        self.assertEqual("true", lint_step["env"]["SAVE_SUPER_LINTER_SUMMARY"])
        self.assertEqual("true", lint_step["env"]["VALIDATE_ALL_CODEBASE"])
        self.assertEqual(
            "true", lint_step["env"]["VALIDATE_GIT_MERGE_CONFLICT_MARKERS"]
        )
        self.assertEqual("true", lint_step["env"]["VALIDATE_GITHUB_ACTIONS"])
        self.assertEqual("true", lint_step["env"]["VALIDATE_GITHUB_ACTIONS_ZIZMOR"])
        self.assertEqual("true", lint_step["env"]["VALIDATE_MARKDOWN"])
        self.assertEqual("true", lint_step["env"]["VALIDATE_YAML"])

        markdown_config = yaml.safe_load(
            (self.repo_root / ".markdownlint.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(400, markdown_config["MD013"]["line_length"])
        self.assertEqual(
            {"siblings_only": True},
            markdown_config["MD024"],
        )
        self.assertFalse(markdown_config["MD033"])
        self.assertEqual(
            "third_party/ecc-v1.10.0/**\nthird_party/caveman-v1.5.0/**\n",
            (self.repo_root / ".markdownlintignore").read_text(encoding="utf-8"),
        )

        yamllint_config = yaml.safe_load(
            (self.repo_root / ".yamllint").read_text(encoding="utf-8")
        )
        self.assertEqual("default", yamllint_config["extends"])
        self.assertEqual(
            1, yamllint_config["rules"]["comments"]["min-spaces-from-content"]
        )
        self.assertEqual("disable", yamllint_config["rules"]["document-start"])
        self.assertEqual("disable", yamllint_config["rules"]["line-length"])
        self.assertEqual("disable", yamllint_config["rules"]["truthy"])

    def test_tests_workflow_uploads_codecov_via_oidc_without_environment_or_secret(
        self,
    ) -> None:
        import yaml  # noqa: F811  — available in CI

        workflow_path = self.repo_root / ".github" / "workflows" / "tests.yml"
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        job = workflow["jobs"]["test-with-coverage"]

        self.assertNotIn("environment", job)
        self.assertEqual(
            {"contents": "read", "id-token": "write"},
            job["permissions"],
        )

        upload_step = next(
            step
            for step in job["steps"]
            if step.get("name") == "Upload coverage to Codecov"
        )

        self.assertEqual(
            "codecov/codecov-action@57e3a136b779b570ffcdbf80b3bdc90e7fab3de2",
            upload_step["uses"],
        )
        self.assertEqual("true", str(upload_step["with"]["use_oidc"]).lower())
        self.assertNotIn("token", upload_step["with"])
        self.assertFalse(
            any(step.get("name") == "Validate Codecov token" for step in job["steps"])
        )

    def test_security_workflow_avoids_unpinned_container_and_template_injection(
        self,
    ) -> None:
        import yaml  # noqa: F811  — available in CI

        workflow_path = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

        self.assertEqual({"contents": "read"}, workflow["permissions"])
        self.assertEqual(
            "semgrep/semgrep:1.156.0@sha256:a3d49dc967b8534a6a76628e50c51cbfe33eb7195dc2feab1fdc0f100852c8ef",
            workflow["jobs"]["semgrep"]["container"]["image"],
        )

        bandit_scope_step = next(
            step
            for step in workflow["jobs"]["bandit"]["steps"]
            if step.get("name") == "Audit — list files in scan scope"
        )
        self.assertEqual(
            "${{ steps.discover.outputs.scan_dirs }}",
            bandit_scope_step["env"]["SCAN_DIRS"],
        )
        self.assertEqual(
            "${{ steps.discover.outputs.test_dirs }}",
            bandit_scope_step["env"]["TEST_DIRS"],
        )
        self.assertIn('find "${scan_dirs[@]}"', bandit_scope_step["run"])
        self.assertNotIn(
            "${{ steps.discover.outputs.scan_dirs }}", bandit_scope_step["run"]
        )
        self.assertNotIn(
            "${{ steps.discover.outputs.test_dirs }}", bandit_scope_step["run"]
        )

        bandit_prod_step = next(
            step
            for step in workflow["jobs"]["bandit"]["steps"]
            if step.get("name")
            == "Run Bandit scan (production code — excludes test directories)"
        )
        self.assertEqual(
            "${{ steps.discover.outputs.scan_dirs }}",
            bandit_prod_step["env"]["SCAN_DIRS"],
        )
        self.assertEqual(
            "${{ steps.discover.outputs.exclude_csv }}",
            bandit_prod_step["env"]["EXCLUDE_CSV"],
        )
        self.assertIn(
            'bandit_cmd=(bandit -r "${scan_dirs[@]}")', bandit_prod_step["run"]
        )
        self.assertNotIn(
            "${{ steps.discover.outputs.scan_dirs }}", bandit_prod_step["run"]
        )
        self.assertNotIn(
            "${{ steps.discover.outputs.exclude_csv }}", bandit_prod_step["run"]
        )

        bandit_test_step = next(
            step
            for step in workflow["jobs"]["bandit"]["steps"]
            if step.get("name")
            == "Run Bandit scan (test code — skips assert and test-credential rules)"
        )
        self.assertEqual(
            "${{ steps.discover.outputs.test_dirs }}",
            bandit_test_step["env"]["TEST_DIRS"],
        )
        self.assertIn('"${test_dirs[@]}"', bandit_test_step["run"])
        self.assertNotIn(
            "${{ steps.discover.outputs.test_dirs }}", bandit_test_step["run"]
        )

        hadolint_audit_step = next(
            step
            for step in workflow["jobs"]["hadolint"]["steps"]
            if step.get("name") == "Audit — show file being scanned"
        )
        self.assertEqual(
            "${{ matrix.dockerfile }}", hadolint_audit_step["env"]["DOCKERFILE_PATH"]
        )
        self.assertIn(
            "printf 'Scanning Dockerfile: %s\\n' \"${DOCKERFILE_PATH}\"",
            hadolint_audit_step["run"],
        )
        self.assertIn('wc -l -- "${DOCKERFILE_PATH}"', hadolint_audit_step["run"])

    def test_security_sarif_upload_jobs_can_read_workflow_run_metadata(self) -> None:
        import yaml  # noqa: F811  — available in CI

        workflow_path = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

        for job_name in (
            "codeql",
            "trivy-filesystem",
            "semgrep",
            "bandit",
            "hadolint",
            "devskim",
        ):
            self.assertEqual(
                "read",
                workflow["jobs"][job_name]["permissions"]["actions"],
                f"{job_name} must grant actions: read so SARIF uploads can resolve workflow run metadata.",
            )

    def test_all_workflow_checkouts_disable_persisted_credentials(self) -> None:
        import yaml  # noqa: F811  — available in CI

        workflows_dir = self.repo_root / ".github" / "workflows"
        for workflow_path in sorted(workflows_dir.glob("*.yml")):
            workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
            for job in workflow.get("jobs", {}).values():
                for step in job.get("steps", []):
                    uses = step.get("uses", "")
                    if uses.startswith("actions/checkout@"):
                        self.assertFalse(
                            step.get("with", {}).get("persist-credentials", True),
                            f"{workflow_path.name} persists checkout credentials",
                        )

    def test_dependabot_updates_define_cooldown_windows(self) -> None:
        import yaml  # noqa: F811  — available in CI

        dependabot_path = self.repo_root / ".github" / "dependabot.yml"
        config = yaml.safe_load(dependabot_path.read_text(encoding="utf-8"))

        for update in config["updates"]:
            self.assertIn("cooldown", update)
            self.assertGreaterEqual(update["cooldown"]["default-days"], 7)

    def test_ci_requirement_manifests_pin_every_dependency(self) -> None:
        requirement_paths = [
            self.repo_root / ".github" / "requirements" / "tests-ci.txt",
            self.repo_root / ".github" / "requirements" / "security-code-scanning.txt",
        ]
        pinned_requirement = re.compile(r"^[A-Za-z0-9_.-]+==[^=].*(?:\s+\\)?$")
        hash_line = re.compile(r"^--hash=sha256:[0-9a-f]{64}(?:\s+\\)?$")

        for requirement_path in requirement_paths:
            requirement_text = requirement_path.read_text(encoding="utf-8")
            current_block: list[str] = []
            for line in requirement_text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("--hash="):
                    current_block.append(stripped)
                    continue

                if current_block:
                    self.assertRegex(
                        current_block[0],
                        pinned_requirement,
                        f"{requirement_path.name} contains an unpinned dependency: {current_block[0]!r}",
                    )
                    self.assertGreaterEqual(
                        len(current_block),
                        2,
                        f"{requirement_path.name} is missing hashes for {current_block[0]!r}",
                    )
                    for hash_entry in current_block[1:]:
                        self.assertRegex(
                            hash_entry,
                            hash_line,
                            f"{requirement_path.name} contains an invalid hash line: {hash_entry!r}",
                        )
                current_block = [stripped]

            if current_block:
                self.assertRegex(
                    current_block[0],
                    pinned_requirement,
                    f"{requirement_path.name} contains an unpinned dependency: {current_block[0]!r}",
                )
                self.assertGreaterEqual(
                    len(current_block),
                    2,
                    f"{requirement_path.name} is missing hashes for {current_block[0]!r}",
                )
                for hash_entry in current_block[1:]:
                    self.assertRegex(
                        hash_entry,
                        hash_line,
                        f"{requirement_path.name} contains an invalid hash line: {hash_entry!r}",
                    )

    def test_ci_requirement_source_manifests_exist(self) -> None:
        source_paths = [
            self.repo_root / ".github" / "requirements" / "tests-ci.in",
            self.repo_root / ".github" / "requirements" / "security-code-scanning.in",
        ]
        for source_path in source_paths:
            self.assertTrue(source_path.exists(), f"{source_path.name} is missing")

    def test_shell_helpers_avoid_global_ifs_mutation(self) -> None:
        extra_packages_script = (
            self.repo_root
            / "helper_scripts_debian"
            / "extra_packages_debian_13_install_script"
        ).read_text(encoding="utf-8")
        docker_analysis_script = (
            self.repo_root / "helper_scripts_debian" / "docker_image_analysis.sh"
        ).read_text(encoding="utf-8")
        public_pull_script = (
            self.repo_root / "github_pull_project_bash_example"
        ).read_text(encoding="utf-8")

        self.assertNotIn("IFS=$'\\n\\t'", extra_packages_script)
        self.assertNotIn("IFS=$'\\n\\t'", docker_analysis_script)
        self.assertNotIn("IFS='/'", public_pull_script)
        self.assertIn(
            'while [ -n "${_remaining_rel}" ]; do',
            public_pull_script,
        )


if __name__ == "__main__":
    unittest.main()
