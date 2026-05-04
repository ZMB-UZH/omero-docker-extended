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

        Inputs: repository fixtures. Output: fails on regressions in selfcheck passes.
        """
        self.assertEqual(regression_guard.selfcheck(), 0)

    def test_repository_tree_is_clean(self) -> None:
        """Verify repository tree is clean.

        Inputs: repository fixtures. Output: fails on regressions in repository tree is clean.
        """
        findings = regression_guard.scan_paths(REPO_ROOT, paths=None)
        rendered = "\n".join(f.render() for f in findings)
        self.assertEqual(findings, [], f"unexpected findings:\n{rendered}")

    def test_catalog_has_minimum_coverage(self) -> None:
        """Verify catalog has minimum coverage.

        Inputs: repository fixtures. Output: fails on regressions in catalog has minimum coverage.
        """
        ids = {rule.id for rule in regression_guard.CATALOG}
        # The catalog must continue to cover the historical hot families.
        for required in {"RG001", "RG002", "RG005", "RG009", "RG012", "RG015"}:
            self.assertIn(required, ids)

    def test_every_rule_has_fixture_and_metadata(self) -> None:
        """Verify every rule has fixture and metadata.

        Inputs: repository fixtures. Output: fails on regressions in every rule has fixture and metadata.
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
        """Scan the one for `RegressionGuardEngineTests`.

        Inputs: `rel_name` (str), `content` (str). Output:
        `list[regression_guard.Finding]`.
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
        """Confirm specific exception handler is not flagged exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions when specific exception handler is not flagged stops reporting the expected error.
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
        """Confirm broad exception handler is flagged exposes the expected failure.

        Inputs: repository fixtures. Output: fails on regressions when broad exception handler is flagged stops reporting the expected error.
        """
        findings = self._scan_one(
            "module/broad.py",
            "def f():\n    try: do()\n    except Exception:\n        pass\n",
        )
        self.assertTrue(any(f.rule_id == "RG002" for f in findings))

    def test_test_files_skip_assert_rule(self) -> None:
        """Verify regression guard allows plain asserts inside test files.

        Inputs: repository fixtures. Output: fails on regressions in assert-rule
        scoping for test modules.
        """
        findings = self._scan_one(
            "module/tests/test_assert_ok.py",
            "def test_ok():\n    assert 1 == 1\n",
        )
        self.assertFalse(any(f.rule_id == "RG001" for f in findings))

    def test_runtime_data_roots_are_not_scanned_as_source(self) -> None:
        """Verify runtime data roots are not scanned as source.

        Inputs: repository fixtures. Output: fails on regressions in runtime data roots are not scanned as source.
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

        Inputs: repository fixtures. Output: fails on regressions in chmod safe mode is not flagged.
        """
        findings = self._scan_one(
            "module/safe_chmod.py",
            "import os\nos.chmod('/srv/x', 0o640)\n",
        )
        self.assertFalse(any(f.rule_id == "RG009" for f in findings))

    def test_pinned_action_is_not_flagged(self) -> None:
        # Build the 40-char hex SHA at runtime so DevSkim DS173237 does not
        # treat it as a token-shaped literal in the test source.
        """Verify the pinned action is not flagged execution contract.

        Inputs: repository fixtures. Output: fails on regressions in pinned action is not flagged integration.
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

        Inputs: repository fixtures. Output: fails on regressions in catalog text render.
        """
        text = regression_guard.render_text()
        self.assertIn("RG001", text)
        self.assertIn("RG015", text)

    def test_catalog_markdown_render_is_self_describing(self) -> None:
        """Verify catalog markdown render is self describing.

        Inputs: repository fixtures. Output: fails on regressions in catalog markdown render is self describing.
        """
        md = regression_guard.render_markdown()
        self.assertIn("python3 tools/regression_guard.py", md)
        self.assertIn("| `RG001` |", md)

    def test_catalog_json_round_trip(self) -> None:
        """Verify catalog JSON round trip.

        Inputs: repository fixtures. Output: fails on regressions in catalog JSON round trip.
        """
        payload = json.loads(regression_guard.render_json())
        self.assertEqual(len(payload), len(regression_guard.CATALOG))
        for entry in payload:
            self.assertIn("id", entry)
            self.assertIn("severity", entry)
            self.assertIn("scanner", entry)


if __name__ == "__main__":
    unittest.main()
