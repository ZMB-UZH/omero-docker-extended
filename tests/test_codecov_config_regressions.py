"""Regression checks for Codecov configuration ergonomics."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class CodecovConfigRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        cls.config = yaml.safe_load((repo_root / "codecov.yml").read_text(encoding="utf-8"))

    def test_pr_comment_layout_surfaces_components_and_files(self) -> None:
        comment = self.config["comment"]
        self.assertEqual("header, diff, components, files", comment["layout"])
        self.assertFalse(comment["require_changes"])
        self.assertFalse(comment["require_base"])
        self.assertTrue(comment["require_head"])

    def test_component_filters_cover_all_runtime_packages(self) -> None:
        component_entries = self.config["component_management"]["individual_components"]
        component_map = {entry["component_id"]: entry for entry in component_entries}

        self.assertEqual(
            {
                "omero_plugin_common",
                "omeroweb_admin_tools",
                "omeroweb_imaris_connector",
                "omeroweb_import",
                "omeroweb_omp_plugin",
            },
            set(component_map),
        )
        self.assertEqual(["omero_plugin_common/**"], component_map["omero_plugin_common"]["paths"])
        self.assertEqual(["omeroweb_admin_tools/**"], component_map["omeroweb_admin_tools"]["paths"])
        self.assertEqual(
            ["omeroweb_imaris_connector/**"],
            component_map["omeroweb_imaris_connector"]["paths"],
        )
        self.assertEqual(["omeroweb_import/**"], component_map["omeroweb_import"]["paths"])
        self.assertEqual(["omeroweb_omp_plugin/**"], component_map["omeroweb_omp_plugin"]["paths"])

    def test_github_annotations_are_disabled_when_components_are_enabled(self) -> None:
        github_checks = self.config["github_checks"]
        self.assertFalse(github_checks["annotations"])


if __name__ == "__main__":
    unittest.main()
