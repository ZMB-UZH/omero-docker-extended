from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class TmpPermissionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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
                ensure_omero_tmp_layout "{tmp_root}" {current_uid} {current_gid} {current_uid} {current_gid} omero-server
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

    def test_server_bootstrap_removes_exact_legacy_lock_namespace(self) -> None:
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

    def _run_bash(self, script: str) -> None:
        subprocess.run(
            ["bash", "-lc", script],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _ownership(self, path: Path) -> tuple[int, int]:
        stat_result = path.stat()
        return stat_result.st_uid, stat_result.st_gid

    def _slice_function(self, content: str, start_marker: str, end_marker: str) -> str:
        start = content.index(start_marker)
        end = content.index(end_marker, start)
        return content[start:end].rstrip()


if __name__ == "__main__":
    unittest.main()
