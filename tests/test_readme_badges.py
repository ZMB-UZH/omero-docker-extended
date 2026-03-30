"""Regression tests for the generated README badge block."""

from __future__ import annotations

import unittest
from pathlib import Path

from tools import update_readme_badges


class ReadmeBadgeGenerationTests(unittest.TestCase):
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
            badge_block.index("[![Tests]("),
        )
        self.assertLess(
            badge_block.index("[![Tests]("),
            badge_block.index("[![Code coverage]("),
        )
        self.assertLess(
            badge_block.index("[![Code coverage]("),
            badge_block.index("[![Ruff]("),
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


if __name__ == "__main__":
    unittest.main()
