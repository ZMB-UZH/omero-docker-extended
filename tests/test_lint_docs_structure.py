"""Tests for docs structure validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.lint_docs_structure import run_validations


class DocsStructureLintTests(unittest.TestCase):
    """Coverage for docs lint helper."""

    def test_validation_passes_for_project_repository(self) -> None:
        repo_root: Path = Path(__file__).resolve().parents[1]
        errors = run_validations(repo_root)
        self.assertEqual(errors, [])

    def test_validation_fails_when_index_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
            errors = run_validations(repo_root)
            self.assertTrue(any("docs/index.md" in err.message for err in errors))


if __name__ == "__main__":
    unittest.main()
