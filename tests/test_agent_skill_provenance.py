"""Unit tests for agent skill provenance helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import TestCase, main, mock

from tools import agent_skill_provenance


class AgentSkillProvenanceTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.sources = agent_skill_provenance.load_upstream_sources(cls.repo_root)

    def test_badge_image_url_uses_stable_static_components(self) -> None:
        self.assertIn("/badge/upstream-", self.sources.badge_image_url)
        self.assertIn("ECC%20v1.9.0%20skills", self.sources.badge_image_url)
        self.assertNotIn(self.sources.repo_slug, self.sources.badge_image_url)

    def test_fetch_text_rejects_unapproved_hosts_and_schemes(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported fetch scheme"):
            agent_skill_provenance.fetch_text("http://raw.githubusercontent.com/x/y")
        with self.assertRaisesRegex(ValueError, "Unsupported fetch host"):
            agent_skill_provenance.fetch_text("https://github.com/x/y")

    def test_fetch_text_uses_curl_for_allowed_upstream_raw_urls(self) -> None:
        with mock.patch(
            "tools.agent_skill_provenance.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="payload", stderr=""),
        ) as mocked_run:
            payload = agent_skill_provenance.fetch_text(
                "https://raw.githubusercontent.com/affaan-m/everything-claude-code/v1.9.0/skills/search-first/SKILL.md",
                timeout=17,
            )

        self.assertEqual("payload", payload)
        mocked_run.assert_called_once_with(
            [
                "curl",
                "--silent",
                "--show-error",
                "--location",
                "--fail",
                "--header",
                "User-Agent: omero-agent-skill-audit",
                "--max-time",
                "17",
                "https://raw.githubusercontent.com/affaan-m/everything-claude-code/v1.9.0/skills/search-first/SKILL.md",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=22,
        )

    def test_fetch_text_surfaces_curl_failures(self) -> None:
        with mock.patch(
            "tools.agent_skill_provenance.subprocess.run",
            return_value=mock.Mock(returncode=22, stdout="", stderr="404 Not Found"),
        ):
            with self.assertRaisesRegex(RuntimeError, "404 Not Found"):
                agent_skill_provenance.fetch_text(
                    "https://raw.githubusercontent.com/affaan-m/everything-claude-code/v1.9.0/skills/search-first/SKILL.md"
                )

    def test_fetch_text_surfaces_transport_exceptions(self) -> None:
        with mock.patch(
            "tools.agent_skill_provenance.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["curl"], timeout=20),
        ):
            with self.assertRaisesRegex(RuntimeError, "Upstream fetch failed"):
                agent_skill_provenance.fetch_text(
                    "https://raw.githubusercontent.com/affaan-m/everything-claude-code/v1.9.0/skills/search-first/SKILL.md"
                )


if __name__ == "__main__":
    main()
