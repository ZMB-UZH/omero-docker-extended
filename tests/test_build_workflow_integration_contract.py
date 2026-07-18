"""Contract tests for compressed build workflow integration points."""

from __future__ import annotations

from iter_test_helpers import next_or_fail

import unittest
from pathlib import Path
import re
import shutil
import subprocess


class BuildWorkflowIntegrationContractTests(unittest.TestCase):
    """Verify compressed build workflow is wired into update/install scripts."""

    DEFAULT_BRANCH_JOB_GUARD = (
        "github.ref_name == github.event.repository.default_branch"
    )

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `BuildWorkflowIntegrationContractTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_installation_script_references_compressed_helper(self) -> None:
        """Verify the installation script references compressed helper execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script references compressed helper integration.
        """
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
        self.assertIn(
            'DOCKER_BUILD_PROGRESS="${DOCKER_BUILD_PROGRESS:-plain}"', script_text
        )
        self.assertIn(
            'local -a compose_build_args=(--progress "${DOCKER_BUILD_PROGRESS:-plain}" build)',
            script_text,
        )
        self.assertNotIn("DOCKER_BUILD_SQUASH", script_text)

    def test_installation_script_keeps_prompts_grouped_without_step_markers(
        self,
    ) -> None:
        """Verify installer prompts keep the grouped pre-build appearance.

        Inputs: repository fixtures. Output: fails on regressions that add
        installation-step labels before or during operator prompts.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("INSTALLATION_PROGRESS_TOTAL", script_text)
        self.assertNotIn("INSTALLATION_PROGRESS_CURRENT", script_text)
        self.assertNotIn("installation_step()", script_text)
        self.assertNotIn('installation_step "', script_text)
        self.assertNotIn("Installation step", script_text)
        self.assertIn("Delete all container images?", script_text)
        self.assertIn("Start containers after build?", script_text)

    def test_installation_script_checks_build_and_flatten_helper_failures_explicitly(
        self,
    ) -> None:
        """Verify the installation script checks build and flatten helper failures explicitly execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script checks build and flatten helper failures explicitly integration.
        """
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

    def test_installation_script_uses_line_oriented_compose_progress_and_single_user_probe(
        self,
    ) -> None:
        """Verify installer output and image-user probing stay deterministic.

        Inputs: repository fixtures. Output: fails on regressions in compose
        progress mode and duplicate user-probe calls.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'COMPOSE_PROGRESS="${COMPOSE_PROGRESS:-${DOCKER_BUILD_PROGRESS:-plain}}"',
            script_text,
        )
        self.assertIn(
            'BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-${DOCKER_BUILD_PROGRESS:-plain}}"',
            script_text,
        )
        self.assertIn(
            'local probe_name="omero-install-probe-user-$RANDOM"', script_text
        )
        self.assertIn(
            'sh -c \'getent passwd "$1" >/dev/null 2>&1\' sh "${candidate}"',
            script_text,
        )
        self.assertIn('sh -c \'id "$1" "$2"\' sh "${id_flag}"', script_text)
        self.assertNotIn(
            "getent passwd '${candidate}' >/dev/null 2>&1\" || true",
            script_text,
        )
        self.assertNotIn("getent passwd '${candidate}'", script_text)
        self.assertNotIn("id ${id_flag} '${user_name}'", script_text)
        self.assertNotIn("omero-install-probe-user-*", script_text)

    def test_installation_script_runs_env_contract_check_before_workflow(self) -> None:
        """Verify the installation script runs env contract check before workflow execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script runs env contract check before workflow integration.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("run_runtime_env_contract_check()", script_text)
        self.assertIn('runtime-env-check "$@"', script_text)
        self.assertIn(
            'run_runtime_env_contract_check "${REPO_ROOT_DIR}" --skip-dot-env',
            script_text,
        )
        self.assertIn(
            'run_runtime_env_contract_check "${OMERO_INSTALLATION_PATH%/}"',
            script_text,
        )
        self.assertLess(
            script_text.index(
                'run_runtime_env_contract_check "${REPO_ROOT_DIR}" --skip-dot-env'
            ),
            script_text.index("resolve_delete_images_choice"),
        )
        self.assertLess(
            script_text.index(
                'run_runtime_env_contract_check "${OMERO_INSTALLATION_PATH%/}"'
            ),
            script_text.index('cd "${OMERO_INSTALLATION_PATH}"'),
        )

    def test_installation_script_propagates_omero_data_dir_into_generated_compose_env(
        self,
    ) -> None:
        """Verify the installation script propagates OMERO data dir into generated compose env execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script propagates OMERO data dir into generated compose env integration.
        """
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
        """Verify the installation script does not inject top logo defaults execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script does not inject top logo defaults integration.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ensure_omeroweb_logo_defaults()", script_text)
        self.assertNotIn("CONFIG_omero_web_top__logo=", script_text)
        self.assertNotIn("CONFIG_omero_web_top__logo__link=/webclient/", script_text)

    def test_omeroweb_example_env_defines_only_login_logo_default(self) -> None:
        """Verify omeroweb example env defines only login logo default.

        Inputs: repository fixtures. Output: fails on regressions in omeroweb example env defines only login logo default.
        """
        env_text = (self.repo_root / "env" / "omeroweb_example.env").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "CONFIG_omero_web_login__logo=/static/branding/logo.png", env_text
        )
        self.assertNotIn("CONFIG_omero_web_top__logo=", env_text)
        self.assertNotIn("CONFIG_omero_web_top__logo__link=", env_text)

    def test_omeroweb_dockerfile_applies_logo_context_patch(self) -> None:
        """Verify omeroweb dockerfile applies logo context patch.

        Inputs: repository fixtures. Output: fails on regressions in omeroweb dockerfile applies logo context patch.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-web.Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn("patch_omeroweb_logo_context.py", dockerfile_text)
        self.assertIn("patch_omeroweb_api_servers.py", dockerfile_text)

    def test_installation_group_bootstrap_uses_dynamic_omero_cli_discovery(
        self,
    ) -> None:
        """Verify the installation group bootstrap uses dynamic OMERO CLI discovery execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation group bootstrap uses dynamic OMERO CLI discovery.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("resolve_omero_bin() {", script_text)
        self.assertIn(
            'OMERO_TMPDIR_VALUE="${OMERO_TMP_PATH%/}/omero-server/tmp"', script_text
        )
        self.assertIn('OMERO_CLI_HOME="$(resolve_cli_home)"', script_text)
        self.assertIn('runuser -p -m -u "${OMERO_CLI_USER}" --', script_text)
        self.assertIn('OMERO_USERDIR="${OMERO_TMPDIR_VALUE}/userdir"', script_text)
        self.assertIn(
            'OMERO_SESSIONDIR="${OMERO_TMPDIR_VALUE}/userdir/sessions"', script_text
        )
        self.assertIn('USER="${OMERO_CLI_USER}"', script_text)
        self.assertIn('LOGNAME="${OMERO_CLI_USER}"', script_text)
        self.assertIn('OMERO_PASSWORD="${ROOTPASS}"', script_text)
        self.assertNotIn('OMERO_TMPDIR_VALUE="/tmp"', script_text)
        self.assertNotIn('HOME="/tmp"', script_text)
        self.assertNotIn("su omero-server", script_text)

    def test_server_bootstrap_job_service_uses_python_api_helper_and_configured_port(
        self,
    ) -> None:
        """Verify server bootstrap job service uses python API helper and configured port.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap job service uses python API helper and configured port.
        """
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
            'JOB_SERVICE_GROUP_SYNC_HELPER="${SCRIPT_DIR}/job_service_group_sync.py"',
            script_text,
        )
        self.assertIn('require_tcp_port_env_var "OMERO_CLI_PORT"', script_text)
        self.assertIn('require_tcp_port_env_var "OMERO_JOB_SERVICE_PORT"', script_text)
        self.assertIn('"${venv_py}"', script_text)
        self.assertIn('"${JOB_SERVICE_GROUP_SYNC_HELPER}"', script_text)
        self.assertIn('--host "${host}"', script_text)
        self.assertIn('--port "${port}"', script_text)
        self.assertNotIn(
            "for candidate in /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do",
            script_text,
        )
        self.assertNotIn("user joingroup", script_text)
        self.assertNotIn("-p 4064", script_text)

    def test_server_bootstrap_normalizes_managed_repo_shared_prefixes_for_runtime_groups(
        self,
    ) -> None:
        """Check server bootstrap normalizes managed repo shared prefixes for runtime groups parsing against the documented contract.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap normalizes managed repo shared prefixes for runtime groups.
        """
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
        """Verify the server bootstrap python helpers use dynamic server paths and CLI home execution contract.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap python helpers use dynamic server paths and CLI home.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('venv_py="$(resolve_server_venv_python)"', script_text)
        self.assertIn("resolve_cli_home()", script_text)
        self.assertIn("resolve_omero_cli_tmpdir()", script_text)
        self.assertIn("run_repo_root_sync_helper()", script_text)
        self.assertIn(
            'TMPDIR="${cli_tmpdir}"',
            script_text,
        )
        self.assertIn('OMERO_TMPDIR="${cli_tmpdir}"', script_text)
        self.assertIn('OMERO_TEMPDIR="${cli_tmpdir}"', script_text)
        self.assertIn('"${python_bin}" "${REPO_ROOT_SYNC_HELPER}"', script_text)
        self.assertNotIn("repo-root-lookup.XXXXXX.py", script_text)

    def test_server_bootstrap_keeps_omero_tmpdir_for_service_user_cli(self) -> None:
        """Check that server bootstrap keeps OMERO tmpdir for service user CLI remains stable.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap keeps OMERO tmpdir for service user CLI.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("resolve_omero_cli_tmpdir() {", script_text)
        self.assertIn('require_nonempty_env_var "OMERO_CLI_USER"', script_text)
        self.assertIn(
            'local candidate="${OMERO_TMPDIR:-${TMPDIR:-${OMERO_TEMPDIR:-}}}"',
            script_text,
        )
        self.assertIn(
            "ERROR: OMERO CLI temp directory is not set. Configure OMERO_TMP_PATH",
            script_text,
        )
        self.assertIn(
            "ERROR: Could not resolve an existing HOME directory for OMERO CLI user",
            script_text,
        )
        self.assertGreaterEqual(script_text.count('TMPDIR="${cli_tmpdir}"'), 4)
        self.assertGreaterEqual(script_text.count('OMERO_TMPDIR="${cli_tmpdir}"'), 4)
        self.assertGreaterEqual(script_text.count('OMERO_TEMPDIR="${cli_tmpdir}"'), 4)
        self.assertNotIn('candidate="/tmp"', script_text)
        self.assertNotIn('cli_home="/tmp"', script_text)
        self.assertNotIn(
            'OMERO_CLI_USER="${OMERO_CLI_USER:-omero-server}"', script_text
        )
        self.assertNotIn('OMERO_TMPDIR="${OMERO_TMPDIR:-}"', script_text)
        self.assertNotIn('OMERO_TEMPDIR="${OMERO_TEMPDIR:-}"', script_text)
        self.assertNotIn('OMERO_TMPDIR="${TMPDIR:-/tmp}"', script_text)
        self.assertNotIn('OMERO_TEMPDIR="${TMPDIR:-/tmp}"', script_text)

    def test_omeroserver_image_copies_repo_root_sync_helper(self) -> None:
        """Verify omeroserver image copies repo root sync helper.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver image copies repo root sync helper.
        """
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

    def test_omeroserver_image_copies_dropbox_user_dir_sync_helper(self) -> None:
        """Verify omeroserver image copies dropbox user dir sync helper.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver image copies dropbox user dir sync helper.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        helper_rel = self.repo_root.joinpath("startup", "dropbox_user_dir_sync.py")
        helper_name = helper_rel.name
        self.assertIn(
            f"COPY startup/{helper_name} /startup/{helper_name}",
            dockerfile_text,
        )
        self.assertIn(f"/startup/{helper_name}", dockerfile_text)

    def test_omeroserver_image_copies_healthcheck_helper(self) -> None:
        """Verify omeroserver image copies healthcheck helper.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver image copies healthcheck helper.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "COPY startup/healthcheck-omeroserver.sh /startup/healthcheck-omeroserver.sh",
            dockerfile_text,
        )
        self.assertIn("/startup/healthcheck-omeroserver.sh", dockerfile_text)

    def test_omeroserver_image_replaces_inherited_config_loader(self) -> None:
        """Verify omeroserver image replaces inherited config loader.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver image replaces inherited config loader.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        config_script_text = (self.repo_root / "startup" / "50-config.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "COPY startup/50-config.py /startup/50-config.py",
            dockerfile_text,
        )
        self.assertIn("/startup/50-config.py", dockerfile_text)
        self.assertIn("def run_omero_config_set", config_script_text)
        self.assertIn("NamedTemporaryFile", config_script_text)
        self.assertNotIn("/opt/omero/server/venv3/bin/omero", config_script_text)

    def test_server_bootstrap_schedules_dropbox_user_dir_sync(self) -> None:
        """Verify server bootstrap schedules dropbox user dir sync.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap schedules dropbox user dir sync.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'DROPBOX_USER_DIR_SYNC_HELPER="${SCRIPT_DIR}/dropbox_user_dir_sync.py"',
            script_text,
        )
        self.assertIn("validate_dropbox_user_dir_sync_configuration()", script_text)
        self.assertIn("write_dropbox_user_dir_sync_status()", script_text)
        self.assertIn("wait_for_dropbox_user_dir_sync_api()", script_text)
        self.assertIn("run_dropbox_user_dir_sync_once()", script_text)
        self.assertIn("schedule_dropbox_user_dir_sync()", script_text)
        self.assertIn("dropbox-user-dir-sync.lock", script_text)
        self.assertIn("dropbox-user-dir-sync.status", script_text)
        self.assertIn(
            'DROPBOX_USER_DIR_SYNC_STATUS_FILE="${SERVER_VAR_DIR}/dropbox-user-dir-sync.status"',
            script_text,
        )
        self.assertNotIn("OMERO_DROPBOX_USER_DIR_SYNC_STATUS_FILE", script_text)
        self.assertIn(
            'write_dropbox_user_dir_sync_status "running" "waiting-for-omero-admin" "0" "0"',
            script_text,
        )
        self.assertIn(
            'write_dropbox_user_dir_sync_status "retrying" "omero-admin-not-ready" "0" "1"',
            script_text,
        )
        self.assertIn(
            'missing_password_message="missing-rootpass"',
            script_text,
        )
        self.assertIn(
            'write_dropbox_user_dir_sync_status "error" "${missing_password_message}" "0" "1"',
            script_text,
        )
        self.assertIn(
            'local startup_wait="${OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS}"',
            script_text,
        )
        self.assertIn('run_dropbox_user_dir_sync_once "${cycle_wait}"', script_text)
        self.assertIn(
            "wait_for_dropbox_user_dir_sync_api \\",
            script_text,
        )
        self.assertIn(
            'OMERO_PASSWORD="${dropbox_bind_value}" run_omero login -q -C -t 60',
            script_text,
        )
        self.assertIn("schedule_dropbox_user_dir_sync", script_text)
        self.assertNotIn("${!password_env-}", script_text)
        self.assertNotIn("OMERO_DROPBOX_USER_DIR_SYNC_ENABLED:-0", script_text)
        self.assertNotIn("65534", script_text)
        self.assertNotIn("/opt/omero/omero_data", script_text)

    def test_server_bootstrap_schedules_dropbox_ice_after_server_start(self) -> None:
        """Verify server bootstrap schedules dropbox ice after server start.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap schedules dropbox ice after server start.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("52-configure-dropbox-ice.sh", dockerfile_text)
        self.assertIn('exe=\\"[$][{]exe[}]\\" activation=', dockerfile_text)
        self.assertIn('activation=\\"manual\\"', dockerfile_text)
        self.assertIn("grep -Fq", dockerfile_text)
        self.assertIn(
            "Failed to set DropBox IceGrid activation to manual",
            dockerfile_text,
        )
        self.assertIn("schedule_dropbox_ice_bootstrap()", script_text)
        self.assertIn("run_dropbox_ice_bootstrap_once()", script_text)
        self.assertIn(
            'DROPBOX_ICE_BOOTSTRAP_STATUS_FILE="${SERVER_VAR_DIR}/dropbox-ice-bootstrap.status"',
            script_text,
        )
        self.assertNotIn("OMERO_DROPBOX_ICE_BOOTSTRAP_STATUS_FILE", script_text)
        self.assertIn(
            'write_dropbox_ice_bootstrap_status "running" "enable-start" "waiting-for-omero-admin" "0"',
            script_text,
        )
        self.assertIn(
            'write_dropbox_ice_bootstrap_status "running" "enable-start" "waiting-for-omero-api" "0"',
            script_text,
        )
        self.assertIn(
            'write_dropbox_ice_bootstrap_status "retrying" "enable" "omero-api-not-ready" "0"',
            script_text,
        )
        self.assertIn(
            'write_dropbox_ice_bootstrap_status "error" "enable" "omero-api-password-missing" "0"',
            script_text,
        )
        self.assertIn(
            "DropBox Ice bootstrap attempt ${attempt} did not complete; retrying in ${poll_interval}s",
            script_text,
        )
        self.assertIn("OMERO_DROPBOX_ICE_BOOTSTRAP_MAX_RETRY_SECONDS", script_text)
        self.assertIn("max_retry_seconds", script_text)
        self.assertIn("retry-budget-exhausted", script_text)
        self.assertIn("run_dropbox_ice_bootstrap_once || rc=$?", script_text)
        self.assertIn(
            "DropBox Ice bootstrap stopped on non-retryable configuration error",
            script_text,
        )
        self.assertIn(
            "wait_for_dropbox_user_dir_sync_api \\",
            script_text,
        )
        self.assertIn(
            'local internal_cfg="${SERVER_HOME}/etc/internal.cfg"', script_text
        )
        self.assertIn("pgrep -f 'icegridnode .*internal\\.cfg'", script_text)
        self.assertIn("run_dropbox_ice_command server list", script_text)
        self.assertNotIn("run_omero admin diagnostics", script_text)
        self.assertIn(
            "run_dropbox_ice_command server enable MonitorServer", script_text
        )
        self.assertIn("run_dropbox_ice_command server enable DropBox", script_text)
        self.assertIn("start_dropbox_ice_server MonitorServer", script_text)
        self.assertIn("start_dropbox_ice_server DropBox", script_text)
        self.assertIn("OMERO_DROPBOX_ENABLED", script_text)
        self.assertNotIn(
            "OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS:-", script_text
        )
        self.assertNotIn(
            "OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS:-",
            script_text,
        )
        self.assertNotIn("retrying in 60s", script_text)
        self.assertNotIn("sleep 60", script_text)

    def test_installation_dropbox_readiness_waits_do_not_use_hidden_defaults(
        self,
    ) -> None:
        """Verify installation dropbox readiness waits do not use hidden defaults.

        Inputs: repository fixtures. Output: fails on regressions in installation dropbox readiness waits do not use hidden defaults.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'local enabled="${OMERO_DROPBOX_ENABLED:?OMERO_DROPBOX_ENABLED is required}"',
            script_text,
        )
        self.assertIn(
            'local status_file="${server_var_path%/}/dropbox-ice-bootstrap.status"',
            script_text,
        )
        self.assertIn(
            'local enabled="${OMERO_DROPBOX_USER_DIR_SYNC_ENABLED:?OMERO_DROPBOX_USER_DIR_SYNC_ENABLED is required}"',
            script_text,
        )
        self.assertIn(
            'local status_file="${server_var_path%/}/dropbox-user-dir-sync.status"',
            script_text,
        )
        self.assertNotIn("OMERO_DROPBOX_ENABLED:-0", script_text)
        self.assertNotIn("OMERO_DROPBOX_USER_DIR_SYNC_ENABLED:-0", script_text)
        self.assertNotIn(
            "OMERO_DROPBOX_ICE_BOOTSTRAP_STARTUP_WAIT_SECONDS:-300", script_text
        )
        self.assertNotIn(
            "OMERO_DROPBOX_ICE_BOOTSTRAP_READINESS_POLL_SECONDS:-10", script_text
        )
        self.assertNotIn("OMERO_DROPBOX_USER_DIR_SYNC_MAX_RETRIES:-3", script_text)
        self.assertNotIn(
            "OMERO_DROPBOX_USER_DIR_SYNC_READINESS_POLL_SECONDS:-10",
            script_text,
        )
        self.assertNotIn(
            "OMERO_DROPBOX_USER_DIR_SYNC_STARTUP_WAIT_SECONDS:-300",
            script_text,
        )
        self.assertIn(
            "deadline_epoch=$(( $(date +%s) + max_wait_seconds ))",
            script_text,
        )
        self.assertIn(
            "DropBox Ice bootstrap reported a non-retryable error",
            script_text,
        )
        self.assertIn(
            "DropBox user directory synchronization reported a non-retryable error",
            script_text,
        )
        self.assertIn(
            "WARNING: Timed out waiting for DropBox Ice bootstrap status",
            script_text,
        )
        self.assertIn(
            "WARNING: Timed out waiting for DropBox user directory synchronization status",
            script_text,
        )

    def test_installation_runs_job_service_group_sync_before_dropbox_waits(
        self,
    ) -> None:
        """Verify installation runs job service group sync before dropbox waits.

        Inputs: repository fixtures. Output: fails on regressions in installation runs job service group sync before dropbox waits.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")

        job_service_index = script_text.rindex(
            'add_job_service_to_install_groups "${COMPOSE_FILE}"'
        )
        dropbox_ice_wait_index = script_text.rindex(
            'wait_for_dropbox_ice_bootstrap_ready "${startup_sync_started_epoch}"'
        )
        dropbox_user_wait_index = script_text.rindex(
            'wait_for_dropbox_user_dir_sync_ready "${startup_sync_started_epoch}"'
        )

        self.assertLess(job_service_index, dropbox_ice_wait_index)
        self.assertLess(job_service_index, dropbox_user_wait_index)
        self.assertIn("dropbox_ice_wait_rc=$?", script_text)
        self.assertIn("dropbox_user_dir_wait_rc=$?", script_text)

    def test_server_bootstrap_uses_dedicated_runtime_tmp_slot(self) -> None:
        """Verify server bootstrap uses dedicated runtime tmp slot.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap uses dedicated runtime tmp slot.
        """
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
        """Verify server bootstrap schedules binary repository cleanse with keepalive.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap schedules binary repository cleanse with keepalive.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("schedule_binary_repository_cleanse()", script_text)
        self.assertIn("cleanup_stale_repository_lock_files()", script_text)
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_ON_START", script_text)
        self.assertIn("OMERO_REPOSITORY_LOCK_CLEANUP_ON_START", script_text)
        self.assertIn("run_omero_with_keepalive", script_text)
        self.assertIn(
            'OMERO_PASSWORD="${root_pass}" run_omero_with_keepalive',
            script_text,
        )
        self.assertIn(
            'admin cleanse -q -C -s "${OMERO_CLI_HOST}" -p "${OMERO_CLI_PORT}" -u root "${data_dir}"',
            script_text,
        )
        self.assertIn("proc_start_ticks", script_text)
        self.assertIn("Removed stale repository lock file", script_text)

    def test_startup_and_installation_do_not_put_root_passwords_in_argv(
        self,
    ) -> None:
        """Verify startup and installation keep root passwords out of argv.

        Inputs: repository fixtures. Output: fails on regressions that expose root passwords in process arguments.
        """
        startup_text = (
            self.repo_root / "startup" / "10-server-bootstrap.sh"
        ).read_text(encoding="utf-8")
        installation_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        repo_helper_text = (
            self.repo_root / "startup" / "repo_root_sync_helper.py"
        ).read_text(encoding="utf-8")

        forbidden_startup_snippets = (
            '-w "${root_pass}"',
            "root_pass = sys.argv[1]",
            "os.system(cmd)",
            '--root-pass "${root_pass}"',
        )
        for snippet in forbidden_startup_snippets:
            self.assertNotIn(snippet, startup_text)

        self.assertIn('OMERO_PASSWORD="${root_pass}" run_omero', startup_text)
        self.assertIn('runuser -p -m -u "${OMERO_CLI_USER}" -- "$@"', startup_text)
        self.assertIn('export OMERO_USERDIR="${cli_tmpdir}/userdir"', startup_text)
        self.assertIn(
            'export OMERO_SESSIONDIR="${OMERO_USERDIR}/sessions"', startup_text
        )
        self.assertIn('export USER="${OMERO_CLI_USER}"', startup_text)
        self.assertIn('export LOGNAME="${OMERO_CLI_USER}"', startup_text)
        self.assertIn("--root-password-env ROOTPASS", startup_text)
        self.assertIn('"OMERO_PASSWORD": root_pass', startup_text)
        self.assertNotIn('runuser -u "${OMERO_CLI_USER}" -- env', startup_text)
        self.assertNotIn('-e ROOTPASS="${ROOTPASS}"', installation_text)
        self.assertNotIn('-e OMERO_JOB_SERVICE_PASS="${job_pass}"', installation_text)
        self.assertIn(
            'ROOTPASS="${ROOTPASS}" compose_with_installation_env', installation_text
        )
        self.assertIn("-e ROOTPASS \\", installation_text)
        self.assertIn(
            'OMERO_JOB_SERVICE_PASS="${job_pass}" compose_with_installation_env',
            installation_text,
        )
        self.assertIn('runuser -p -m -u "${OMERO_CLI_USER}" --', installation_text)
        self.assertIn("--root-password-env", repo_helper_text)
        self.assertNotIn('add_argument("--root-pass"', repo_helper_text)
        self.assertNotIn("args.root_pass or", repo_helper_text)
        self.assertNotIn("args.root_pass,", repo_helper_text)

    def test_installation_script_preserves_server_temp_namespace_ownership(
        self,
    ) -> None:
        """Check that installation script preserves server temp namespace ownership remains stable.

        Inputs: repository fixtures. Output: fails on regressions in installation script preserves server temp namespace ownership integration.
        """
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
        """Verify the installation script reports binary repository cleanse runtime hook execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script reports binary repository cleanse runtime hook integration.
        """
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
        """Verify omeroserver example env defines binary repository cleanse defaults.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver example env defines binary repository cleanse defaults.
        """
        env_text = (self.repo_root / "env" / "omeroserver_example.env").read_text(
            encoding="utf-8"
        )
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_ON_START=1", env_text)
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_DATA_DIR=/OMERO", env_text)
        self.assertIn("OMERO_BINARY_REPO_CLEANSE_KEEPALIVE_SECONDS=30", env_text)
        self.assertIn("OMERO_REPOSITORY_LOCK_CLEANUP_ON_START=1", env_text)
        self.assertIn("CONFIG_omero_managed_dir=/OMERO/ManagedRepository", env_text)

    def test_omeroserver_runtime_does_not_force_server_tree_cwd(self) -> None:
        """Verify omeroserver runtime does not force server tree cwd.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver runtime does not force server tree cwd.
        """
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        compose_text = (self.repo_root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("'cd /opt/omero/server'", dockerfile_text)
        self.assertNotIn("working_dir: /opt/omero/server/OMERO.server", compose_text)

    def test_database_secret_values_are_not_compose_interpolation_inputs(
        self,
    ) -> None:
        """Check that database secret values are not compose interpolation inputs keeps sensitive data out of output.

        Inputs: repository fixtures. Output: fails on regressions in database secret values are not compose interpolation inputs.
        """
        compose_text = (self.repo_root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        omero_db_pass_config_key = "CONFIG_" + "omero_db_pass"

        self.assertNotIn("POSTGRES_" + "PASSWORD:", compose_text)
        self.assertNotIn("DATA_" + "SOURCE_NAME:", compose_text)
        self.assertNotIn(
            f'{omero_db_pass_config_key}: "${{OMERO_DB_PASS',
            compose_text,
        )
        self.assertIn("OMERO_POSTGRES_PASSWORD_SOURCE: main", compose_text)
        self.assertIn("OMERO_POSTGRES_PASSWORD_SOURCE: plugin", compose_text)
        self.assertIn("OMERO_POSTGRES_EXPORTER_SOURCE: main", compose_text)
        self.assertIn("OMERO_POSTGRES_EXPORTER_SOURCE: plugin", compose_text)
        self.assertIn(
            "./docker/postgres-entrypoint-from-env.sh:/usr/local/bin/postgres-entrypoint-from-env.sh:ro",
            compose_text,
        )
        self.assertIn(
            "./monitoring/postgres-exporter/entrypoint.sh:/postgres-exporter-entrypoint.sh:ro",
            compose_text,
        )
        self.assertIn(
            'export CONFIG_omero_db_pass=\\"\\$OMERO_DB_PASS\\"',
            dockerfile_text,
        )

    def test_secret_derivation_entrypoints_are_tracked_and_executable(self) -> None:
        """Check that secret derivation entrypoints are tracked and executable keeps sensitive data out of output.

        Inputs: repository fixtures. Output: fails on regressions in secret derivation entrypoints are tracked and executable.
        """
        for relative_path in (
            "docker/postgres-entrypoint-from-env.sh",
            "monitoring/postgres-exporter/entrypoint.sh",
        ):
            with self.subTest(relative_path=relative_path):
                script_path = self.repo_root / relative_path
                script_text = script_path.read_text(encoding="utf-8")
                git_executable = shutil.which("git")
                self.assertIsNotNone(
                    git_executable,
                    "git executable is required to check tracked file modes.",
                )
                git_mode = subprocess.check_output(
                    [git_executable, "ls-files", "-s", relative_path],
                    cwd=self.repo_root,
                    text=True,
                    encoding="utf-8",
                ).split(maxsplit=1)[0]
                self.assertEqual("100755", git_mode)
                self.assertIn("set -eu", script_text)
                self.assertIn("Missing required environment variable", script_text)

    def test_supervisord_uses_writable_gunicorn_runtime_by_default(self) -> None:
        """Verify supervisord uses the installation-agnostic Gunicorn launcher.

        Inputs: repository fixtures. Output: fails on Gunicorn runtime path regressions.
        """
        supervisord_text = (self.repo_root / "supervisord.conf").read_text(
            encoding="utf-8"
        )
        dockerfile_text = (self.repo_root / "docker" / "omero-web.Dockerfile").read_text(
            encoding="utf-8"
        )
        env_text = (self.repo_root / "env" / "omeroweb_example.env").read_text(
            encoding="utf-8"
        )
        launcher_text = (
            self.repo_root / "startup" / "30-start-omero-web.sh"
        ).read_text(encoding="utf-8")
        web_bootstrap_text = (
            self.repo_root / "startup" / "10-web-bootstrap.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("command=/opt/omero/web/bin/start-omero-web.sh", supervisord_text)
        self.assertIn(
            "COPY startup/30-start-omero-web.sh /opt/omero/web/bin/start-omero-web.sh",
            dockerfile_text,
        )
        self.assertIn("OMERO_WEB_RUNTIME_DIR", launcher_text)
        self.assertIn("OMERO_WEB_GUNICORN_CONTROL_SOCKET", launcher_text)
        self.assertIn('*) wsgi_args="${wsgi_args} --control-socket', launcher_text)
        self.assertIn(
            "OMERO_WEB_WSGI_ARGS=--chdir /opt/omero/web/OMERO.web/var/run "
            "--control-socket /opt/omero/web/OMERO.web/var/run/gunicorn.ctl",
            env_text,
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

    def test_supervisord_uses_private_socket_without_checked_in_auth(self) -> None:
        """Verify the supervisord uses private socket without checked in auth safety boundary.

        Inputs: repository fixtures. Output: fails on regressions when supervisord uses private socket without checked in auth accepts unsafe input.
        """
        supervisord_text = (self.repo_root / "supervisord.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("file=/tmp/supervisor.sock", supervisord_text)
        self.assertIn("chmod=0700", supervisord_text)
        self.assertNotIn("username=%(ENV_SUPERVISOR_", supervisord_text)
        self.assertNotIn("password=%(ENV_SUPERVISOR_", supervisord_text)

    def test_github_pull_script_exports_compressed_build_env(self) -> None:
        """Verify the github pull script exports compressed build env execution contract.

        Inputs: repository fixtures. Output: fails on regressions in github pull script exports compressed build env integration.
        """
        script_text = (
            self.repo_root / "installation" / "github_pull_project_bash"
        ).read_text(encoding="utf-8")
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
        """Verify pull scripts enable transcript capture.

        Inputs: repository fixtures. Output: fails on regressions in pull scripts enable transcript capture.
        """
        scripts = [self.repo_root / "installation" / "github_pull_project_bash"]

        for script in scripts:
            text = script.read_text(encoding="utf-8")
            self.assertIn(
                'TRANSCRIPT_HELPER_PATH="${SCRIPT_DIR}/install_transcript_utils.sh"',
                text,
            )
            self.assertIn(
                'install_transcript_enable "${REPO_ROOT_DIR}/${INSTALLATION_PATHS_ENV_RELATIVE_PATH}" "$0" "$@"',
                text,
            )

    def test_installation_script_publishes_transcript_destination_after_path_resolution(
        self,
    ) -> None:
        """Verify the installation script publishes transcript destination after path resolution execution contract.

        Inputs: repository fixtures. Output: fails on regressions when installation script publishes transcript destination after path resolution accepts unsafe input.
        """
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

    def test_public_pull_script_defaults_to_public_repo_and_remote_default_branch(
        self,
    ) -> None:
        """Verify the public pull script defaults to public repo and remote HEAD.

        Inputs: repository fixtures. Output: fails on hard-coded branch defaults.
        """
        script_text = (
            self.repo_root / "installation" / "github_pull_project_bash"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'REPO_URL="${REPO_URL:-https://github.com/ZMB-UZH/omero-docker-extended.git}"',
            script_text,
        )
        self.assertIn('REPO_BRANCH="${REPO_BRANCH:-}"', script_text)
        self.assertIn("resolve_latest_repo_branch()", script_text)
        self.assertIn('git ls-remote --symref "${REPO_URL}" HEAD', script_text)
        self.assertNotIn('REPO_BRANCH="${REPO_BRANCH:-main}"', script_text)

    def test_public_pull_script_is_https_only(self) -> None:
        """Verify the public pull script is https only execution contract.

        Inputs: repository fixtures. Output: fails on regressions in public pull script is https only integration.
        """
        script_text = (
            self.repo_root / "installation" / "github_pull_project_bash"
        ).read_text(encoding="utf-8")
        self.assertNotIn("GIT_SSH_COMMAND", script_text)
        self.assertIn("supports only HTTP(S) repository URLs", script_text)

    def test_public_pull_script_refreshes_tracked_installation_launcher(self) -> None:
        """Verify the public pull script refreshes the tracked installation launcher.

        Inputs: repository fixtures. Output: fails on stale root-launcher protection.
        """
        script_text = (
            self.repo_root / "installation" / "github_pull_project_bash"
        ).read_text(encoding="utf-8")
        self.assertIn('REPO_ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"', script_text)
        self.assertIn(
            'replace_working_tree_with_clone "${BOOTSTRAP_CLONE_DIR}" "${REPO_ROOT_DIR}"',
            script_text,
        )
        self.assertNotIn("! -name 'github_pull_project_bash'", script_text)

    # ------------------------------------------------------------------
    # CrowdSec conditional probe injection
    # ------------------------------------------------------------------

    def test_prometheus_yml_contains_crowdsec_probe_marker(self) -> None:
        """Verify prometheus yml contains crowdsec probe marker.

        Inputs: repository fixtures. Output: fails on regressions in prometheus yml contains crowdsec probe marker.

        The installation script uses the marker as the injection point. The actual
        CrowdSec probe line may or may not be present — the installation script
        injects it when CrowdSec is enabled and removes it when disabled. Both
        states are valid for the checked-in file.
        """
        prom_text = (
            self.repo_root / "monitoring" / "prometheus" / "prometheus.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("# CROWDSEC_PROBE_MARKER", prom_text)

    def test_installation_script_injects_crowdsec_probe_conditionally(self) -> None:
        """Verify the installation script injects crowdsec probe conditionally execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script injects crowdsec probe conditionally integration.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("CROWDSEC_PROBE_MARKER", script_text)
        self.assertIn("crowdsec:8080/health", script_text)
        self.assertIn("Injected CrowdSec health probe into prometheus.yml", script_text)
        self.assertIn("Removed CrowdSec health probe from prometheus.yml", script_text)

    def test_is_crowdsec_enabled_rejects_both_placeholder_values(self) -> None:
        """Confirm is crowdsec enabled rejects both placeholder values is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in is crowdsec enabled rejects both placeholder values.
        """
        script_text = (
            self.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('legacy_placeholder_prefix="CHANGE"', script_text)
        self.assertIn('"${legacy_placeholder_prefix}VALUE2"', script_text)
        self.assertIn('"${legacy_placeholder_prefix}VALUE3"', script_text)

    def test_installation_script_schedules_one_shot_crowdsec_restart_only_when_needed(
        self,
    ) -> None:
        """Verify the installation script schedules one shot crowdsec restart only when needed execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script schedules one shot crowdsec restart only when needed integration.
        """
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
        """Verify the installation script prints crowdsec banner before compose up execution contract.

        Inputs: repository fixtures. Output: fails on regressions in installation script prints crowdsec banner before compose up integration.
        """
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
        """Verify crowdsec restart helper is single shot.

        Inputs: repository fixtures. Output: fails on regressions in crowdsec restart helper is single shot.
        """
        helper_text = (
            self.repo_root / "installation" / "crowdsec_install_auto_restart.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("trap cleanup_marker EXIT HUP INT TERM", helper_text)
        self.assertIn('docker restart "${container_name}"', helper_text)
        self.assertNotIn("while ", helper_text)

    def test_crowdsec_entrypoint_enrolls_only_when_install_bootstrap_is_armed(
        self,
    ) -> None:
        """Verify crowdsec entrypoint enrolls only when install bootstrap is armed.

        Inputs: repository fixtures. Output: fails on regressions in crowdsec entrypoint enrolls only when install bootstrap is armed.
        """
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

    def test_crowdsec_forward_chains_wait_for_bouncer_sets(self) -> None:
        """Verify crowdsec forward chains wait for bouncer sets.

        Inputs: repository fixtures. Output: fails on regressions in crowdsec forward chains wait for bouncer sets.
        """
        entrypoint_text = (
            self.repo_root / "docker" / "crowdsec-entrypoint.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("wait_for_nft_sets()", entrypoint_text)
        self.assertIn("ensure_nft_forward_chain()", entrypoint_text)
        self.assertIn('nft -t list table "${_family}" "${_table}"', entrypoint_text)
        self.assertIn(
            "creates one set per decision origin",
            entrypoint_text,
        )
        self.assertIn("nft flush chain", entrypoint_text)
        self.assertIn(
            "wait_for_nft_sets ip crowdsec crowdsec-blacklists",
            entrypoint_text,
        )
        self.assertIn(
            "wait_for_nft_sets ip6 crowdsec6 crowdsec6-blacklists",
            entrypoint_text,
        )
        self.assertNotIn("for _candidate in crowdsec-blacklists", entrypoint_text)

    def test_docker_compose_defaults_crowdsec_install_bootstrap_enroll_to_disabled(
        self,
    ) -> None:
        """Verify docker compose defaults crowdsec install bootstrap enroll to disabled.

        Inputs: repository fixtures. Output: fails on regressions in docker compose defaults crowdsec install bootstrap enroll to disabled.
        """
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
        """Verify docker compose omeroserver passes OMERO data dir and OMERO dir.

        Inputs: repository fixtures. Output: fails on regressions in docker compose omeroserver passes OMERO data dir and OMERO dir.

        The server must receive OMERO_DATA_DIR and OMERO_DIR so it resolves
        managed repository paths against the bind-mounted data volume, not the
        ephemeral server install directory. Removing these causes imports to land
        inside the container and be lost on restart.
        """
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
        """Verify server bootstrap validates managed repository before startup.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap validates managed repository before startup.
        """
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
        """Verify omeroserver example env uses absolute managed dir.

        Inputs: repository fixtures. Output: fails on regressions in omeroserver example env uses absolute managed dir.

        CONFIG_omero_managed_dir must be absolute so OMERO never resolves it
        against the server install directory. A relative value causes silent data
        loss on restart.
        """
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
        """Confirm server bootstrap rejects managed dir outside OMERO dir is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap rejects managed dir outside OMERO dir.

        The managed-repository guard must check that the configured path lives
        inside OMERO_DIR and must produce a clear error when it does not, so the
        container refuses to start with a misconfigured path.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("normalize_dir_path()", script_text)
        self.assertIn(
            "Refusing startup because unexpected image-local managed repository",
            script_text,
        )

    def test_server_bootstrap_persists_ims_export_dir_for_processor_scripts(
        self,
    ) -> None:
        """Verify server bootstrap persists IMS export dir for processor scripts.

        Inputs: repository fixtures. Output: fails on regressions in IMS export
        path handling for Processor subprocesses.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        env_text = (self.repo_root / "env" / "omeroserver_example.env").read_text(
            encoding="utf-8"
        )
        celery_env_text = (
            self.repo_root / "env" / "omero-celery_example.env"
        ).read_text(encoding="utf-8")
        dockerfile_text = (
            self.repo_root / "docker" / "omero-server.Dockerfile"
        ).read_text(encoding="utf-8")
        processor_patch_text = (
            self.repo_root / "docker" / "patch_omero_processor_env.py"
        ).read_text(encoding="utf-8")

        self.assertIn('OMERO_IMS_EXPORT_CONFIG_KEY="omero.ims.export.dir"', script_text)
        self.assertIn("expected_ims_export_root()", script_text)
        self.assertIn("validate_ims_export_configuration", script_text)
        self.assertIn("configure_ims_export_runtime_paths", script_text)
        self.assertIn("patch_omero_processor_env.py", dockerfile_text)
        self.assertIn("OMERO_IMS_EXPORT_DIR", processor_patch_text)
        self.assertIn("CONFIG_omero_managed_dir", processor_patch_text)
        self.assertIn("environment allowlist", processor_patch_text)
        self.assertIn(
            'wrapper_path="${SERVER_HOME%/}/bin/omero-scripts-python"',
            script_text,
        )
        self.assertIn("export OMERO_IMS_EXPORT_DIR=%q", script_text)
        self.assertIn(
            'run_omero config set omero.scripts.python "${wrapper_path}"',
            script_text,
        )
        self.assertIn(
            'run_omero config set "${OMERO_IMS_EXPORT_CONFIG_KEY}" "${export_root}"',
            script_text,
        )
        self.assertIn("OMERO_IMS_EXPORT_DIR=/OMERO/ImarisExports", env_text)
        self.assertNotIn("OMERO_IMS_EXPORT_DIR=", celery_env_text)

    # ------------------------------------------------------------------
    # Coverage pipeline completeness
    # ------------------------------------------------------------------

    def test_coveragerc_tracks_all_python_source_directories(self) -> None:
        """Verify coveragerc tracks all python source directories.

        Inputs: repository fixtures. Output: fails on regressions in coveragerc tracks all python source directories.

        Every plugin/library directory that contains Python source must appear in
        .coveragerc [run] source so coverage.py traces it.
        """
        expected_dirs = [
            "./omero_plugin_common",
            "./omeroweb_omp_plugin",
            "./omeroweb_import",
            "./omeroweb_admin_tools",
            "./omero_imaris_connector",
            "./omeroweb_tools",
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
        """Verify the ci workflow runs all test suites execution contract.

        Inputs: repository fixtures. Output: fails on regressions in ci workflow runs all test suites integration.

        The CI workflow must run every test suite as a separate coverage
        invocation so the conftest mock stubs do not interfere.
        """
        expected_suites = [
            "tests/",
            "omero_plugin_common/tests/",
            "omero_imaris_connector/tests/",
            "omeroweb_admin_tools/tests/",
            "omeroweb_omp_plugin/tests/",
            "omeroweb_import/tests/",
            "omeroweb_tools/tests/",
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
        """Verify the all workflow checkout steps use verified v6 pin execution contract.

        Inputs: repository fixtures. Output: fails on regressions in all workflow checkout steps use verified v6 pin integration.
        """
        expected_checkout = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
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
        """Verify the security code scanning workflow includes zero delta alert gate execution contract.

        Inputs: repository fixtures. Output: fails on regressions when security code scanning workflow includes zero delta alert gate accepts unsafe input.
        """
        import yaml  # noqa: F811  — available in CI

        workflow_path = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        security_delta_job = workflow["jobs"]["security-delta"]

        self.assertEqual("security", workflow["name"])
        self.assertEqual(
            f"always() && {self.DEFAULT_BRANCH_JOB_GUARD}",
            security_delta_job["if"],
        )
        self.assertEqual("read", security_delta_job["permissions"]["actions"])
        self.assertEqual("read", security_delta_job["permissions"]["contents"])
        self.assertEqual("read", security_delta_job["permissions"]["security-events"])
        self.assertNotIn("pull-requests", security_delta_job["permissions"])
        self.assertEqual("ubuntu-latest", security_delta_job["runs-on"])
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
        """Verify the standalone security delta workflow is not present execution contract.

        Inputs: repository fixtures. Output: fails on regressions when standalone security delta workflow is not present accepts unsafe input.
        """
        self.assertFalse(
            (self.repo_root / ".github" / "workflows" / "security-delta.yml").exists()
        )

    def test_codecov_yml_has_component_for_each_source_directory(self) -> None:
        """Verify codecov yml has component for each source directory.

        Inputs: repository fixtures. Output: fails on regressions in codecov yml has component for each source directory.

        Each plugin/library tracked in .coveragerc must have a matching Codecov
        project component so per-module coverage is reported.
        """
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
            "omero_imaris_connector",
            "omeroweb_tools",
            "omero_web_zarr",
        }
        for prefix in expected_prefixes:
            self.assertIn(
                prefix,
                covered_prefixes,
                f"Codecov component for {prefix!r} is missing",
            )

    def test_codecov_denominator_scope_is_documented(self) -> None:
        """Verify codecov denominator scope is documented.

        Inputs: repository fixtures. Output: fails on regressions in codecov denominator scope is documented.
        """
        operations_text = (
            self.repo_root / "docs" / "operations" / "code-scanning.md"
        ).read_text(encoding="utf-8")
        for package_root in (
            "omero_plugin_common/",
            "omero_web_zarr/",
            "omeroweb_admin_tools/",
            "omero_imaris_connector/",
            "omeroweb_import/",
            "omeroweb_omp_plugin/",
            "omeroweb_tools/",
        ):
            self.assertIn(package_root, operations_text)
        for excluded_root in (
            "tools/",
            "startup/",
            "monitoring/",
            "docker/",
            "docs/",
            "scripts/",
            "env/",
        ):
            self.assertIn(excluded_root, operations_text)
        self.assertIn(
            "smaller than the repository's full Python footprint", operations_text
        )

    def test_ci_workflows_install_from_pinned_requirement_manifests(self) -> None:
        """Verify ci workflows install from pinned requirement manifests.

        Inputs: repository fixtures. Output: fails on regressions in ci workflows install from pinned requirement manifests.
        """
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

    def test_python_backed_ci_workflows_pin_exact_setup_python_runtime(self) -> None:
        """Verify python backed ci workflows pin exact setup python runtime.

        Inputs: repository fixtures. Output: fails on regressions in python backed ci workflows pin exact setup python runtime.
        """
        import yaml  # noqa: F811  — available in CI

        expected_versions = {
            ".github/workflows/docs-knowledge-base.yml": ["3.14.4"],
            ".github/workflows/mypy.yml": ["3.14.4"],
            ".github/workflows/tests.yml": ["3.14.4"],
            ".github/workflows/vulture.yml": ["3.14.4"],
            ".github/workflows/security-code-scanning.yml": ["3.14.4", "3.14.4"],
        }

        for relative_path, expected in expected_versions.items():
            workflow = yaml.safe_load(
                (self.repo_root / relative_path).read_text(encoding="utf-8")
            )
            actual = [
                step["with"]["python-version"]
                for job in workflow["jobs"].values()
                for step in job.get("steps", [])
                if step.get("uses")
                == "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
            ]
            with self.subTest(relative_path=relative_path):
                self.assertEqual(expected, actual)

    def test_python_dependency_jobs_enable_setup_python_pip_cache(self) -> None:
        """Verify python dependency jobs enable setup python pip cache.

        Inputs: repository fixtures. Output: fails on regressions in python dependency jobs enable setup python pip cache.
        """
        import yaml  # noqa: F811  — available in CI

        expected_cache_paths = {
            ".github/workflows/tests.yml": (
                "test-with-coverage",
                [".github/requirements/tests-ci.txt"],
            ),
            ".github/workflows/mypy.yml": (
                "mypy",
                [
                    ".github/requirements/tests-ci.txt",
                    ".github/requirements/mypy-ci.txt",
                ],
            ),
            ".github/workflows/vulture.yml": (
                "vulture",
                [".github/requirements/vulture-ci.txt"],
            ),
            ".github/workflows/security-code-scanning.yml": (
                "bandit",
                [".github/requirements/security-code-scanning.txt"],
            ),
        }

        for relative_path, (job_name, dependency_paths) in expected_cache_paths.items():
            workflow = yaml.safe_load(
                (self.repo_root / relative_path).read_text(encoding="utf-8")
            )
            setup_step = next_or_fail(
                step
                for step in workflow["jobs"][job_name]["steps"]
                if step.get("name") == "Setup Python"
            )
            with self.subTest(relative_path=relative_path):
                self.assertEqual("pip", setup_step["with"]["cache"])
                self.assertEqual(
                    dependency_paths,
                    setup_step["with"]["cache-dependency-path"].splitlines(),
                )

    def test_security_codeql_uses_build_free_interpreted_language_mode(self) -> None:
        """Verify the security codeql uses build free interpreted language mode safety boundary.

        Inputs: repository fixtures. Output: fails on regressions when security codeql uses build free interpreted language mode accepts unsafe input.
        """
        import yaml  # noqa: F811  — available in CI

        workflow_path = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["codeql"]["steps"]

        init_step = next_or_fail(
            step for step in steps if step.get("name") == "Initialize CodeQL"
        )
        self.assertEqual("none", init_step["with"]["build-mode"])
        self.assertEqual("true", str(init_step["with"]["dependency-caching"]).lower())
        self.assertEqual(
            "./.github/codeql/codeql-config.yml", init_step["with"]["config-file"]
        )
        codeql_config = yaml.safe_load(
            (self.repo_root / ".github" / "codeql" / "codeql-config.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            ["third_party/**"],
            codeql_config["paths-ignore"],
        )
        self.assertFalse(
            any(
                str(step.get("uses", "")).startswith("github/codeql-action/autobuild@")
                for step in steps
            )
        )

        audit_step = next_or_fail(
            step
            for step in steps
            if step.get("name") == "Audit — explain CodeQL language candidates"
        )
        self.assertEqual("bash", audit_step["shell"])
        self.assertIn("RUNNER_TEMP", audit_step["run"])
        self.assertIn("git ls-files '*.py'", audit_step["run"])
        self.assertIn("':!:third_party/**'", audit_step["run"])
        self.assertIn("git ls-files '*.pyi'", audit_step["run"])
        self.assertIn("git ls-files '*.js' '*.jsx' '*.mjs'", audit_step["run"])
        self.assertIn("grep -v '^\\.agents/'", audit_step["run"])
        self.assertIn("grep '^\\.agents/'", audit_step["run"])

    def test_super_linter_workflow_is_pinned_and_covers_repo_hygiene_surfaces(
        self,
    ) -> None:
        """Verify the super linter workflow is pinned and covers repo hygiene surfaces execution contract.

        Inputs: repository fixtures. Output: fails on regressions in super linter workflow is pinned and covers repo hygiene surfaces integration.
        """
        import yaml  # noqa: F811  — available in CI

        workflow_path = self.repo_root / ".github" / "workflows" / "super-linter.yml"
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        triggers = workflow[True]

        self.assertEqual("super-linter", workflow["name"])
        self.assertNotIn("pull_request", triggers)
        self.assertIn("push", triggers)
        self.assertIsNone(triggers["push"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(
            self.DEFAULT_BRANCH_JOB_GUARD,
            workflow["jobs"]["super-linter"]["if"],
        )
        self.assertEqual("read", workflow["permissions"]["contents"])
        self.assertEqual("ubuntu-latest", workflow["jobs"]["super-linter"]["runs-on"])

        job_permissions = workflow["jobs"]["super-linter"]["permissions"]
        self.assertEqual("read", job_permissions["contents"])
        self.assertEqual("read", job_permissions["packages"])
        self.assertNotIn("statuses", job_permissions)

        steps = workflow["jobs"]["super-linter"]["steps"]
        checkout_step = next_or_fail(
            step for step in steps if step.get("name") == "Checkout"
        )
        self.assertEqual(
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
            checkout_step["uses"],
        )
        self.assertEqual(0, checkout_step["with"]["fetch-depth"])
        self.assertFalse(checkout_step["with"]["persist-credentials"])

        lint_step = next_or_fail(
            step for step in steps if step.get("name") == "Super-Linter"
        )
        self.assertNotIn("uses", lint_step)
        self.assertRegex(
            lint_step["run"],
            r"ghcr\.io/super-linter/super-linter:v8\.7\.0@sha256:[0-9a-f]{64}\b",
        )
        self.assertNotIn("GITHUB_TOKEN", lint_step["env"])
        self.assertNotIn("MULTI_STATUS", lint_step["env"])
        self.assertNotIn("SAVE_SUPER_LINTER_SUMMARY", lint_step["env"])
        self.assertEqual(
            "${{ github.event.repository.default_branch }}",
            lint_step["env"]["DEFAULT_BRANCH"],
        )
        self.assertEqual(
            "(^|/)third_party/(ecc-v2\\.0\\.0|caveman-v1\\.9\\.1)/",
            lint_step["env"]["FILTER_REGEX_EXCLUDE"],
        )
        self.assertEqual(".", lint_step["env"]["LINTER_RULES_PATH"])
        self.assertEqual(".markdownlint.yaml", lint_step["env"]["MARKDOWN_CONFIG_FILE"])
        self.assertEqual("true", lint_step["env"]["RUN_LOCAL"])
        self.assertEqual("true", lint_step["env"]["VALIDATE_BASH"])
        self.assertEqual(".yamllint", lint_step["env"]["YAML_CONFIG_FILE"])
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
            "third_party/ecc-v2.0.0/**\nthird_party/caveman-v1.9.1/**\n",
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
        """Check that tests workflow uploads codecov via oidc without environment or secret keeps sensitive data out of output.

        Inputs: repository fixtures. Output: fails on regressions in tests workflow uploads codecov via oidc without environment or secret integration.
        """
        import yaml  # noqa: F811  — available in CI

        workflow_path = self.repo_root / ".github" / "workflows" / "tests.yml"
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        job = workflow["jobs"]["test-with-coverage"]

        self.assertNotIn("environment", job)
        self.assertEqual(
            {"contents": "read", "id-token": "write"},
            job["permissions"],
        )

        upload_step = next_or_fail(
            step
            for step in job["steps"]
            if step.get("name") == "Upload coverage to Codecov"
        )

        self.assertEqual(
            "codecov/codecov-action@fb8b3582c8e4def4969c97caa2f19720cb33a72f",
            upload_step["uses"],
        )
        self.assertEqual(
            "always() && github.event_name == 'push' && github.ref_name == github.event.repository.default_branch",
            upload_step["if"],
        )
        self.assertEqual("true", str(upload_step["with"]["use_oidc"]).lower())
        self.assertEqual("v11.3.1", upload_step["with"]["version"])
        self.assertNotIn("token", upload_step["with"])
        self.assertFalse(
            any(step.get("name") == "Validate Codecov token" for step in job["steps"])
        )

    def test_security_workflow_avoids_unpinned_container_and_template_injection(
        self,
    ) -> None:
        """Check security workflow avoids unpinned container and template injection renders the expected surface.

        Inputs: repository fixtures. Output: fails on regressions when security workflow avoids unpinned container and template injection accepts unsafe input.
        """
        import yaml  # noqa: F811  — available in CI

        workflow_path = (
            self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
        )
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

        self.assertEqual({"contents": "read"}, workflow["permissions"])
        self.assertEqual(
            "semgrep/semgrep:1.170.0@sha256:c98f8829eea377274ee4b10656458b078b88232469b2ff913f091c2317347c9d",
            workflow["jobs"]["semgrep"]["container"]["image"],
        )
        trivy_step = next_or_fail(
            step
            for step in workflow["jobs"]["trivy-filesystem"]["steps"]
            if step.get("name") == "Run Trivy vulnerability scan"
        )
        self.assertEqual(
            "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25",
            trivy_step["uses"],
        )

        bandit_scope_step = next_or_fail(
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

        bandit_prod_step = next_or_fail(
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

        bandit_test_step = next_or_fail(
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

        hadolint_audit_step = next_or_fail(
            step
            for step in workflow["jobs"]["hadolint"]["steps"]
            if step.get("name") == "Audit — show file being scanned"
        )
        self.assertEqual(1, workflow["jobs"]["hadolint"]["strategy"]["max-parallel"])
        self.assertEqual(
            "${{ matrix.dockerfile }}", hadolint_audit_step["env"]["DOCKERFILE_PATH"]
        )
        self.assertIn(
            "printf 'Scanning Dockerfile: %s\\n' \"${DOCKERFILE_PATH}\"",
            hadolint_audit_step["run"],
        )
        self.assertIn('wc -l -- "${DOCKERFILE_PATH}"', hadolint_audit_step["run"])

    def test_workflow_scanner_scope_exclusions_are_limited_and_audited(
        self,
    ) -> None:
        """Verify the workflow scanner scope exclusions are limited and audited execution contract.

        Inputs: repository fixtures. Output: fails on regressions in workflow scanner scope exclusions are limited and audited integration.
        """
        import yaml  # noqa: F811 - available in CI

        workflow_paths = sorted(
            (self.repo_root / ".github" / "workflows").glob("*.yml")
        )
        for workflow_path in workflow_paths:
            if workflow_path.name == "release-prebuilt-carrier.yml":
                continue
            workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
            triggers = workflow.get(True, {})
            with self.subTest(workflow=workflow_path.name):
                self.assertNotIn("pull_request", triggers)
                self.assertIn("push", triggers)
                event_config = triggers.get("push")
                if isinstance(event_config, dict):
                    self.assertNotIn("branches", event_config)
                    self.assertNotIn("branches-ignore", event_config)
                    self.assertNotIn("paths", event_config)
                    self.assertNotIn("paths-ignore", event_config)

        security_workflow = yaml.safe_load(
            (
                self.repo_root / ".github" / "workflows" / "security-code-scanning.yml"
            ).read_text(encoding="utf-8")
        )
        security_jobs = security_workflow["jobs"]

        semgrep_run = next_or_fail(
            step
            for step in security_jobs["semgrep"]["steps"]
            if step.get("name") == "Run Semgrep scan"
        )["run"]
        self.assertEqual(
            "semgrep scan --sarif --config auto --exclude third_party . > semgrep-results.sarif",
            semgrep_run,
        )

        trivy_with = next_or_fail(
            step
            for step in security_jobs["trivy-filesystem"]["steps"]
            if step.get("name") == "Run Trivy vulnerability scan"
        )["with"]
        self.assertEqual("fs", trivy_with["scan-type"])
        self.assertEqual("vuln,misconfig,secret,license", trivy_with["scanners"])
        self.assertEqual("third_party", trivy_with["skip-dirs"])
        self.assertNotIn("skip-files", trivy_with)
        self.assertNotIn("trivyignores", trivy_with)

        bandit_prod = next_or_fail(
            step
            for step in security_jobs["bandit"]["steps"]
            if step.get("name")
            == "Run Bandit scan (production code — excludes test directories)"
        )["run"]
        self.assertIn('--skip "B603,B404"', bandit_prod)
        self.assertNotIn("B101", bandit_prod)
        self.assertNotIn("B106", bandit_prod)

        bandit_test = next_or_fail(
            step
            for step in security_jobs["bandit"]["steps"]
            if step.get("name")
            == "Run Bandit scan (test code — skips assert and test-credential rules)"
        )["run"]
        self.assertIn('--skip "B101,B106,B603,B404"', bandit_test)

        devskim_with = next_or_fail(
            step
            for step in security_jobs["devskim"]["steps"]
            if step.get("name") == "Run DevSkim scan"
        )["with"]
        self.assertEqual(
            "**/.git/**,**/pgdata/**,**/omero_data/**,**/omero_temp/**,**/third_party/**",
            devskim_with["ignore-globs"],
        )
        self.assertEqual("DS162092", devskim_with["exclude-rules"])

        docs_text = (
            self.repo_root / "docs" / "operations" / "code-scanning.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Do not narrow scanner scope to improve scores.", docs_text)
        self.assertIn(
            "CodeQL/Semgrep/Trivy/DevSkim exclusion of vendored `third_party`",
            docs_text,
        )
        self.assertIn("DevSkim `DS162092`", docs_text)

    def test_security_sarif_upload_jobs_can_read_workflow_run_metadata(self) -> None:
        """Verify the security sarif upload jobs can read workflow run metadata execution contract.

        Inputs: repository fixtures. Output: fails on regressions when security sarif upload jobs can read workflow run metadata accepts unsafe input.
        """
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
        """Verify the all workflow checkouts disable persisted credentials execution contract.

        Inputs: repository fixtures. Output: fails on regressions in all workflow checkouts disable persisted credentials integration.
        """
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

    def test_all_workflow_jobs_gate_runner_execution_to_default_branch(self) -> None:
        """Verify the all workflow jobs gate runner execution to default branch execution contract.

        Inputs: repository fixtures. Output: fails on regressions in all workflow jobs gate runner execution to default branch integration.
        """
        import yaml  # noqa: F811  — available in CI

        workflows_dir = self.repo_root / ".github" / "workflows"
        for workflow_path in sorted(workflows_dir.glob("*.yml")):
            workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
            for job_name, job in workflow.get("jobs", {}).items():
                with self.subTest(workflow=workflow_path.name, job=job_name):
                    self.assertIn(
                        "if",
                        job,
                        f"{workflow_path.name}:{job_name} must gate runner execution to the default branch",
                    )
                    self.assertIn(
                        self.DEFAULT_BRANCH_JOB_GUARD,
                        str(job["if"]),
                        f"{workflow_path.name}:{job_name} is missing the default-branch runner guard",
                    )

    def test_dependabot_updates_define_cooldown_windows(self) -> None:
        """Verify dependabot updates define cooldown windows.

        Inputs: repository fixtures. Output: fails on regressions in dependabot updates define cooldown windows.
        """
        import yaml  # noqa: F811  — available in CI

        dependabot_path = self.repo_root / ".github" / "dependabot.yml"
        config = yaml.safe_load(dependabot_path.read_text(encoding="utf-8"))

        for update in config["updates"]:
            self.assertIn("cooldown", update)
            self.assertGreaterEqual(update["cooldown"]["default-days"], 7)

    def test_dependabot_covers_compose_and_dockerfiles(self) -> None:
        """Verify Docker dependency updates cover both manifest locations.

        Inputs: Dependabot YAML. Output: asserts root and Dockerfile coverage.
        """
        import yaml  # noqa: F811 -- available in CI

        dependabot_path = self.repo_root / ".github" / "dependabot.yml"
        config = yaml.safe_load(dependabot_path.read_text(encoding="utf-8"))
        docker_directories = {
            update["directory"]
            for update in config["updates"]
            if update["package-ecosystem"] == "docker"
        }

        self.assertEqual({"/", "/docker"}, docker_directories)

        dockerfile_update = next_or_fail(
            update
            for update in config["updates"]
            if update["package-ecosystem"] == "docker"
            and update["directory"] == "/docker"
        )
        postgres_ignore = next_or_fail(
            rule
            for rule in dockerfile_update["ignore"]
            if rule["dependency-name"] == "postgres"
        )
        self.assertEqual(
            ["version-update:semver-major"], postgres_ignore["update-types"]
        )

    def test_ci_requirement_manifests_pin_every_dependency(self) -> None:
        """Verify ci requirement manifests pin every dependency.

        Inputs: repository fixtures. Output: fails on regressions in ci requirement manifests pin every dependency.
        """
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
        """Verify ci requirement source manifests exist.

        Inputs: repository fixtures. Output: fails on regressions in ci requirement source manifests exist.
        """
        source_paths = [
            self.repo_root / ".github" / "requirements" / "tests-ci.in",
            self.repo_root / ".github" / "requirements" / "security-code-scanning.in",
        ]
        for source_path in source_paths:
            self.assertTrue(source_path.exists(), f"{source_path.name} is missing")

    def test_shell_helpers_avoid_global_ifs_mutation(self) -> None:
        """Verify shell helpers avoid global ifs mutation.

        Inputs: repository fixtures. Output: fails on regressions in shell helpers avoid global ifs mutation.
        """
        extra_packages_script = (
            self.repo_root
            / "helper_scripts_debian"
            / "extra_packages_debian_13_install_script"
        ).read_text(encoding="utf-8")
        docker_analysis_script = (
            self.repo_root / "helper_scripts_debian" / "docker_image_analysis.sh"
        ).read_text(encoding="utf-8")
        public_pull_script = (
            self.repo_root / "installation" / "github_pull_project_bash"
        ).read_text(encoding="utf-8")

        self.assertNotIn("IFS=$'\\n\\t'", extra_packages_script)
        self.assertNotIn("IFS=$'\\n\\t'", docker_analysis_script)
        self.assertNotIn("IFS='/'", public_pull_script)
        self.assertIn(
            'while [ -n "${_remaining_rel}" ]; do',
            public_pull_script,
        )

    def test_docker_image_analysis_probe_uses_hardened_container_runtime(self) -> None:
        """Verify Docker image analysis probes use hardened Docker runtime flags.

        Inputs: repository fixtures. Output: fails on regressions in helper probe isolation.
        """
        script_text = (
            self.repo_root / "helper_scripts_debian" / "docker_image_analysis.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("--network none", script_text)
        self.assertIn("--cap-drop ALL", script_text)
        self.assertIn("--security-opt no-new-privileges", script_text)
        self.assertIn("--read-only", script_text)
        self.assertIn('--tmpfs "/tmp:rw,noexec,nosuid,nodev,size=16m"', script_text)
        self.assertIn("--pids-limit 128", script_text)
        self.assertIn("--memory 256m", script_text)

    def test_server_bootstrap_avoids_bash_operator_portability_findings(self) -> None:
        """Verify server bootstrap avoids bash operator portability findings.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap avoids bash operator portability findings.
        """
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(script_text, r"\[\[[^\n\]]*=~")
        self.assertNotRegex(script_text, r"\[\[[^\n\]]*==")
        self.assertIn("is_positive_integer()", script_text)
        self.assertIn("is_env_var_name()", script_text)


if __name__ == "__main__":
    unittest.main()
