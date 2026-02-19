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

    def test_github_pull_script_exports_compressed_build_env(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn("exec env", script_text)
        self.assertIn('USE_BUILDX_COMPRESSED_BUILD="${USE_BUILDX_COMPRESSED_BUILD:-1}"', script_text)
        self.assertIn('INSTALLATION_AUTOMATION_MODE="${INSTALLATION_AUTOMATION_MODE}"', script_text)

    def test_public_pull_script_defaults_to_public_repo(self) -> None:
        script_text = (self.repo_root / "github_pull_project_bash_example").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'REPO_URL="${REPO_URL:-https://github.com/ZMB-UZH/omero-docker-extended.git}"',
            script_text,
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
