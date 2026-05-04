"""Tests for the regression-guard catalog and engine.

The tool's contract:

* every catalog rule fires on its synthesized bad fixture (selfcheck)
* the canonical good fixture stays clean (selfcheck)
* the actual repository working tree stays clean
* the catalog can render as text/JSON/Markdown
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import regression_guard


REPO_ROOT = Path(__file__).resolve().parents[1]


class RegressionGuardSelfCheckTests(unittest.TestCase):
    """Test cases for regression guard self check tests."""

    def test_selfcheck_passes(self) -> None:
        # ``selfcheck`` proves every rule fires on its fixture and that the
        # canonical good fixture stays silent. It returns 0 on success.
        """Verify selfcheck passes.

        Inputs: none. Output: None.
        """
        self.assertEqual(regression_guard.selfcheck(), 0)

    def test_repository_tree_is_clean(self) -> None:
        """Verify repository tree is clean.

        Inputs: none. Output: None.
        """
        findings = regression_guard.scan_paths(REPO_ROOT, paths=None)
        rendered = "\n".join(f.render() for f in findings)
        self.assertEqual(findings, [], f"unexpected findings:\n{rendered}")

    def test_catalog_has_minimum_coverage(self) -> None:
        """Verify catalog has minimum coverage.

        Inputs: none. Output: None.
        """
        ids = {rule.id for rule in regression_guard.CATALOG}
        # The catalog must continue to cover the historical hot families.
        for required in {"RG001", "RG002", "RG005", "RG009", "RG012", "RG015"}:
            self.assertIn(required, ids)

    def test_every_rule_has_fixture_and_metadata(self) -> None:
        """Verify every rule has fixture and metadata.

        Inputs: none. Output: None.
        """
        fixtures = regression_guard._selfcheck_fixtures()
        for rule in regression_guard.CATALOG:
            self.assertIn(rule.id, fixtures, f"missing fixture for {rule.id}")
            self.assertIn(rule.severity, regression_guard.SEVERITY_ORDER)
            self.assertTrue(rule.title.strip(), f"{rule.id} missing title")
            self.assertTrue(rule.fix.strip(), f"{rule.id} missing fix guidance")
            self.assertTrue(rule.scanner.strip(), f"{rule.id} missing scanner crossref")


class RegressionGuardEngineTests(unittest.TestCase):
    """Test cases for regression guard engine tests."""

    @staticmethod
    def _scan_one(rel_name: str, content: str) -> list[regression_guard.Finding]:
        """Scan one.

        Inputs: `rel_name`, `content`. Output: `list[regression_guard.Finding]`.
        """
        with tempfile.TemporaryDirectory(prefix="rg_engine_") as tmp:
            root = Path(tmp)
            target = root / rel_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return regression_guard.scan_paths(root, [target])

    def test_specific_exception_handler_is_not_flagged(self) -> None:
        # ``except (TypeError, ValueError): continue`` is a deliberate
        # type-narrowing pattern used in production parsers and must not be
        # treated as a regression. RG002 fires only on broad excepts.
        """Verify specific exception handler is not flagged.

        Inputs: none. Output: None.
        """
        findings = self._scan_one(
            "module/specific.py",
            "def f():\n"
            "    try: do()\n"
            "    except (TypeError, ValueError):\n"
            "        continue\n",
        )
        rule_hits = [f.rule_id for f in findings if f.rule_id == "RG002"]
        self.assertEqual(rule_hits, [])

    def test_broad_exception_handler_is_flagged(self) -> None:
        """Verify broad exception handler is flagged.

        Inputs: none. Output: None.
        """
        findings = self._scan_one(
            "module/broad.py",
            "def f():\n    try: do()\n    except Exception:\n        pass\n",
        )
        self.assertTrue(any(f.rule_id == "RG002" for f in findings))

    def test_test_files_skip_assert_rule(self) -> None:
        """Verify module paths skip the assert-statement rule.

        Inputs: none. Output: None.
        """
        findings = self._scan_one(
            "module/tests/test_assert_ok.py",
            "def test_ok():\n    assert 1 == 1\n",
        )
        self.assertFalse(any(f.rule_id == "RG001" for f in findings))

    def test_runtime_data_roots_are_not_scanned_as_source(self) -> None:
        """Verify runtime data roots are not scanned as source.

        Inputs: none. Output: None.
        """
        with tempfile.TemporaryDirectory(prefix="rg_runtime_") as tmp:
            root = Path(tmp)
            runtime_file = root / "omero_data" / "ManagedRepository" / "secret.txt"
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_text("token=" + "ghp_" + ("A" * 36), encoding="utf-8")

            self.assertEqual(regression_guard.scan_paths(root, paths=None), [])
            self.assertEqual(regression_guard.scan_paths(root, [runtime_file]), [])

    def test_chmod_safe_mode_is_not_flagged(self) -> None:
        """Verify chmod safe mode is not flagged.

        Inputs: none. Output: None.
        """
        findings = self._scan_one(
            "module/safe_chmod.py",
            "import os\nos.chmod('/srv/x', 0o640)\n",
        )
        self.assertFalse(any(f.rule_id == "RG009" for f in findings))

    def test_pinned_action_is_not_flagged(self) -> None:
        # Build the 40-char hex SHA at runtime so DevSkim DS173237 does not
        # treat it as a token-shaped literal in the test source.
        """Verify pinned action is not flagged.

        Inputs: none. Output: None.
        """
        sha = "0" * 40
        findings = self._scan_one(
            ".github/workflows/sample.yml",
            "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@"
            + sha
            + "  # v6\n",
        )
        self.assertFalse(any(f.rule_id == "RG012" for f in findings))


class RegressionGuardCliTests(unittest.TestCase):
    """Test cases for regression guard cli tests."""

    def test_catalog_text_render(self) -> None:
        """Verify catalog text render.

        Inputs: none. Output: None.
        """
        text = regression_guard.render_text()
        self.assertIn("RG001", text)
        self.assertIn("RG015", text)

    def test_catalog_markdown_render_is_self_describing(self) -> None:
        """Verify catalog markdown render is self describing.

        Inputs: none. Output: None.
        """
        md = regression_guard.render_markdown()
        self.assertIn("python3 tools/regression_guard.py", md)
        self.assertIn("| `RG001` |", md)

    def test_catalog_json_round_trip(self) -> None:
        """Verify catalog JSON round trip.

        Inputs: none. Output: None.
        """
        payload = json.loads(regression_guard.render_json())
        self.assertEqual(len(payload), len(regression_guard.CATALOG))
        for entry in payload:
            self.assertIn("id", entry)
            self.assertIn("severity", entry)
            self.assertIn("scanner", entry)


if __name__ == "__main__":
    unittest.main()
