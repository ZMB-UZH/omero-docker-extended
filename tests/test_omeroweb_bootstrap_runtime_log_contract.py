from __future__ import annotations

import unittest
from pathlib import Path


class OmeroWebBootstrapRuntimeLogContractTests(unittest.TestCase):
    """Test cases for OMERO web bootstrap runtime log contract tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Store set up class."""
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.bootstrap_text = (
            cls.repo_root / "startup" / "10-web-bootstrap.sh"
        ).read_text(encoding="utf-8")
        cls.supervisord_text = (cls.repo_root / "supervisord.conf").read_text(
            encoding="utf-8"
        )

    def test_supervisord_declares_expected_log_targets(self) -> None:
        """Verify test supervisord declares expected log targets."""
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
            "stderr_logfile=/opt/omero/web/OMERO.web/var/log/tools-celery-worker.stderr.log",
            self.supervisord_text,
        )
        self.assertIn(
            "stdout_logfile=/opt/omero/web/OMERO.web/var/log/tools-celery-worker.stdout.log",
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
        """Verify test bootstrap prepares runtime log targets f behavior."""
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

    def test_bootstrap_ensures_tmpdir_for_session_storage(self) -> None:
        """Verify test bootstrap ensures tmpdir for session sto behavior."""
        self.assertIn(
            'ensure_runtime_directory "${TMPDIR}" "OMERO.web TMPDIR (session storage)"',
            self.bootstrap_text,
        )
        self.assertIn(
            "${TMPDIR:-}",
            self.bootstrap_text,
        )

    def test_bootstrap_repairs_plugin_tmp_subtrees_for_runtime_user(self) -> None:
        """Verify test bootstrap repairs plugin tmp subtrees fo behavior."""
        self.assertIn("repair_plugin_tmp_layout()", self.bootstrap_text)
        self.assertIn('local tmp_root="${OMERO_TMP_PATH:-}"', self.bootstrap_text)
        self.assertIn(
            'local server_runtime_user="${OMERO_SERVER_RUNTIME_USER:-omero-server}"',
            self.bootstrap_text,
        )
        self.assertIn('"${runtime_user}"|omeroweb-*', self.bootstrap_text)
        self.assertIn(
            'chown -R "${runtime_user}:${runtime_group}" "${top_level_entry}"',
            self.bootstrap_text,
        )
        self.assertIn("repair_plugin_tmp_layout", self.bootstrap_text)

    def test_bootstrap_verifies_runtime_user_write_path_instead_of_root_only(
        self,
    ) -> None:
        """Verify test bootstrap verifies runtime user write pa behavior."""
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
