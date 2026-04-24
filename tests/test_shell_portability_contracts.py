"""Shell portability and boundary contracts."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


BASH_BIN = "/bin/bash"


class ShellPortabilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_tracked_shell_scripts_avoid_bash_regex_operator(self) -> None:
        git_path = shutil.which("git")
        self.assertIsNotNone(git_path)
        result = subprocess.run(
            [
                git_path,
                "ls-files",
                "*.sh",
                "*.bash",
                "github_pull_project_bash_example",
                "helper_scripts_debian/*",
            ],
            cwd=self.repo_root,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        regex_operator = re.compile(r"\[\[[^\n\]]*=~|=~")
        offenders: dict[str, list[str]] = {}
        for relative_path in result.stdout.splitlines():
            path = self.repo_root / relative_path
            if not path.is_file():
                continue
            matches = [
                f"{line_number}: {line.strip()}"
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(),
                    start=1,
                )
                if regex_operator.search(line)
            ]
            if matches:
                offenders[relative_path] = matches

        self.assertFalse(offenders, msg=f"Bash regex operator remains: {offenders}")

    def test_ext4_quota_enforcer_matches_group_names_literally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin = temp_path / "bin"
            fake_bin.mkdir()
            self._write_fake_command(fake_bin / "chattr")
            self._write_fake_command(fake_bin / "setquota")

            mount_path = temp_path / "mount"
            group_path = mount_path / "team.a"
            group_path.mkdir(parents=True)
            projects_file = temp_path / "quota" / "projects"
            projid_file = temp_path / "quota" / "projid"
            projects_file.parent.mkdir()
            projects_file.write_text("", encoding="utf-8")
            projid_file.write_text("teamxa:210000\n", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env.get('PATH', '')}",
                    "ADMIN_TOOLS_QUOTA_PROJECTS_FILE": str(projects_file),
                    "ADMIN_TOOLS_QUOTA_PROJID_FILE": str(projid_file),
                    "ADMIN_TOOLS_QUOTA_LOCK_PATH": str(temp_path / "quota.lock"),
                    "ADMIN_TOOLS_QUOTA_PROJECT_ID_MIN": "200000",
                }
            )

            result = subprocess.run(
                [
                    BASH_BIN,
                    str(self.repo_root / "startup/60-enforce-ext4-project-quota.sh"),
                    "--group",
                    "team.a",
                    "--group-path",
                    str(group_path),
                    "--quota-gb",
                    "1",
                    "--mount-point",
                    str(mount_path),
                ],
                cwd=self.repo_root,
                env=env,
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(
                projid_file.read_text(encoding="utf-8").splitlines(),
                ["teamxa:210000", "team.a:210001"],
            )
            self.assertEqual(
                projects_file.read_text(encoding="utf-8").strip(),
                f"210001:{group_path}",
            )

    @staticmethod
    def _write_fake_command(path: Path) -> None:
        path.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                exit 0
                """
            ),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
