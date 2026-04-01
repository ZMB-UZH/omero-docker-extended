from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLBAR_TEMPLATE = (
    REPO_ROOT
    / "omero_web_zarr"
    / "templates"
    / "webclient"
    / "annotations"
    / "includes"
    / "toolbar.html"
)


class ZarrToolbarTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template_text = TOOLBAR_TEMPLATE.read_text(encoding="utf-8")

    def test_toolbar_bootstraps_selection_data_via_json_script_block(self) -> None:
        self.assertIn(
            '<script id="zarr-toolbar-selection-data" type="application/json">',
            self.template_text,
        )
        self.assertIn(
            '<script id="zarr-toolbar-manager-selection-data" type="application/json">',
            self.template_text,
        )
        self.assertIn("JSON.parse(selectionNode.textContent)", self.template_text)
        self.assertIn(
            "JSON.parse(managerSelectionNode.textContent)", self.template_text
        )
        self.assertIn('return item.type + "-" + item.id;', self.template_text)
        self.assertNotIn(
            "var selectedObjs = [{% for o in obj_labels %}",
            self.template_text,
        )
        self.assertIn(
            "var shareMode = \"{{ share|yesno:'true,false' }}\" === \"true\";",
            self.template_text,
        )
        self.assertIn("if (!shareMode) {", self.template_text)
        self.assertNotIn(
            "{% if not share %}\n                function getOpenwithHtml()",
            self.template_text,
        )


if __name__ == "__main__":
    unittest.main()
