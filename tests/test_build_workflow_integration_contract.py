"""Contract tests for compressed build workflow integration points."""

from __future__ import annotations

import unittest
from pathlib import Path


class BuildWorkflowIntegrationContractTests(unittest.TestCase):
    """Verify compressed build workflow is wired into update/install scripts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_installation_script_references_compressed_helper(self) -> None:
        script_text = (self.repo_root / "installation" / "installation_script.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("USE_BUILDX_COMPRESSED_BUILD", script_text)
        self.assertIn("run_image_build()", script_text)
        self.assertIn("docker_buildx_compressed_push.sh", script_text)
        self.assertIn('DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE:-0}"', script_text)
        self.assertIn("resolve_flatten_final_image_choice()", script_text)
        self.assertIn('local prompt_hint="Y/n"', script_text)
        self.assertIn('Flatten final images into single-layer outputs? (slower; rebuilds each image)', script_text)
        self.assertIn('DOCKER_BUILD_FLATTEN_ONLY="1"', script_text)
        self.assertIn('resolve_build_provenance_setting()', script_text)
        self.assertIn('--provenance "${provenance_setting}"', script_text)
        self.assertNotIn("DOCKER_BUILD_SQUASH", script_text)

    def test_installation_script_checks_build_and_flatten_helper_failures_explicitly(self) -> None:
        script_text = (self.repo_root / "installation" / "installation_script.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'if ! compose_with_installation_env "${COMPOSE_FILE}" "${compose_build_args[@]}"; then',
            script_text,
        )
        self.assertIn("ERROR: docker compose build workflow failed.", script_text)
        self.assertIn("ERROR: Compose image flatten workflow failed.", script_text)
        self.assertIn("ERROR: Buildx compressed build workflow failed.", script_text)

    def test_installation_script_does_not_inject_top_logo_defaults(self) -> None:
        script_text = (self.repo_root / "installation" / "installation_script.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("ensure_omeroweb_logo_defaults()", script_text)
        self.assertNotIn('CONFIG_omero_web_top__logo=', script_text)
        self.assertNotIn('CONFIG_omero_web_top__logo__link=/webclient/', script_text)

    def test_omeroweb_example_env_defines_only_login_logo_default(self) -> None:
        env_text = (self.repo_root / "env" / "omeroweb_example.env").read_text(
            encoding="utf-8"
        )
        self.assertIn("CONFIG_omero_web_login__logo=/static/branding/logo.png", env_text)
        self.assertNotIn("CONFIG_omero_web_top__logo=", env_text)
        self.assertNotIn("CONFIG_omero_web_top__logo__link=", env_text)

    def test_omeroweb_dockerfile_applies_logo_context_patch(self) -> None:
        dockerfile_text = (self.repo_root / "docker" / "omero-web.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("patch_omeroweb_logo_context.py", dockerfile_text)


    def test_installation_group_bootstrap_uses_dynamic_omero_cli_discovery(self) -> None:
        script_text = (self.repo_root / "installation" / "installation_script.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('resolve_omero_bin() { local candidate=""; for candidate in /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do [ -x "${candidate}" ] || continue; printf "%s" "${candidate}"; return 0; done; return 1; }', script_text)


    def test_server_bootstrap_job_service_uses_cli_autodetection_and_hosted_login(self) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('SERVER_HOME="${SERVER_HOME:-/opt/omero/server/OMERO.server}"', script_text)
        self.assertIn('resolve_omero_bin() {', script_text)
        self.assertIn('server_root="${SERVER_HOME%/*}"', script_text)
        self.assertIn('for candidate in "${server_root}"/venv*/bin/omero "${SERVER_HOME}"/bin/omero; do', script_text)
        self.assertIn('for candidate in /opt/omero/server/venv*/bin/omero /opt/omero/server/OMERO.server/bin/omero; do', script_text)
        self.assertIn('run_omero -C -s "${host}" -p "${port}" login -u root -w "${root_pass}"', script_text)

    def test_server_bootstrap_normalizes_managed_repo_shared_prefixes_for_runtime_groups(self) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("list_repo_root_bootstrap_groups()", script_text)
        self.assertIn('mapfile -t repo_root_groups < <(list_repo_root_bootstrap_groups "${root_pass}")', script_text)
        self.assertIn('path_list="$(collect_repo_root_bootstrap_paths "${repo_root_groups[@]}")"', script_text)
        self.assertIn('path_list="$(collect_repo_root_bootstrap_paths)"', script_text)
        self.assertIn('run_omero fs mkdir --parents "${repo_dir_path}"', script_text)
        self.assertIn('run_omero chown root "OriginalFile:${root_dir_id}" --force', script_text)
        self.assertIn("schedule_repo_root_bootstrap", script_text)

    def test_server_bootstrap_python_helpers_use_dynamic_server_paths_and_cli_home(self) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('venv_py="$(resolve_server_venv_python)"', script_text)
        self.assertIn('resolve_cli_home()', script_text)
        self.assertIn('runuser -u "${OMERO_CLI_USER}" -- env HOME="${cli_home}" TMPDIR="${TMPDIR:-/tmp}"', script_text)

    def test_server_bootstrap_uses_dedicated_runtime_tmp_slot(self) -> None:
        script_text = (self.repo_root / "startup" / "10-server-bootstrap.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"${expected_tmp_dir}/runtime"', script_text)
        self.assertIn('export TMPDIR="${runtime_tmp_dir}"', script_text)
        self.assertIn('ln -sf "${runtime_tmp_dir}" "${legacy_tmp_dir}"', script_text)
        self.assertIn('local legacy_omero_py_user_dir="${expected_tmp_dir}/omero_${requested_owner}"', script_text)
        self.assertIn('rm -rf "${omero_py_dir}" "${omero_py_user_dir}" "${legacy_omero_py_user_dir}"', script_text)

    def test_installation_script_preserves_server_temp_namespace_ownership(self) -> None:
        script_text = (self.repo_root / "installation" / "installation_script.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("ensure_omero_tmp_layout()", script_text)
        self.assertIn('if ! ensure_omero_tmp_layout "${OMERO_TMP_PATH}"', script_text)
        self.assertIn('if [ "${top_level_entry}" = "${server_namespace_dir}" ]; then', script_text)
        self.assertIn('chown -R "${server_uid}:${server_gid}" "${server_namespace_dir}"', script_text)
        self.assertNotIn('chown_tree_or_die "${OMERO_TMP_PATH}"', script_text)

    def test_github_pull_script_exports_compressed_build_env(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn("exec env", script_text)
        self.assertIn('USE_BUILDX_COMPRESSED_BUILD="${USE_BUILDX_COMPRESSED_BUILD:-1}"', script_text)
        self.assertIn('DOCKER_BUILD_FLATTEN_FINAL_IMAGE="${DOCKER_BUILD_FLATTEN_FINAL_IMAGE:-0}"', script_text)
        self.assertIn('INSTALLATION_AUTOMATION_MODE="${INSTALLATION_AUTOMATION_MODE}"', script_text)

    def test_public_pull_script_defaults_to_public_repo(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'REPO_URL="${REPO_URL:-https://github.com/ZMB-UZH/omero-docker-extended.git}"',
            script_text,
        )
        self.assertIn('REPO_BRANCH="${REPO_BRANCH:-main}"', script_text)

    def test_private_pull_script_branch_default_is_independent(self) -> None:
        script_text = (self.repo_root / "github_pull_private_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn('REPO_BRANCH="${REPO_BRANCH:-alpha}"', script_text)

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


if __name__ == "__main__":
    unittest.main()
