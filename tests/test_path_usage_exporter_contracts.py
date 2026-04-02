from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PathUsageExporterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dockerfile_text = (
            REPO_ROOT / "docker" / "path-usage-exporter.Dockerfile"
        ).read_text(encoding="utf-8")
        cls.installation_script_text = (
            REPO_ROOT / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")

    def test_exporter_image_runs_as_dedicated_non_root_user(self) -> None:
        self.assertIn("addgroup -S omero-path-exporter", self.dockerfile_text)
        self.assertIn(
            "adduser -S -D -H -G omero-path-exporter omero-path-exporter",
            self.dockerfile_text,
        )
        self.assertIn("USER omero-path-exporter", self.dockerfile_text)

    def test_installation_assigns_textfile_directory_to_exporter_uid_gid(self) -> None:
        self.assertIn(
            'PATH_USAGE_EXPORTER_IMAGE="${PATH_USAGE_EXPORTER_IMAGE:-path-usage-exporter:custom}"',
            self.installation_script_text,
        )
        self.assertIn(
            'PATH_USAGE_EXPORTER_UID="$(discover_container_default_id_or_die "${PATH_USAGE_EXPORTER_IMAGE}" "-u")"',
            self.installation_script_text,
        )
        self.assertIn(
            'PATH_USAGE_EXPORTER_GID="$(discover_container_default_id_or_die "${PATH_USAGE_EXPORTER_IMAGE}" "-g")"',
            self.installation_script_text,
        )
        self.assertIn(
            'chown_tree_or_die "${NODE_EXPORTER_TEXTFILE_PATH}" "Node exporter textfile directory" "${PATH_USAGE_EXPORTER_UID}" "${PATH_USAGE_EXPORTER_GID}"',
            self.installation_script_text,
        )


if __name__ == "__main__":
    unittest.main()
