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
        self.assertIn('USE_BUILDX_COMPRESSED_BUILD="${USE_BUILDX_COMPRESSED_BUILD}"', script_text)
        self.assertIn('DOCKER_REGISTRY_PREFIX="${DOCKER_REGISTRY_PREFIX}"', script_text)
        self.assertIn('DOCKER_IMAGE_TAG="${DOCKER_IMAGE_TAG}"', script_text)


if __name__ == "__main__":
    unittest.main()
