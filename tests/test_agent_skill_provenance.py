"""Unit tests for agent skill provenance helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest import TestCase, main, mock

from tools import agent_skill_provenance


class AgentSkillProvenanceTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.sources = agent_skill_provenance.load_upstream_sources(cls.repo_root)

    def test_badge_image_url_uses_stable_static_components(self) -> None:
        parsed = urlsplit(self.sources.badge_image_url)
        self.assertEqual("https", parsed.scheme)
        self.assertEqual("img.shields.io", parsed.netloc)
        self.assertEqual("/static/v1", parsed.path)
        self.assertEqual(
            {
                "label": [""],
                "message": ["everything-claude-code"],
                "color": ["555"],
                "logo": ["github"],
                "logoColor": ["white"],
            },
            parse_qs(parsed.query, keep_blank_values=True),
        )
        self.assertNotIn(self.sources.repo_slug, self.sources.badge_image_url)
        self.assertEqual("everything-claude-code", self.sources.badge_title)

    def test_repo_url_and_skills_tree_url_remain_stable(self) -> None:
        self.assertEqual(
            "https://github.com/affaan-m/everything-claude-code",
            self.sources.repo_url,
        )
        self.assertEqual(
            ("https://github.com/affaan-m/everything-claude-code/tree/v1.10.0/skills"),
            self.sources.skills_tree_url,
        )

    def test_fetch_text_rejects_unapproved_hosts_and_schemes(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported fetch scheme"):
            agent_skill_provenance.fetch_text("ssh://raw.githubusercontent.com/x/y")
        with self.assertRaisesRegex(ValueError, "Unsupported fetch host"):
            agent_skill_provenance.fetch_text("https://github.com/x/y")

    def test_fetch_text_uses_curl_for_allowed_upstream_raw_urls(self) -> None:
        allowed_url = self.sources.raw_skill_url("search-first")
        with (
            mock.patch(
                "tools.agent_skill_provenance.resolve_required_executable",
                return_value="/usr/bin/curl",
            ),
            mock.patch(
                "tools.agent_skill_provenance.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="payload", stderr=""),
            ) as mocked_run,
        ):
            payload = agent_skill_provenance.fetch_text(allowed_url, timeout=17)

        self.assertEqual("payload", payload)
        mocked_run.assert_called_once_with(
            [
                "/usr/bin/curl",
                "--silent",
                "--show-error",
                "--location",
                "--fail",
                "--header",
                "User-Agent: omero-agent-skill-audit",
                "--max-time",
                "17",
                allowed_url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=22,
        )

    def test_fetch_text_surfaces_curl_failures(self) -> None:
        allowed_url = self.sources.raw_skill_url("search-first")
        with (
            mock.patch(
                "tools.agent_skill_provenance.resolve_required_executable",
                return_value="/usr/bin/curl",
            ),
            mock.patch(
                "tools.agent_skill_provenance.subprocess.run",
                return_value=mock.Mock(
                    returncode=22, stdout="", stderr="404 Not Found"
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "404 Not Found"),
        ):
            agent_skill_provenance.fetch_text(allowed_url)

    def test_fetch_text_surfaces_transport_exceptions(self) -> None:
        allowed_url = self.sources.raw_skill_url("search-first")
        with (
            mock.patch(
                "tools.agent_skill_provenance.resolve_required_executable",
                return_value="/usr/bin/curl",
            ),
            mock.patch(
                "tools.agent_skill_provenance.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["/usr/bin/curl"], timeout=20
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "Upstream fetch failed"),
        ):
            agent_skill_provenance.fetch_text(allowed_url)

    def test_resolve_required_executable_rejects_missing_command(self) -> None:
        with (
            mock.patch(
                "tools.agent_skill_provenance.shutil.which",
                return_value=None,
            ),
            self.assertRaisesRegex(RuntimeError, "not available in PATH"),
        ):
            agent_skill_provenance.resolve_required_executable("curl")


if __name__ == "__main__":
    main()
