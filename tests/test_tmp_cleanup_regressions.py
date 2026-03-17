import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase, main as unittest_main


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from omero_plugin_common import tmp_cleanup


class TmpCleanupRegressionTests(TestCase):
    def test_safe_mark_path_for_deferred_cleanup_marks_directory_root(self):
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
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_dir = root / "omeroweb-upload" / "data" / "job123"
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
                ["bash", str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"), "--tmp-dir", str(root), "--max-age-seconds", "60"],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(payload.exists())
            self.assertTrue((target_dir / tmp_cleanup.RETENTION_DIR_MARKER_NAME).exists())

    def test_tmp_cleaner_respects_active_file_retention_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            job_file = root / "omeroweb-upload" / "jobs" / "job123.json"
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
                ["bash", str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"), "--tmp-dir", str(root), "--max-age-seconds", "60"],
                check=True,
                capture_output=True,
                text=True,
            )

            marker = job_file.parent / f".{job_file.name}{tmp_cleanup.RETENTION_FILE_MARKER_SUFFIX}"
            self.assertTrue(job_file.exists())
            self.assertTrue(marker.exists())

    def test_tmp_cleaner_deletes_expired_retained_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            job_file = root / "omeroweb-upload" / "jobs" / "job123.json"
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
            marker = job_file.parent / f".{job_file.name}{tmp_cleanup.RETENTION_FILE_MARKER_SUFFIX}"
            os.utime(marker, (old_time, old_time))

            subprocess.run(
                ["bash", str(REPO_ROOT / "scripts/omero-tmp-cleaner.sh"), "--tmp-dir", str(root), "--max-age-seconds", "60"],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse(job_file.exists())


if __name__ == "__main__":
    unittest_main()
