"""Regression tests for the generated README badge block."""

from __future__ import annotations

import json
from unittest import TestCase, main, mock
from pathlib import Path

from tools import agent_skill_provenance
from tools import update_readme_badges


class ReadmeBadgeGenerationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.metadata_path = cls.repo_root / ".github" / "readme_badges.json"
        cls.upstream_sources = agent_skill_provenance.load_upstream_sources(
            cls.repo_root
        )

    def test_readme_badges_match_generated_block(self) -> None:
        readme_text = (self.repo_root / "README.md").read_text(encoding="utf-8")
        metadata = update_readme_badges.resolve_repo_metadata(self.repo_root)
        expected_block = update_readme_badges.render_badge_block(
            metadata, self.upstream_sources
        )
        self.assertEqual(
            expected_block,
            update_readme_badges.extract_badge_block(readme_text),
        )

    def test_generated_badges_follow_expected_order(self) -> None:
        metadata = update_readme_badges.resolve_repo_metadata(self.repo_root)
        badge_block = update_readme_badges.render_badge_block(
            metadata, self.upstream_sources
        )
        self.assertLess(
            badge_block.index("[![License]("),
            badge_block.index("[![tests]("),
        )
        self.assertLess(
            badge_block.index("[![tests]("),
            badge_block.index("[![security-code-scanning]("),
        )
        self.assertLess(
            badge_block.index("[![GitHub commit activity]("),
            badge_block.index("[![DeepSource]("),
        )
        self.assertLess(
            badge_block.index("[![DeepSource]("),
            badge_block.index("[![Codecov]("),
        )
        self.assertLess(
            badge_block.index("[![Codecov]("),
            badge_block.index("[![Mypy]("),
        )
        self.assertLess(
            badge_block.index("[![Mypy]("),
            badge_block.index("[![super-linter]("),
        )
        self.assertLess(
            badge_block.index("[![super-linter]("),
            badge_block.index("[![Ruff]("),
        )
        self.assertLess(
            badge_block.index("[![Ruff]("),
            badge_block.index("[![Vulture]("),
        )
        self.assertLess(
            badge_block.index("[![Vulture]("),
            badge_block.index(f"[![{self.upstream_sources.badge_title}]("),
        )
        self.assertLess(
            badge_block.index(f"[![{self.upstream_sources.badge_title}]("),
            badge_block.index("[![caveman]("),
        )
        self.assertLess(
            badge_block.index("[![GitHub commit activity]("),
            badge_block.index(f"[![{self.upstream_sources.badge_title}]("),
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
        badge_block = update_readme_badges.render_badge_block(
            metadata, self.upstream_sources
        )
        self.assertIn(
            "https://img.shields.io/github/commit-activity/m/example-owner/example-repo",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/github/license/example-owner/example-repo",
            badge_block,
        )
        self.assertIn(
            "https://github.com/example-owner/example-repo/commits/main",
            badge_block,
        )
        self.assertIn(
            "https://app.deepsource.com/gh/ZMB-UZH/omero-docker-extended.svg/?label=active+issues&show_trend=true&token=PzuHW2m-HGSR7AFW5klcqPzJ",
            badge_block,
        )
        self.assertIn(
            "https://app.deepsource.com/gh/ZMB-UZH/omero-docker-extended/",
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
            "https://img.shields.io/github/actions/workflow/status/example-owner/example-repo/security-code-scanning.yml?branch=main&label=security-code-scanning",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/codecov/c/github/example-owner/example-repo?label=Codecov&logo=codecov",
            badge_block,
        )
        self.assertIn(
            "https://github.com/python/mypy",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/github/actions/workflow/status/example-owner/example-repo/mypy.yml?branch=main&logo=python&label=Mypy",
            badge_block,
        )
        self.assertIn(
            "https://github.com/super-linter/super-linter",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/github/actions/workflow/status/example-owner/example-repo/super-linter.yml?branch=main&label=super-linter",
            badge_block,
        )
        self.assertIn(
            "https://github.com/astral-sh/ruff",
            badge_block,
        )
        self.assertIn(
            "https://github.com/jendrikseipp/vulture",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/github/actions/workflow/status/example-owner/example-repo/vulture.yml?branch=main&logo=python&label=Vulture",
            badge_block,
        )
        self.assertIn(
            "https://img.shields.io/static/v1?label=&message=caveman&color=555&logo=github&logoColor=white",
            badge_block,
        )
        self.assertNotIn(
            "https://img.shields.io/badge/caveman-555?logo=github&labelColor=555",
            badge_block,
        )
        self.assertNotIn(
            "https://img.shields.io/badge/caveman-555",
            badge_block,
        )
        self.assertIn(
            "https://github.com/JuliusBrussee/caveman",
            badge_block,
        )
        self.assertIn(
            self.upstream_sources.repo_url,
            badge_block,
        )
        self.assertIn(
            self.upstream_sources.badge_image_url,
            badge_block,
        )
        self.assertNotIn(
            self.upstream_sources.skills_tree_url,
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

    def test_canonical_badge_metadata_file_exists_and_is_complete(self) -> None:
        payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "host",
                "owner",
                "repo",
                "branch_name",
                "remote_name",
            },
            set(payload),
        )
        for key in ("host", "owner", "repo", "branch_name"):
            self.assertTrue(str(payload[key]).strip(), f"{key} must not be empty")

    def test_resolve_repo_metadata_prefers_canonical_metadata_file(self) -> None:
        with mock.patch("tools.update_readme_badges._run_git") as mocked_run_git:
            metadata = update_readme_badges.resolve_repo_metadata(self.repo_root)

        self.assertEqual(
            update_readme_badges.RepoMetadata(
                host="github.com",
                owner="ZMB-UZH",
                repo="omero-docker-extended",
                remote_name="canonical",
                branch_name="main",
            ),
            metadata,
        )
        mocked_run_git.assert_not_called()

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
        with (
            mock.patch(
                "tools.update_readme_badges.agent_skill_provenance.resolve_required_executable",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "tools.update_readme_badges.subprocess.run",
                return_value=mock.Mock(stdout="main\n"),
            ) as mocked_run,
        ):
            self.assertEqual(
                update_readme_badges._run_git(self.repo_root, "rev-parse", "HEAD"),
                "main",
            )

        mocked_run.assert_called_once_with(
            [
                "/usr/bin/git",
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
