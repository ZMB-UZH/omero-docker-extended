from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class TmpPermissionRegressionTests(unittest.TestCase):
    """Test cases for tmp permission regression tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare shared fixtures for `TmpPermissionRegressionTests` checks.

        Inputs: unittest supplies the class. Output: prepares shared fixtures for these checks.
        """
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.installation_script = (
            cls.repo_root / "installation" / "installation_script.sh"
        ).read_text(encoding="utf-8")
        cls.server_bootstrap_script = (
            cls.repo_root / "startup" / "10-server-bootstrap.sh"
        ).read_text(encoding="utf-8")

    def test_installation_layout_keeps_server_namespace_owned_by_server_uid(
        self,
    ) -> None:
        """Check that installation layout keeps server namespace owned by server uid remains stable.

        Inputs: repository fixtures. Output: fails on regressions in installation layout keeps server namespace owned by server uid.
        """
        function_text = self._slice_function(
            self.installation_script,
            "ensure_omero_tmp_layout() {",
            'if ! chown_tree_or_die "${OMERO_USER_DATA_PATH}"',
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir) / "omero_temp"
            current_uid = os.getuid()
            current_gid = os.getgid()
            server_lock_dir = (
                tmp_root / "omero-server" / "tmp" / "omero_omero-server" / "1477"
            )
            web_plugin_dir = tmp_root / "omeroweb-import" / "jobs"
            server_lock_dir.mkdir(parents=True, exist_ok=True)
            web_plugin_dir.mkdir(parents=True, exist_ok=True)
            lock_file = server_lock_dir / ".lock"
            lock_file.write_text("locked", encoding="utf-8")

            tmp_root.chmod(0o700)
            (tmp_root / "omero-server").chmod(0o755)
            (tmp_root / "omero-server" / "tmp").chmod(0o755)
            web_plugin_dir.chmod(0o700)

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                {function_text}
                ensure_omero_tmp_layout "{tmp_root}" {current_uid} {current_gid} {current_uid} {current_gid} omero-server omero-web
                """
            )
            self._run_bash(script)

            self.assertEqual((current_uid, current_gid), self._ownership(tmp_root))
            self.assertEqual(
                (current_uid, current_gid), self._ownership(tmp_root / "omero-server")
            )
            self.assertEqual(
                (current_uid, current_gid),
                self._ownership(tmp_root / "omero-server" / "tmp"),
            )
            self.assertEqual(
                (current_uid, current_gid), self._ownership(server_lock_dir)
            )
            self.assertEqual((current_uid, current_gid), self._ownership(lock_file))
            self.assertEqual(
                (current_uid, current_gid), self._ownership(web_plugin_dir)
            )
            self.assertEqual(0o755, tmp_root.stat().st_mode & 0o777)
            self.assertEqual(0o700, (tmp_root / "omero-server").stat().st_mode & 0o777)
            self.assertEqual(
                0o700, (tmp_root / "omero-server" / "tmp").stat().st_mode & 0o777
            )

    def test_installation_layout_creates_web_tmp_directory(self) -> None:
        """Verify installation layout creates web tmp directory.

        Inputs: repository fixtures. Output: fails on regressions in installation layout creates web tmp directory.
        """
        function_text = self._slice_function(
            self.installation_script,
            "ensure_omero_tmp_layout() {",
            'if ! chown_tree_or_die "${OMERO_USER_DATA_PATH}"',
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir) / "omero_temp"
            current_uid = os.getuid()
            current_gid = os.getgid()

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                {function_text}
                ensure_omero_tmp_layout "{tmp_root}" {current_uid} {current_gid} {current_uid} {current_gid} omero-server omero-web
                """
            )
            self._run_bash(script)

            web_tmp = tmp_root / "omero-web" / "tmp"
            self.assertTrue(
                web_tmp.is_dir(),
                "ensure_omero_tmp_layout must create omero-web/tmp",
            )
            self.assertEqual(
                (current_uid, current_gid),
                self._ownership(web_tmp),
            )
            self.assertEqual(
                (current_uid, current_gid),
                self._ownership(tmp_root / "omero-web"),
            )

    def test_server_bootstrap_removes_exact_legacy_lock_namespace(self) -> None:
        """Check server bootstrap removes exact legacy lock namespace cleanup behavior.

        Inputs: repository fixtures. Output: fails on regressions in server bootstrap removes exact legacy lock namespace.
        """
        function_text = self._slice_function(
            self.server_bootstrap_script,
            "ensure_tmpdir_permissions() {",
            "validate_ldap_configuration() {",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir) / "omero_temp"
            server_home = Path(tmpdir) / "server" / "OMERO.server"
            legacy_dir = tmp_root / "root" / "tmp" / "omero_root" / "1234"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            lock_file = legacy_dir / ".lock"
            lock_file.write_text("locked", encoding="utf-8")
            legacy_dir.parent.chmod(0o755)
            legacy_dir.chmod(0o755)

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                log() {{
                    :
                }}
                SERVER_HOME="{server_home}"
                OMERO_TMP_PATH="{tmp_root}"
                mkdir -p "$(dirname "$SERVER_HOME")"
                {function_text}
                ensure_tmpdir_permissions root
                test ! -e "{tmp_root}/root/tmp/omero_root"
                """
            )
            self._run_bash(script)

    def test_server_bootstrap_keeps_cli_tmp_namespace_private(self) -> None:
        """Check server bootstrap preserves private CLI temp permissions.

        Inputs: repository fixtures. Output: asserts server CLI runtime temp
        permissions stay private across service boundaries.
        """
        function_text = TmpPermissionRegressionTests._slice_function(
            self.server_bootstrap_script,
            "ensure_tmpdir_permissions() {",
            "validate_ldap_configuration() {",
        )

        expected_fragments = (
            'chmod 0700 "${expected_tmp_dir}"',
            'chmod 0700 "${candidate_dir}"',
            'chmod 0700 "${candidate_omero_py_dir}" "${candidate_omero_py_user_dir}"',
            'chmod 0700 "${omero_py_dir}" "${omero_py_user_dir}"',
        )
        for expected in expected_fragments:
            self.assertIn(expected, function_text)
        self.assertNotIn("chmod 0777", function_text)

    @staticmethod
    def _run_bash(script: str) -> None:
        """Run the bash for `TmpPermissionRegressionTests`.

        Inputs: `script` (str). Output: None.
        """
        subprocess.run(
            [BASH_BIN, "-lc", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @staticmethod
    def _ownership(path: Path) -> tuple[int, int]:
        """Return the ownership for `TmpPermissionRegressionTests`.

        Inputs: `path` (Path) path. Output: `tuple[int, int]`.
        """
        stat_result = path.stat()
        return stat_result.st_uid, stat_result.st_gid

    @staticmethod
    def _slice_function(content: str, start_marker: str, end_marker: str) -> str:
        """Return the slice function for `TmpPermissionRegressionTests`.

        Inputs: `content` (str), `start_marker` (str), `end_marker` (str). Output:
        `str`.
        """
        start = content.index(start_marker)
        end = content.index(end_marker, start)
        return content[start:end].rstrip()


if __name__ == "__main__":
    unittest.main()
