from __future__ import annotations

import unittest
from html.parser import HTMLParser
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
    """Test cases for Zarr toolbar template contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `ZarrToolbarTemplateContractTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.template_text = TOOLBAR_TEMPLATE.read_text(encoding="utf-8")

    def test_toolbar_bootstraps_selection_data_via_json_script_block(self) -> None:
        """Verify the toolbar bootstraps selection data via JSON script block execution contract.

        Inputs: repository fixtures. Output: fails on regressions in toolbar bootstraps selection data via JSON script block integration.
        """
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
            'var shareMode = "{{ share|yesno:\'true,false\' }}" === "true";',
            self.template_text,
        )
        self.assertIn("if (!shareMode) {", self.template_text)
        self.assertIn("function sanitizeOpenwithUrl(candidateUrl)", self.template_text)
        self.assertIn("function buildOpenwithMenuItems()", self.template_text)
        self.assertIn('var $link = $("<a/>")', self.template_text)
        self.assertIn("var safeUrl = sanitizeOpenwithUrl(url);", self.template_text)
        self.assertIn('.attr("href", safeUrl)', self.template_text)
        self.assertIn(".text(label);", self.template_text)
        self.assertIn("$menu.empty();", self.template_text)
        self.assertNotIn('$("#right_panel_openwith").html(', self.template_text)
        self.assertNotIn(
            "{% if not share %}\n                function getOpenwithHtml()",
            self.template_text,
        )

    def test_full_viewer_cannot_control_the_opener(self) -> None:
        """Require browser isolation on the actual full-viewer link.

        Inputs: tracked toolbar template. Output: parsed anchor attribute checks.
        """
        links = []

        class Links(HTMLParser):
            """Collect anchor attributes while ignoring template text."""

            def handle_starttag(self, tag, attrs):
                """Inputs: parsed HTML tag and attributes. Output: collected links."""
                if tag == "a":
                    links.append(dict(attrs))

        Links().feed(self.template_text)
        viewer = [link for link in links if link.get("id") == "open_full_viewer"]
        self.assertEqual(len(viewer), 1)
        self.assertEqual(viewer[0]["target"], "_blank")
        self.assertEqual(set(viewer[0]["rel"].split()), {"noopener", "noreferrer"})


if __name__ == "__main__":
    unittest.main()
