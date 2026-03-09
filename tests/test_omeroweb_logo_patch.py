from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OmeroWebLogoPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.patch_script = cls.repo_root / "docker" / "patch_omeroweb_logo_context.py"

    def test_patch_script_updates_logo_context_block(self) -> None:
        original_text = """\
def example(context, settings):
        if settings.TOP_LOGO:
            context["ome"]["logo_src"] = settings.TOP_LOGO
        if settings.TOP_LOGO_LINK:
            context["ome"]["logo_href"] = settings.TOP_LOGO_LINK
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_path = Path(tmp_dir) / "decorators.py"
            target_path.write_text(original_text, encoding="utf-8")

            subprocess.run(
                [sys.executable, str(self.patch_script), str(target_path)],
                check=True,
            )
            subprocess.run(
                [sys.executable, str(self.patch_script), str(target_path)],
                check=True,
            )

            patched_text = target_path.read_text(encoding="utf-8")
            self.assertIn('context["ome"].setdefault("logo_src", "")', patched_text)
            self.assertIn('context["ome"].setdefault("logo_href", "")', patched_text)
            self.assertEqual(patched_text.count('context["ome"].setdefault("logo_src", "")'), 1)
            self.assertEqual(patched_text.count('context["ome"].setdefault("logo_href", "")'), 1)
            self.assertIn('if settings.TOP_LOGO:', patched_text)
            self.assertIn('if settings.TOP_LOGO_LINK:', patched_text)


if __name__ == "__main__":
    unittest.main()
