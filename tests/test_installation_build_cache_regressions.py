"""Regression tests for installation build-cache behavior."""

from __future__ import annotations

import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallationBuildCacheRegressionTests(unittest.TestCase):
    """Exercise installer cache behavior in both compose and Buildx modes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.script_path = cls.repo_root / "installation" / "installation_script.sh"
        cls.script_text = cls.script_path.read_text(encoding="utf-8")
        cls.build_functions = cls._extract_script_block(
            "resolve_buildx_inline_cache_setting() {",
            "resolve_buildx_local_cache_dir() {",
        )
        cls.cleanup_functions = cls._extract_script_block(
            "resolve_buildx_local_cache_dir() {",
            "compose_with_installation_env() {",
        )

    @classmethod
    def _extract_script_block(cls, start_marker: str, end_marker: str) -> str:
        start = cls.script_text.find(start_marker)
        if start == -1:
            raise AssertionError(f"Unable to find script marker: {start_marker}")

        end = cls.script_text.find(end_marker, start)
        if end == -1:
            raise AssertionError(f"Unable to find script marker: {end_marker}")

        return cls.script_text[start:end]

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_compose_mode_disables_cache_and_uses_no_cache_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_path = temp_path / "compose.log"
            helper_path = temp_path / "helper.sh"
            helper_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            helper_path.chmod(helper_path.stat().st_mode | stat.S_IXUSR)

            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    {self.build_functions}
                    compose_with_installation_env() {{
                        printf '%s\\n' "$*" >> "{log_path}"
                    }}
                    USE_BUILDX_COMPRESSED_BUILD=0
                    USE_CACHE_BUILD=0
                    APPLY_SECURITY_HARDENING=0
                    ENABLE_VULNERABILITY_SCAN=0
                    DOCKER_BUILD_PROVENANCE=0
                    DOCKER_BUILD_FLATTEN_FINAL_IMAGE=0
                    COMPOSE_FILE="{temp_path / 'docker-compose.yml'}"
                    OMERO_INSTALLATION_PATH="{temp_path}"
                    BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH="{helper_path.name}"
                    run_image_build
                    """,
                ),
            )

            result = subprocess.run(
                ["bash", str(harness_path)],
                cwd=temp_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            compose_log = log_path.read_text(encoding="utf-8").strip()
            self.assertIn("build --no-cache --provenance false", compose_log)

    def test_buildx_mode_disables_all_cache_knobs_for_no_cache_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_log_path = temp_path / "buildx-env.log"
            helper_path = temp_path / "helper.sh"
            self._write_executable(
                helper_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    {{
                        printf 'DOCKER_BUILD_INLINE_CACHE=%s\\n' "${{DOCKER_BUILD_INLINE_CACHE:-}}"
                        printf 'DOCKER_BUILD_NO_CACHE=%s\\n' "${{DOCKER_BUILD_NO_CACHE:-}}"
                        printf 'DOCKER_BUILD_LOCAL_CACHE_ENABLED=%s\\n' "${{DOCKER_BUILD_LOCAL_CACHE_ENABLED:-}}"
                        printf 'DOCKER_BUILD_LOCAL_CACHE_MODE=%s\\n' "${{DOCKER_BUILD_LOCAL_CACHE_MODE:-}}"
                    }} > "{env_log_path}"
                    """,
                ),
            )

            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    {self.build_functions}
                    USE_BUILDX_COMPRESSED_BUILD=1
                    USE_CACHE_BUILD=0
                    APPLY_SECURITY_HARDENING=0
                    ENABLE_VULNERABILITY_SCAN=0
                    DOCKER_BUILD_PROVENANCE=0
                    DOCKER_BUILD_FLATTEN_FINAL_IMAGE=0
                    DOCKER_BUILD_LOCAL_CACHE_ENABLED=1
                    DOCKER_BUILD_LOCAL_CACHE_MODE=min
                    COMPOSE_FILE="{temp_path / 'docker-compose.yml'}"
                    OMERO_INSTALLATION_PATH="{temp_path}"
                    BUILDX_COMPRESSED_BUILD_SCRIPT_RELATIVE_PATH="{helper_path.name}"
                    run_image_build
                    """,
                ),
            )

            result = subprocess.run(
                ["bash", str(harness_path)],
                cwd=temp_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            env_log = env_log_path.read_text(encoding="utf-8")
            self.assertIn("DOCKER_BUILD_INLINE_CACHE=0", env_log)
            self.assertIn("DOCKER_BUILD_NO_CACHE=1", env_log)
            self.assertIn("DOCKER_BUILD_LOCAL_CACHE_ENABLED=0", env_log)
            self.assertIn("DOCKER_BUILD_LOCAL_CACHE_MODE=min", env_log)

    def test_cleanup_prunes_docker_builder_and_buildx_cache_in_buildx_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bin_dir = temp_path / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            docker_log_path = temp_path / "docker.log"
            buildx_cache_dir = temp_path / "data" / "buildx_cache"
            buildx_cache_dir.mkdir(parents=True, exist_ok=True)
            (buildx_cache_dir / "marker.txt").write_text("cache", encoding="utf-8")

            fake_docker_path = bin_dir / "docker"
            self._write_executable(
                fake_docker_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\\n' "$*" >> "{docker_log_path}"
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "--help" ]; then
                        exit 0
                    fi
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "-a" ] && [ "${{4:-}}" = "-f" ]; then
                        exit 0
                    fi
                    exit 0
                    """,
                ),
            )

            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    export PATH="{bin_dir}:$PATH"
                    {self.cleanup_functions}
                    USE_CACHE_BUILD=0
                    USE_BUILDX_COMPRESSED_BUILD=1
                    OMERO_DATA_PATH="{temp_path / 'data'}"
                    cleanup_local_build_cache_if_disabled
                    """,
                ),
            )

            result = subprocess.run(
                ["bash", str(harness_path)],
                cwd=temp_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Removed docker builder cache.", result.stdout)
            self.assertIn("Removed Buildx local cache directory:", result.stdout)
            self.assertFalse(buildx_cache_dir.exists())
            docker_log = docker_log_path.read_text(encoding="utf-8")
            self.assertIn("builder prune --help", docker_log)
            self.assertIn("builder prune -a -f", docker_log)

    def test_cleanup_skips_buildx_cache_directory_in_compose_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bin_dir = temp_path / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            docker_log_path = temp_path / "docker.log"
            buildx_cache_dir = temp_path / "data" / "buildx_cache"
            buildx_cache_dir.mkdir(parents=True, exist_ok=True)
            marker_path = buildx_cache_dir / "marker.txt"
            marker_path.write_text("cache", encoding="utf-8")

            fake_docker_path = bin_dir / "docker"
            self._write_executable(
                fake_docker_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\\n' "$*" >> "{docker_log_path}"
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "--help" ]; then
                        exit 0
                    fi
                    if [ "${{1:-}}" = "builder" ] && [ "${{2:-}}" = "prune" ] && [ "${{3:-}}" = "-a" ] && [ "${{4:-}}" = "-f" ]; then
                        exit 0
                    fi
                    exit 0
                    """,
                ),
            )

            harness_path = temp_path / "run.sh"
            self._write_executable(
                harness_path,
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    export PATH="{bin_dir}:$PATH"
                    {self.cleanup_functions}
                    USE_CACHE_BUILD=0
                    USE_BUILDX_COMPRESSED_BUILD=0
                    OMERO_DATA_PATH="{temp_path / 'data'}"
                    cleanup_local_build_cache_if_disabled
                    """,
                ),
            )

            result = subprocess.run(
                ["bash", str(harness_path)],
                cwd=temp_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Removed docker builder cache.", result.stdout)
            self.assertTrue(buildx_cache_dir.exists())
            self.assertTrue(marker_path.exists())
            self.assertNotIn("Removed Buildx local cache directory:", result.stdout)
            docker_log = docker_log_path.read_text(encoding="utf-8")
            self.assertIn("builder prune --help", docker_log)
            self.assertIn("builder prune -a -f", docker_log)


if __name__ == "__main__":
    unittest.main()
