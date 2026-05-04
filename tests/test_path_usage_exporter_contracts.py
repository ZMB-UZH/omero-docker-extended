from __future__ import annotations

import importlib.util
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = (
    REPO_ROOT / "monitoring" / "path-usage-exporter" / "path_usage_exporter.py"
)


class PathUsageExporterContractTests(TestCase):
    """Test cases for path usage exporter contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `PathUsageExporterContractTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks. Raises: RuntimeError for the exercised failure path.
        """
        spec = importlib.util.spec_from_file_location(
            "path_usage_exporter", EXPORTER_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {EXPORTER_PATH}")
        cls.exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.exporter)
        cls.dockerfile_text = (
            REPO_ROOT / "docker" / "path-usage-exporter.Dockerfile"
        ).read_text(encoding="utf-8")
        cls.installation_script_text = (
            REPO_ROOT / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")

    def test_exporter_image_runs_as_dedicated_non_root_user(self) -> None:
        """Verify exporter image runs as dedicated non root user.

        Inputs: repository fixtures. Output: fails on regressions in exporter image runs as dedicated non root user.
        """
        self.assertIn("addgroup -S omero-path-exporter", self.dockerfile_text)
        self.assertIn(
            "adduser -S -D -H -G omero-path-exporter omero-path-exporter",
            self.dockerfile_text,
        )
        self.assertIn("USER omero-path-exporter", self.dockerfile_text)

    def test_installation_assigns_textfile_directory_to_exporter_uid_gid(self) -> None:
        """Verify installation assigns textfile directory to exporter uid gid.

        Inputs: repository fixtures. Output: fails on regressions in installation assigns textfile directory to exporter uid gid.
        """
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

    def test_path_translation_requires_absolute_host_paths(self) -> None:
        """Verify the path translation requires absolute host paths safety boundary.

        Inputs: repository fixtures. Output: fails on regressions when path translation requires absolute host paths accepts unsafe input.
        """
        self.assertEqual(
            self.exporter.host_path_for_df("/srv/omero/../data", "/host"),
            "/host/srv/data",
        )
        self.assertEqual(
            self.exporter.host_path_for_df("/../../etc", "/host"),
            "/host/etc",
        )
        with self.assertRaises(ValueError):
            self.exporter.host_path_for_df("relative/path", "/host")

    def test_prometheus_labels_are_escaped_in_rendered_metrics(self) -> None:
        """Verify prometheus labels are escaped in rendered metrics.

        Inputs: repository fixtures. Output: fails on regressions in prometheus labels are escaped in rendered metrics.
        """
        path_value = '/data/"quoted\\line\nnext'
        mountpoint = '/host/data/"quoted\\mount\nnext'

        with (
            mock.patch.object(self.exporter.os.path, "exists", return_value=True),
            mock.patch.object(
                self.exporter, "df_usage", return_value=(mountpoint, 2048, 1024, 0.5)
            ),
        ):
            metrics = self.exporter.render_metrics({"OMERO_DATA_PATH": path_value})

        self.assertIn('path="/data/\\"quoted\\\\line\\nnext"', metrics)
        self.assertIn('mountpoint="/host/data/\\"quoted\\\\mount\\nnext"', metrics)
        self.assertIn('omero_path_used_ratio{kind="omero_data"', metrics)

    def test_df_usage_times_out_and_rejects_malformed_numbers(self) -> None:
        """Confirm df usage times out and rejects malformed numbers is rejected at the boundary.

        Inputs: repository fixtures. Output: fails on regressions in df usage times out and rejects malformed numbers.
        """
        with mock.patch.object(
            self.exporter.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["df"], 1),
        ):
            self.assertIsNone(self.exporter.df_usage("/host/data", timeout_seconds=1))

        bad_completed = subprocess.CompletedProcess(
            ["df"],
            0,
            stdout=(
                "Filesystem 1B-blocks Used Available Use% Mounted on\n"
                "/dev/test not-a-number 10 5 50% /host/data\n"
            ),
            stderr="",
        )
        with mock.patch.object(
            self.exporter.subprocess, "run", return_value=bad_completed
        ):
            self.assertIsNone(self.exporter.df_usage("/host/data"))

    def test_write_metrics_uses_atomic_temp_file_in_output_directory(self) -> None:
        """Verify write metrics uses atomic temp file in output directory.

        Inputs: repository fixtures. Output: fails on regressions in write metrics uses atomic temp file in output directory.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "omero_paths.prom"

            with mock.patch.object(self.exporter, "OUT", str(output_path)):
                self.exporter.write_metrics("metric 1\n")

            self.assertEqual(output_path.read_text(encoding="utf-8"), "metric 1\n")
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o644)
            self.assertEqual(list(Path(tmp_dir).glob("*.tmp")), [])
            self.assertEqual(list(Path(tmp_dir).glob(".*.tmp")), [])


if __name__ == "__main__":
    main()
