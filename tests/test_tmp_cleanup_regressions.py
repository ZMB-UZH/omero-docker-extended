import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase, main as unittest_main


REPO_ROOT = Path(__file__).resolve().parents[1]
BASH_BIN = "/bin/bash"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from omero_plugin_common import tmp_cleanup


class TmpCleanupRegressionTests(TestCase):
    """Test cases for tmp cleanup regression tests."""

    def test_safe_mark_path_for_deferred_cleanup_marks_directory_root(self):
        """Check safe mark path for deferred cleanup marks directory root cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions when safe mark path for deferred cleanup marks directory root accepts unsafe input.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "upload-job"
            target.mkdir()

            marked = tmp_cleanup.safe_mark_path_for_deferred_cleanup(
                target,
                root,
                ttl_seconds=120,
                now=1000,
            )

            self.assertTrue(marked)
            marker = target / tmp_cleanup.RETENTION_DIR_MARKER_NAME
            self.assertTrue(marker.exists())
            self.assertEqual("1120", marker.read_text(encoding="utf-8").strip())

    def test_safe_mark_path_for_deferred_cleanup_marks_file_sidecar(self):
        """Check safe mark path for deferred cleanup marks file sidecar cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions when safe mark path for deferred cleanup marks file sidecar accepts unsafe input.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "job.json"
            target.write_text("{}", encoding="utf-8")

            marked = tmp_cleanup.safe_mark_path_for_deferred_cleanup(
                target,
                root,
                ttl_seconds=300,
                now=2000,
            )

            self.assertTrue(marked)
            marker = root / f".{target.name}{tmp_cleanup.RETENTION_FILE_MARKER_SUFFIX}"
            self.assertTrue(marker.exists())
            self.assertEqual("2300", marker.read_text(encoding="utf-8").strip())

    def test_tmp_cleaner_respects_active_directory_retention_marker(self):
        """Verify tmp cleaner respects active directory retention marker.

        Inputs: repository fixtures. Output: fails on regressions in tmp cleaner respects active directory retention marker.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_dir = root / "omeroweb-import" / "data" / "job123"
            target_dir.mkdir(parents=True)
            payload = target_dir / "payload.bin"
            payload.write_text("payload", encoding="utf-8")
            tmp_cleanup.safe_mark_path_for_deferred_cleanup(
                target_dir,
                root,
                ttl_seconds=3600,
                now=time.time(),
            )
            old_time = time.time() - 7200
            os.utime(payload, (old_time, old_time))

            subprocess.run(
                [
                    BASH_BIN,
                    str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"),
                    "--tmp-dir",
                    str(root),
                    "--max-age-seconds",
                    "60",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(payload.exists())
            self.assertTrue(
                (target_dir / tmp_cleanup.RETENTION_DIR_MARKER_NAME).exists()
            )

    def test_tmp_cleaner_respects_active_file_retention_marker(self):
        """Verify tmp cleaner respects active file retention marker.

        Inputs: repository fixtures. Output: fails on regressions in tmp cleaner respects active file retention marker.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            job_file = root / "omeroweb-import" / "jobs" / "job123.json"
            job_file.parent.mkdir(parents=True)
            job_file.write_text("{}", encoding="utf-8")
            tmp_cleanup.safe_mark_path_for_deferred_cleanup(
                job_file,
                root,
                ttl_seconds=3600,
                now=time.time(),
            )
            old_time = time.time() - 7200
            os.utime(job_file, (old_time, old_time))

            subprocess.run(
                [
                    BASH_BIN,
                    str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"),
                    "--tmp-dir",
                    str(root),
                    "--max-age-seconds",
                    "60",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            marker = (
                job_file.parent
                / f".{job_file.name}{tmp_cleanup.RETENTION_FILE_MARKER_SUFFIX}"
            )
            self.assertTrue(job_file.exists())
            self.assertTrue(marker.exists())

    def test_tmp_cleaner_deletes_expired_retained_file(self):
        """Check tmp cleaner deletes expired retained file cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions in tmp cleaner deletes expired retained file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            job_file = root / "omeroweb-import" / "jobs" / "job123.json"
            job_file.parent.mkdir(parents=True)
            job_file.write_text("{}", encoding="utf-8")
            tmp_cleanup.safe_mark_path_for_deferred_cleanup(
                job_file,
                root,
                ttl_seconds=60,
                now=time.time() - 7200,
            )
            old_time = time.time() - 7200
            os.utime(job_file, (old_time, old_time))
            marker = (
                job_file.parent
                / f".{job_file.name}{tmp_cleanup.RETENTION_FILE_MARKER_SUFFIX}"
            )
            os.utime(marker, (old_time, old_time))

            subprocess.run(
                [
                    BASH_BIN,
                    str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"),
                    "--tmp-dir",
                    str(root),
                    "--max-age-seconds",
                    "60",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse(job_file.exists())

    def test_tmp_cleaner_preserves_structural_namespace_directories(self):
        """Check that tmp cleaner preserves structural namespace directories remains stable.

        Inputs: repository fixtures. Output: fails on regressions in tmp cleaner preserves structural namespace directories.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for ns in ("omero-web", "omero-server", "omeroweb-import"):
                (root / ns / "tmp").mkdir(parents=True)
            old_time = time.time() - 172800  # 48h
            for ns in ("omero-web", "omero-server", "omeroweb-import"):
                os.utime(root / ns, (old_time, old_time))
                os.utime(root / ns / "tmp", (old_time, old_time))

            subprocess.run(
                [
                    BASH_BIN,
                    str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"),
                    "--tmp-dir",
                    str(root),
                    "--max-age-seconds",
                    "60",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            for ns in ("omero-web", "omero-server", "omeroweb-import"):
                self.assertTrue(
                    (root / ns).is_dir(),
                    f"Structural namespace dir {ns}/ was deleted by cleaner",
                )
                self.assertTrue(
                    (root / ns / "tmp").is_dir(),
                    f"Structural namespace child directory under {ns}/ was deleted",
                )

    def test_tmp_cleaner_still_deletes_deep_empty_subdirectories(self):
        """Check tmp cleaner still deletes deep empty subdirectories cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions in tmp cleaner still deletes deep empty subdirectories.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "omero-web" / "tmp").mkdir(parents=True)
            ephemeral = root / "omero-web" / "tmp" / "runtime" / "session-abc"
            ephemeral.mkdir(parents=True)
            old_time = time.time() - 172800
            for p in (
                root / "omero-web",
                root / "omero-web" / "tmp",
                root / "omero-web" / "tmp" / "runtime",
                ephemeral,
            ):
                os.utime(p, (old_time, old_time))

            subprocess.run(
                [
                    BASH_BIN,
                    str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"),
                    "--tmp-dir",
                    str(root),
                    "--max-age-seconds",
                    "60",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse(ephemeral.exists())
            self.assertTrue((root / "omero-web" / "tmp").is_dir())
            self.assertTrue((root / "omero-web").is_dir())


if __name__ == "__main__":
    unittest_main()
