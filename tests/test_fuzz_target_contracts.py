from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class FuzzTargetContractTests(unittest.TestCase):
    """Test cases for fuzz target contract tests."""

    def test_filename_parser_atheris_target_exists_and_targets_parse_filename(
        self,
    ) -> None:
        """Verify test filename parser atheris target exists an behavior."""
        fuzz_target = REPO_ROOT / "fuzzing" / "fuzz_filename_parser.py"
        fuzz_text = fuzz_target.read_text(encoding="utf-8")
        self.assertIn("import atheris", fuzz_text)
        self.assertIn("parse_filename", fuzz_text)
        self.assertIn("def TestOneInput(data: bytes) -> None:", fuzz_text)
        self.assertIn("atheris.Fuzz()", fuzz_text)


if __name__ == "__main__":
    unittest.main()
