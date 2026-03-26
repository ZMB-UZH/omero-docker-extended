from __future__ import annotations

import unittest
from pathlib import Path


class OmeroWebBootstrapRuntimeLogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.bootstrap_text = (
            cls.repo_root / "startup" / "10-web-bootstrap.sh"
        ).read_text(encoding="utf-8")
        cls.supervisord_text = (cls.repo_root / "supervisord.conf").read_text(
            encoding="utf-8"
        )

    def test_supervisord_declares_expected_log_targets(self) -> None:
        self.assertIn(
            "logfile=/opt/omero/web/logs/supervisord.log", self.supervisord_text
        )
        self.assertIn(
            "stderr_logfile=/opt/omero/web/OMERO.web/var/log/omero-web.stderr.log",
            self.supervisord_text,
        )
        self.assertIn(
            "stdout_logfile=/opt/omero/web/OMERO.web/var/log/omero-web.stdout.log",
            self.supervisord_text,
        )
        self.assertIn(
            "stderr_logfile=/opt/omero/web/OMERO.web/var/log/imaris-celery-worker.stderr.log",
            self.supervisord_text,
        )
        self.assertIn(
            "stdout_logfile=/opt/omero/web/OMERO.web/var/log/imaris-celery-worker.stdout.log",
            self.supervisord_text,
        )
        self.assertIn(
            "stderr_logfile=/opt/omero/web/OMERO.web/var/log/storage-quota-reconcile.stderr.log",
            self.supervisord_text,
        )
        self.assertIn(
            "stdout_logfile=/opt/omero/web/OMERO.web/var/log/storage-quota-reconcile.stdout.log",
            self.supervisord_text,
        )

    def test_bootstrap_prepares_runtime_log_targets_from_supervisord_config(
        self,
    ) -> None:
        self.assertIn(
            'supervisord_config_path="${OMERO_WEB_SUPERVISORD_CONFIG:-/etc/supervisord.conf}"',
            self.bootstrap_text,
        )
        self.assertIn("prepare_supervisor_logs_from_config()", self.bootstrap_text)
        self.assertIn(
            'prepare_supervisor_logs_from_config "${supervisord_config_path}"',
            self.bootstrap_text,
        )
        self.assertIn('case "${line}" in', self.bootstrap_text)
        self.assertIn(
            "logfile=*|stdout_logfile=*|stderr_logfile=*)", self.bootstrap_text
        )
        self.assertIn(
            'ensure_runtime_file "${log_path}" "${label}" 0664', self.bootstrap_text
        )

    def test_bootstrap_verifies_runtime_user_write_path_instead_of_root_only(
        self,
    ) -> None:
        self.assertIn("ensure_runtime_identity()", self.bootstrap_text)
        self.assertIn(
            'runuser -u "${runtime_user}" -- touch "${probe_path}"', self.bootstrap_text
        )
        self.assertIn(
            'runuser -u "${runtime_user}" -- test -w "${path}"', self.bootstrap_text
        )
        self.assertIn('quota_runtime_user="${runtime_user}"', self.bootstrap_text)
        self.assertIn('quota_runtime_group="${runtime_group}"', self.bootstrap_text)


if __name__ == "__main__":
    unittest.main()
