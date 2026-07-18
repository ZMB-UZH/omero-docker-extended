"""Unit tests for agent skill provenance helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest import TestCase, main, mock

from tools import agent_skill_provenance


class AgentSkillProvenanceTests(TestCase):
    """Test cases for agent skill provenance tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `AgentSkillProvenanceTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.sources = agent_skill_provenance.load_upstream_sources(cls.repo_root)

    def test_badge_image_url_uses_stable_static_components(self) -> None:
        """Check that badge image URL uses stable static components remains stable.

        Inputs: repository fixtures. Output: fails on regressions in badge image URL uses stable static components.
        """
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
        """Check that repo URL and skills tree URL remain stable remains stable.

        Inputs: repository fixtures. Output: fails on regressions in repo URL and skills tree URL remain stable.
        """
        self.assertEqual(
            "https://github.com/affaan-m/everything-claude-code",
            self.sources.repo_url,
        )
        self.assertEqual(
            ("https://github.com/affaan-m/everything-claude-code/tree/v2.0.0/skills"),
            self.sources.skills_tree_url,
        )

    def test_vendor_snapshot_excludes_upstream_runtime_documentation(self) -> None:
        """Verify the vendor snapshot excludes upstream runtime documentation.

        Inputs: repository fixtures. Output: verifies unused cross-platform
        installation material is absent from the Linux-only snapshot.
        """
        vendor_root = self.repo_root / "third_party" / "ecc-v2.0.0"

        self.assertTrue((vendor_root / "LICENSE").is_file())
        self.assertFalse((vendor_root / "README.md").exists())

    def test_fetch_text_rejects_unapproved_hosts_and_schemes(self) -> None:
        """Confirm fetch text rejects unapproved hosts and schemes is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in fetch text rejects unapproved hosts and schemes.
        """
        with self.assertRaisesRegex(ValueError, "Unsupported fetch scheme"):
            agent_skill_provenance.fetch_text("ssh://raw.githubusercontent.com/x/y")
        with self.assertRaisesRegex(ValueError, "Unsupported fetch host"):
            agent_skill_provenance.fetch_text("https://github.com/x/y")

    def test_strip_local_scanner_annotations_preserves_upstream_text(self) -> None:
        """Verify scanner annotations can be stripped from vendored skill text.

        Inputs: sample text. Output: fails on provenance normalization regressions.
        """
        local_text = "\n".join(
            (
                "before",
                "# skipcq: SCT-A000",
                "python_line()",
                "  // skipcq: JS-0833",
                "js_line();",
                "<!-- skipcq: SCT-1000 -->",
                "after",
                "",
            )
        )

        self.assertEqual(
            "before\npython_line()\njs_line();\nafter\n",
            agent_skill_provenance.strip_local_scanner_annotations(local_text),
        )

    def test_fetch_text_uses_curl_for_allowed_upstream_raw_urls(self) -> None:
        """Verify fetch text uses curl for allowed upstream raw URLs.

        Inputs: repository fixtures. Output: fails on regressions in fetch text uses curl for allowed upstream raw URLs.
        """
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
        """Verify fetch text surfaces curl failures.

        Inputs: repository fixtures. Output: fails on regressions in fetch text surfaces curl failures.
        """
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
        """Verify fetch text surfaces transport exceptions.

        Inputs: repository fixtures. Output: fails on regressions in fetch text surfaces transport exceptions.
        """
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
        """Confirm resolve required executable rejects missing command is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in resolve required executable rejects missing command integration.
        """
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
