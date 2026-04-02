"""Regression tests for the generated README badge block."""

from __future__ import annotations

from unittest import TestCase, main, mock
from pathlib import Path

from tools import update_readme_badges


class ReadmeBadgeGenerationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_readme_badges_match_generated_block(self) -> None:
        readme_text = (self.repo_root / "README.md").read_text(encoding="utf-8")
        metadata = update_readme_badges.resolve_repo_metadata(self.repo_root)
        expected_block = update_readme_badges.render_badge_block(metadata)
        self.assertEqual(
            expected_block,
            update_readme_badges.extract_badge_block(readme_text),
        )

    def test_generated_badges_follow_expected_order(self) -> None:
        metadata = update_readme_badges.resolve_repo_metadata(self.repo_root)
        badge_block = update_readme_badges.render_badge_block(metadata)
        self.assertLess(
            badge_block.index("[![License]("),
            badge_block.index("[![tests]("),
        )
        self.assertLess(
            badge_block.index("[![tests]("),
            badge_block.index("[![security]("),
        )
        self.assertLess(
            badge_block.index("[![Codecov]("),
            badge_block.index("[![Ruff]("),
        )
        self.assertLess(
            badge_block.index("[![Ruff]("),
            badge_block.index("[![GitHub commit activity]("),
        )

    def test_generated_commit_activity_badge_uses_repo_slug_and_default_branch(
        self,
    ) -> None:
        metadata = update_readme_badges.RepoMetadata(
            host="github.com",
            owner="example-owner",
            repo="example-repo",
            remote_name="origin",
            branch_name="main",
        )
        badge_block = update_readme_badges.render_badge_block(metadata)
        self.assertIn(
            "https://img.shields.io/github/commit-activity/m/example-owner/example-repo",
            badge_block,
        )
        self.assertIn(
            "https://github.com/example-owner/example-repo/commits/main",
            badge_block,
        )
        self.assertIn(
            "https://github.com/example-owner/example-repo/actions/workflows/security-code-scanning.yml",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/github/actions/workflow/status/example-owner/example-repo/tests.yml?branch=main&label=tests",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/github/actions/workflow/status/example-owner/example-repo/security-code-scanning.yml?branch=main&label=security",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/codecov/c/github/example-owner/example-repo?label=Codecov&logo=codecov",
            badge_block,
        )
        self.assertNotIn(
            "https://github.com/example-owner/example-repo/actions/workflows/tests.yml/badge.svg",
            badge_block,
        )
        self.assertNotIn(
            "https://codecov.io/gh/example-owner/example-repo/graph/badge.svg",
            badge_block,
        )
        self.assertNotIn(
            "https://github.com/example-owner/example-repo/actions/workflows/security-code-scanning.yml/badge.svg",
            badge_block,
        )

    def test_remote_url_parsing_supports_public_and_private_clone_styles(self) -> None:
        cases = {
            "git@github.com:ZMB-UZH/omero-docker-extended.git": (
                "github.com",
                "ZMB-UZH",
                "omero-docker-extended",
            ),
            "https://example-token@github.com/strmt7/omero-docker-extended.git": (
                "github.com",
                "strmt7",
                "omero-docker-extended",
            ),
        }

        for remote_url, expected in cases.items():
            with self.subTest(remote_url=remote_url):
                self.assertEqual(
                    expected, update_readme_badges._parse_remote_url(remote_url)
                )

    def test_run_git_marks_repo_root_as_safe_directory(self) -> None:
        with mock.patch(
            "tools.update_readme_badges.subprocess.run",
            return_value=mock.Mock(stdout="main\n"),
        ) as mocked_run:
            self.assertEqual(
                update_readme_badges._run_git(self.repo_root, "rev-parse", "HEAD"),
                "main",
            )

        mocked_run.assert_called_once_with(
            [
                "git",
                "-c",
                f"safe.directory={self.repo_root.resolve()}",
                "rev-parse",
                "HEAD",
            ],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    main()
